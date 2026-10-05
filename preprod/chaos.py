"""Chaos experiments against the running pre-prod environment.

    python preprod/chaos.py OUT_DIR [CHAOS-01 CHAOS-02 ...]

Each experiment breaks one thing on purpose, observes, puts it back, and writes OUT_DIR/<id>.json:
its hypothesis, what was observed, and each check with pass or fail. Exits non-zero if any fails.
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("BASE_URL", "http://localhost:8100")
COMPOSE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docker-compose.yml")
PASSWORD = "monsoon-mango-42"


# ── plumbing ─────────────────────────────────────────────────────────────────

def compose(*args, check=True):
    return subprocess.run(["docker", "compose", "-f", COMPOSE_FILE, *args], capture_output=True, text=True, check=check)


HOSTS = ("edge", "trading", "money", "street")


def all_healthy():
    """Every host's health check passes (each checks every service it runs, not just the first to start)."""
    for host in HOSTS:
        r = compose("ps", "--format", "{{.Health}}", host, check=False)
        if r.stdout.strip() != "healthy":
            return False
    return True


def inside(service, url):
    """GETs a URL from inside a container (health and monitoring ports aren't published)."""
    r = compose("exec", "-T", service, "wget", "-qO-", url, check=False)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None


def call(method, path, body=None, token=None, ip="198.19.200.1", timeout=10, key=None):
    """Returns (status, json body, headers with lower-case names, seconds)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("CF-Connecting-IP", ip)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if key:
        req.add_header("Idempotency-Key", key)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw, headers = r.status, r.read(), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        status, raw, headers = e.code, e.read(), {k.lower(): v for k, v in e.headers.items()}
    except Exception as e:  # timeouts, refused connections
        return None, {"error": str(e)}, {}, time.monotonic() - start
    took = time.monotonic() - start
    try:
        payload = json.loads(raw) if raw else {}
    except ValueError:
        payload = {}
    return status, payload, headers, took


def new_token(ip):
    email = f"chaos-{uuid.uuid4()}@example.com"
    call("POST", "/api/identity/v1/users", {"email": email, "password": PASSWORD, "displayName": "Chaos"}, ip=ip)
    status, body, _, _ = call("POST", "/api/identity/v1/sessions", {"email": email, "password": PASSWORD}, ip=ip)
    return body["tokens"]["accessToken"]


class Stream:
    """Reads a price stream in the background, counting ticks and noticing when it ends."""

    def __init__(self, symbols, token, ip):
        req = urllib.request.Request(f"{BASE}/api/marketdata/v1/stream?symbols={symbols}")
        req.add_header("Authorization", "Bearer " + token)
        req.add_header("CF-Connecting-IP", ip)
        req.add_header("Accept", "text/event-stream")
        self.response = urllib.request.urlopen(req, timeout=60)
        self.ticks = 0
        self.ended_at = None
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            for line in self.response:
                if line.startswith(b"event:tick"):
                    self.ticks += 1
        except Exception:
            pass
        self.ended_at = time.monotonic()

    def close(self):
        try:
            self.response.close()
        except Exception:
            pass


def wait_until(predicate, timeout, step=0.5):
    """Seconds until predicate() was true, or None if it never was."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if predicate():
            return round(time.monotonic() - start, 1)
        time.sleep(step)
    return None


def wait_for_open_market(min_minutes_left=60):
    """The accelerated market closes between sessions; start experiments with time to spare."""
    def ready():
        s, m, _, _ = call("GET", "/api/marketdata/v1/market")
        if s != 200 or m.get("state") != "OPEN":
            return False
        hh, mm = int(m["marketTime"][11:13]), int(m["marketTime"][14:16])
        return (15 * 60 + 30) - (hh * 60 + mm) >= min_minutes_left
    if wait_until(ready, 120) is None:
        raise RuntimeError("the market never opened with time to spare")


def result(eid, title, hypothesis, observations, checks):
    return {"id": eid, "title": title, "hypothesis": hypothesis,
            "observations": [{"what": k, "value": v} for k, v in observations],
            "checks": [{"what": k, "pass": bool(v)} for k, v in checks],
            "pass": all(v for _, v in checks)}


def fmt(status, took):
    return f"{status} in {took * 1000:,.0f} ms" if status else f"no answer after {took:.1f} s"


# ── experiments ──────────────────────────────────────────────────────────────

def chaos_01():
    ip = "198.19.201.1"
    wrong = {"email": "nobody@example.com", "password": "whatever-password"}
    before = call("POST", "/api/identity/v1/sessions", wrong, ip=ip)
    compose("stop", "postgres")
    down = [call("POST", "/api/identity/v1/sessions", wrong, ip=f"198.19.201.{10 + i}") for i in range(3)]
    compose("start", "postgres")
    recovered = wait_until(lambda: call("POST", "/api/identity/v1/sessions", wrong, ip="198.19.201.50")[0] == 401, 60, 1)
    return result(
        "CHAOS-01", "The database goes away",
        "With Postgres stopped, sign-in answers 503 with Retry-After in under 3 s (never hanging until the "
        "gateway's 5 s timeout), and recovers within 30 s of Postgres returning, without a restart.",
        [("Before (wrong password, so 401 is healthy)", fmt(before[0], before[3])),
         *[(f"Database down, try {i + 1}", fmt(s, t)) for i, (s, _, _, t) in enumerate(down)],
         ("Retry-After", down[-1][2].get("retry-after", "none")),
         ("Answering normally again after Postgres started", f"{recovered} s" if recovered is not None else "never")],
        [("503 UPSTREAM_UNAVAILABLE every time", all(s == 503 and b.get("code") == "UPSTREAM_UNAVAILABLE" for s, b, _, _ in down)),
         ("each in under 3 s", all(t < 3 for _, _, _, t in down)),
         ("with Retry-After", all("retry-after" in h for _, _, h, _ in down)),
         ("recovered within 30 s without a restart", recovered is not None and recovered <= 30)])


def chaos_02():
    ip = "198.19.202.1"
    token = new_token(ip)
    wait_for_open_market()
    connected = lambda: (inside("trading", "http://127.0.0.1:8103/actuator/health") or {}).get("components", {}) \
        .get("nats", {}).get("details", {}).get("connected") is True
    was_connected = connected()
    stream = Stream("HARBOR,INKWELL", token, ip)
    time.sleep(2)
    compose("stop", "nats")
    ticks_at_stop = stream.ticks
    time.sleep(10)
    ticks_during = stream.ticks - ticks_at_stop
    health = inside("trading", "http://127.0.0.1:8103/actuator/health") or {}
    quote = call("GET", "/api/marketdata/v1/quotes?symbols=HARBOR", token=token, ip=ip)
    compose("start", "nats")
    reconnected = wait_until(connected, 30)
    published = None
    if reconnected is not None:
        first = (inside("nats", "http://127.0.0.1:8222/varz") or {}).get("in_msgs", 0)
        time.sleep(3)
        published = (inside("nats", "http://127.0.0.1:8222/varz") or {}).get("in_msgs", 0) - first
    stream_alive = stream.ended_at is None
    stream.close()
    return result(
        "CHAOS-02", "NATS goes away",
        "With NATS stopped, prices keep streaming to clients and quotes keep working; the trading host stays "
        "healthy. When NATS returns, market data reconnects by itself within 30 s and publishes again.",
        [("NATS connected before", was_connected),
         ("Ticks streamed to a client in the 10 s NATS was down", ticks_during),
         ("Trading host health while NATS was down", health.get("status", "unreachable")),
         ("Quote while NATS was down", fmt(quote[0], quote[3])),
         ("Reconnected after NATS started", f"{reconnected} s" if reconnected is not None else "never"),
         ("Events published in 3 s after reconnecting", published)],
        [("prices kept streaming", ticks_during > 0),
         ("the stream stayed open", stream_alive),
         ("the host stayed healthy", health.get("status") == "UP"),
         ("quotes kept working", quote[0] == 200),
         ("reconnected within 30 s", reconnected is not None and reconnected <= 30),
         ("publishing again", (published or 0) > 0)])


def chaos_03():
    ip = "198.19.203.1"
    token = new_token(ip)
    wait_for_open_market()
    stream = Stream("HARBOR", token, ip)
    time.sleep(2)
    stopped_at = time.monotonic()
    compose("kill", "trading")
    stream_end = wait_until(lambda: stream.ended_at is not None, 15, 0.2)
    wrong = {"email": "nobody@example.com", "password": "whatever-password"}
    signin = call("POST", "/api/identity/v1/sessions", wrong, ip="198.19.203.20")
    me = call("GET", "/api/identity/v1/users/me", token=token, ip=ip)
    quote = call("GET", "/api/marketdata/v1/quotes?symbols=HARBOR", token=token, ip=ip)
    new_stream = call("GET", "/api/marketdata/v1/stream?symbols=HARBOR", token=token, ip=ip)
    compose("start", "trading")
    recovered = wait_until(lambda: call("GET", "/api/marketdata/v1/quotes?symbols=HARBOR", token=token, ip=ip)[0] == 200, 90, 1)
    edge_state = compose("ps", "edge", "--format", "{{.Status}}", check=False).stdout.strip()
    stream.close()
    return result(
        "CHAOS-03", "The trading host dies",
        "With the trading host killed, sign-in and accounts are unaffected (they run in a different JVM). "
        "Market data answers 503 within 3 s instead of hanging, open price streams end within 5 s so clients "
        "know to reconnect, and market data is back within 60 s of the host restarting.",
        [("Open stream ended after the kill", f"{stream_end} s" if stream_end is not None else "still open after 15 s"),
         ("Sign-in (wrong password, so 401 is healthy)", fmt(signin[0], signin[3])),
         ("My account", fmt(me[0], me[3])),
         ("A quote", fmt(quote[0], quote[3]) + f" ({quote[1].get('code', '')})"),
         ("Opening a new stream", fmt(new_stream[0], new_stream[3])),
         ("Quotes working again after restart", f"{recovered} s" if recovered is not None else "never"),
         ("Edge host", edge_state)],
        [("sign-in unaffected", signin[0] == 401 and signin[3] < 2),
         ("accounts unaffected", me[0] == 200),
         ("quotes fail fast with 503", quote[0] == 503 and quote[3] < 3),
         ("new streams refused fast", new_stream[0] in (502, 503) and new_stream[3] < 3),
         ("open streams end within 5 s", stream_end is not None and stream_end <= 5),
         ("market data back within 60 s", recovered is not None and recovered <= 60)])


# ── money ────────────────────────────────────────────────────────────────────

def sql_text(query):
    """A single text value from the database, or None."""
    r = compose("exec", "-T", "postgres", "psql", "-U", "sprout", "-d", "sprout", "-tAc", query, check=False)
    return r.stdout.strip() or None


def sql(query):
    """A number from the database, read inside the postgres container."""
    r = compose("exec", "-T", "postgres", "psql", "-U", "sprout", "-d", "sprout", "-tAc", query, check=False)
    out = r.stdout.strip()
    return int(out) if out.lstrip("-").isdigit() else None


def customer(ip):
    """A signed-in user with a Sprout Bank account (PIN 2580) and a Sprout account. Returns the token."""
    token = new_token(ip)
    bank = call("POST", "/api/bank/v1/accounts", {"holderName": "Chaos Test", "upiPin": "2580"}, token=token, ip=ip)[1]
    n = uuid.uuid4().int
    pan = "AB" + chr(65 + n % 26) + "P" + chr(65 + (n // 26) % 26) + f"{n % 10000:04d}" + "K"
    call("POST", "/api/accounts/v1/accounts", {"legalName": "Chaos Test", "dateOfBirth": "1995-01-01", "pan": pan,
                                               "bankVpa": bank["vpa"]}, token=token, ip=ip)
    return token


def deposit_status(token, ip, deposit_id):
    return call("GET", f"/api/payments/v1/deposits/{deposit_id}", token=token, ip=ip)[1].get("status")


def fund(token, ip, amount):
    d = call("POST", "/api/payments/v1/deposits", {"amount": amount}, token=token, ip=ip, key=str(uuid.uuid4()))[1]
    req = call("GET", "/api/bank/v1/requests?status=PENDING", token=token, ip=ip)[1]["requests"][0]
    call("POST", f"/api/bank/v1/requests/{req['id']}/approve", {"upiPin": "2580"}, token=token, ip=ip)
    wait_until(lambda: deposit_status(token, ip, d["id"]) == "COMPLETED", 20)


def balances(token, ip):
    b = call("GET", "/api/payments/v1/balance", token=token, ip=ip)[1]
    bank = call("GET", "/api/bank/v1/accounts/me", token=token, ip=ip)[1]
    return b.get("available"), b.get("withdrawing"), bank.get("balance")


def chaos_04():
    ip = "198.19.204.1"
    token = customer(ip)
    fund(token, ip, "1000")
    compose("stop", "street")
    start = time.monotonic()
    status, w, _, took = call("POST", "/api/payments/v1/withdrawals", {"amount": "400"}, token=token, ip=ip, key=str(uuid.uuid4()))
    during = balances(token, ip)
    compose("start", "street")
    done = wait_until(lambda: call("GET", f"/api/payments/v1/withdrawals/{w.get('id')}", token=token, ip=ip)[1].get("status") == "COMPLETED", 90, 1)
    after = balances(token, ip)
    return result(
        "CHAOS-04", "Sprout Bank goes away mid-withdrawal",
        "With the bank unreachable, a withdrawal is accepted and the money held (never lost, never paid twice); "
        "when the bank returns, the reconciler finishes it within 90 s and the money arrives in the bank exactly once.",
        [("Withdrawal while the bank was down", f"{status} {w.get('status')} in {took * 1000:,.0f} ms"),
         ("Available / withdrawing / bank balance while down", " / ".join(str(x) for x in during)),
         ("Completed after the bank came back", f"{done} s" if done is not None else "never"),
         ("Available / withdrawing / bank balance after", " / ".join(str(x) for x in after))],
        [("accepted and held, not refused or lost", status == 201 and w.get("status") == "PROCESSING" and during[0] == "600.00" and during[1] == "400.00"),
         ("answered without waiting for the bank", took < 6),
         ("completed within 90 s of the bank returning", done is not None and done <= 90),
         ("paid exactly once", after == ("600.00", "0.00", "99400.00"))])


def chaos_05():
    ip = "198.19.205.1"
    token = customer(ip)
    d = call("POST", "/api/payments/v1/deposits", {"amount": "750"}, token=token, ip=ip, key=str(uuid.uuid4()))[1]
    req = call("GET", "/api/bank/v1/requests?status=PENDING", token=token, ip=ip)[1]["requests"][0]
    compose("stop", "money")
    approved, body, _, _ = call("POST", f"/api/bank/v1/requests/{req['id']}/approve", {"upiPin": "2580"}, token=token, ip=ip)
    time.sleep(5)  # the bank tries to tell payments, and fails
    compose("start", "money")
    done = wait_until(lambda: deposit_status(token, ip, d["id"]) == "COMPLETED", 120, 1)
    available, _, bank = balances(token, ip)
    credited = sql(f"SELECT COUNT(*) FROM ledger.journal_entries WHERE reference = '{d['id']}'")
    return result(
        "CHAOS-05", "Payments is down when the customer approves",
        "The customer approves in the bank while the money host is down. The bank keeps the news and retries; "
        "when the money host is back, the deposit completes within 120 s and is credited exactly once.",
        [("Approval in the bank (money host down)", f"{approved} {body.get('status')}"),
         ("Deposit completed after the money host started", f"{done} s" if done is not None else "never"),
         ("Sprout cash / bank balance", f"{available} / {bank}"),
         ("Ledger entries for this deposit", credited)],
        [("the customer could still approve", approved == 200),
         ("completed within 120 s of the money host returning", done is not None and done <= 120),
         ("credited exactly once", available == "750.00" and credited == 1),
         ("the bank's side matches", bank == "99250.00")])


def recon_01():
    ledger_bank = sql("SELECT balance_paise FROM ledger.accounts WHERE name = 'sprout:bank'") or 0
    bank_holds = sql("SELECT balance_paise FROM bank.accounts WHERE vpa = 'sprout@sproutbank'") or 0
    assets = sql("SELECT COALESCE(SUM(balance_paise), 0) FROM ledger.accounts WHERE kind = 'ASSET'")
    liabilities = sql("SELECT COALESCE(SUM(balance_paise), 0) FROM ledger.accounts WHERE kind = 'LIABILITY'")
    stuck = sql("SELECT COUNT(*) FROM payments.withdrawals WHERE status = 'PROCESSING'")
    rupees = lambda p: f"₹{p / 100:,.2f}"
    return result(
        "RECON-01", "The books agree with the bank",
        "After every test and every failure above: the ledger balances (assets equal liabilities), and what it says "
        "Sprout holds at the bank is exactly what Sprout Bank says it holds, to the paisa.",
        [("Ledger assets / liabilities", f"{rupees(assets)} / {rupees(liabilities)}"),
         ("Ledger: Sprout's money at the bank", rupees(ledger_bank)),
         ("Sprout Bank: Sprout's account", rupees(bank_holds)),
         ("Withdrawals still in progress", stuck)],
        [("the ledger balances", assets == liabilities),
         ("the ledger matches the bank", ledger_bank == bank_holds),
         ("nothing left in progress", stuck == 0)])


# ── trading ──────────────────────────────────────────────────────────────────

def funds(token, ip):
    return call("GET", "/api/oms/v1/funds", token=token, ip=ip)[1]


def chaos_06():
    ip = "198.19.206.1"
    token = customer(ip)
    fund(token, ip, "20000")
    wait_for_open_market(30)
    compose("stop", "street")
    status, o, _, took = call("POST", "/api/oms/v1/orders", {"symbol": "HARBOR", "side": "BUY", "quantity": 2, "orderType": "MARKET",
                                                            "product": "CNC"}, token=token, ip=ip, key=str(uuid.uuid4()))
    during = funds(token, ip)
    compose("start", "street")
    order = lambda: call("GET", f"/api/oms/v1/orders/{o.get('id')}", token=token, ip=ip)[1]
    ended = wait_until(lambda: order().get("status") not in ("PENDING", None), 120, 1)
    final = order()
    after = funds(token, ip)
    return result(
        "CHAOS-06", "The exchange goes away mid-order",
        "With the exchange unreachable, an order is accepted with its money blocked and left PENDING (its fate unknown, "
        "so not guessed); when the exchange is back, the reconciler finds it never arrived, rejects it within 120 s, "
        "and every paisa blocked for it is back.",
        [("Order while the exchange was down", f"{status} {o.get('status')} in {took * 1000:,.0f} ms, blocked ₹{o.get('blocked')}"),
         ("Cash / blocked while down", f"{during.get('cash')} / {during.get('blocked')}"),
         ("Ended after the exchange came back", f"{final.get('status')} after {ended} s" if ended is not None else "never"),
         ("Rejection", (final.get("rejection") or {}).get("code")),
         ("Cash / blocked after", f"{after.get('cash')} / {after.get('blocked')}")],
        [("accepted, money blocked, outcome left open", status == 201 and o.get("status") == "PENDING" and float(o.get("blocked", 0)) > 0),
         ("answered without waiting for the exchange", took < 6),
         ("ended within 120 s of the exchange returning", ended is not None and ended <= 120),
         ("rejected as never placed (not filled from nowhere)", final.get("status") == "REJECTED"),
         ("every paisa back", after.get("cash") == "20000.00" and after.get("blocked") == "0.00")])


def recon_02():
    # let in-flight callbacks and ledger postings land first
    wait_until(lambda: sql("SELECT COUNT(*) FROM oms.ledger_outbox WHERE posted_at IS NULL") == 0
               and sql("SELECT COUNT(*) FROM exchange.outbox WHERE delivered_at IS NULL") == 0, 60, 1)
    filled = sql("SELECT COUNT(*) FROM oms.orders WHERE status = 'FILLED'")
    trades = sql("SELECT COUNT(*) FROM exchange.trades")
    mismatched = sql("""SELECT COUNT(*) FROM oms.orders o LEFT JOIN exchange.orders e ON e.client_order_id = o.id::text
                        WHERE o.status = 'FILLED' AND (e.status IS DISTINCT FROM 'FILLED' OR e.price_paise <> o.fill_price_paise
                                                       OR e.quantity <> o.quantity)""")
    orphans = sql("""SELECT COUNT(*) FROM exchange.orders e LEFT JOIN oms.orders o ON e.client_order_id = o.id::text
                     WHERE e.status = 'FILLED' AND o.status IS DISTINCT FROM 'FILLED'""")
    holds = sql("""WITH expected AS (
                       SELECT user_id, SUM(paise) AS paise FROM (
                           SELECT user_id, blocked_paise AS paise FROM oms.orders
                           UNION ALL SELECT user_id, margin_paise FROM oms.positions) x GROUP BY user_id),
                   held AS (
                       SELECT CAST(substring(name FROM 10 FOR 36) AS uuid) AS user_id, balance_paise AS paise
                       FROM ledger.accounts WHERE name LIKE 'customer:%:order-hold')
                   SELECT COUNT(*) FROM expected e FULL JOIN held h ON h.user_id = e.user_id
                   WHERE COALESCE(e.paise, 0) <> COALESCE(h.paise, 0)""")
    unposted = sql("SELECT COUNT(*) FROM oms.ledger_outbox WHERE posted_at IS NULL")
    # placed (or sent) over 2 minutes ago and still unconfirmed; not updated_at, which every question touches
    stuck = sql("SELECT COUNT(*) FROM oms.orders WHERE status = 'PENDING' AND COALESCE(sent_at, created_at) < now() - interval '2 minutes'")
    return result(
        "RECON-02", "Orders, the exchange and the ledger agree",
        "After every test and every failure above: each order Sprout booked as executed was executed by the exchange, "
        "at the same price and quantity, and nothing the exchange executed is missing from Sprout; the money the ledger "
        "holds for each customer is exactly what their working orders and open positions say; every ledger entry "
        "Sprout decided on has been posted.",
        [("Orders executed (Sprout) / trades (exchange)", f"{filled} / {trades}"),
         ("Executed orders that differ from the exchange", mismatched),
         ("Exchange executions Sprout hasn't booked", orphans),
         ("Customers whose held money doesn't match their orders", holds),
         ("Ledger entries not yet posted", unposted),
         ("Orders still waiting on the exchange after 2 minutes", stuck)],
        [("every executed order matches the exchange", mismatched == 0 and filled == trades),
         ("nothing executed is missing", orphans == 0),
         ("held money matches orders and positions", holds == 0),
         ("every ledger entry posted", unposted == 0),
         ("nothing left hanging", stuck == 0)])


# ── settlement ───────────────────────────────────────────────────────────────

def lines_where(day, condition=None):
    extra = f" AND l.status = '{condition}'" if condition else ""
    return sql("SELECT COUNT(*) FROM clearing.lines l JOIN clearing.settlements s ON s.id = l.settlement_id "
               f"WHERE s.trade_date = '{day}'{extra}")


def settle_01():
    """The first trade date of the run (the E2E suite's) settles T+1, end to end."""
    first = sql_text("SELECT MIN(trade_date)::text FROM oms.orders WHERE status = 'FILLED'")
    if not first:
        raise RuntimeError("no trades to settle")
    status = lambda: sql_text(f"SELECT status FROM settlement.settlements WHERE trade_date = '{first}'")
    took = wait_until(lambda: status() in ("COMPLETED", "BREAK"), 15 * 60, 2)
    final = status()
    cc = sql_text(f"SELECT status || ' ' || funds_direction || ' ' || funds_paise FROM clearing.settlements WHERE trade_date = '{first}'")
    shorts = lines_where(first, "SHORT")
    breaks = sql("SELECT COUNT(*) FROM settlement.settlements WHERE status = 'BREAK'")
    released = sql(f"SELECT COUNT(*) FROM oms.settled_days WHERE trade_date = '{first}'")
    return result(
        "SETTLE-01", "A trading day settles T+1",
        "Once the next session begins, the clearing corporation nets the day's trades, takes in the sellers' shares, "
        "and tells Sprout what it owes or is owed; Sprout's back office finds that matches its own books exactly (no break), "
        "the money moves through Sprout Bank, buyers' shares reach their demat accounts, and clients' sale proceeds "
        "become cash. All within one session of the trade date.",
        [("Trade date", first),
         ("Back office", f"{final} after {took} s" if took is not None else f"{final} (timed out)"),
         ("Clearing corporation (status, funds, paise)", cc),
         ("Lines / delivered / short", f"{lines_where(first)} / {lines_where(first, 'DELIVERED')} / {shorts}"),
         ("Breaks", breaks),
         ("Clients settled for the day", released)],
        [("settled end to end", final == "COMPLETED"),
         ("the obligation matched Sprout's books (no break)", breaks == 0),
         ("nobody was short", shorts == 0),
         ("clients' proceeds and shares released", released == 1)])


def recon_03():
    settled = "SELECT trade_date FROM oms.settled_days"
    # shares: what the depository holds for each client = what Sprout says is delivered (held less T1)
    shares = sql("""WITH ours AS (
                        SELECT a.bo_id, h.symbol, h.quantity - h.t1_quantity AS qty
                        FROM oms.holdings h JOIN accounts.accounts a ON a.user_id = h.user_id
                        WHERE h.quantity - h.t1_quantity <> 0),
                    theirs AS (
                        SELECT bo_id, symbol, quantity AS qty FROM depository.holdings
                        WHERE quantity <> 0 AND bo_id IN (SELECT bo_id FROM depository.accounts WHERE NOT settlement))
                    SELECT COUNT(*) FROM ours o FULL JOIN theirs t ON t.bo_id = o.bo_id AND t.symbol = o.symbol
                    WHERE COALESCE(o.qty, 0) <> COALESCE(t.qty, 0)""")
    # money: each client's unsettled money is exactly the proceeds of days not yet settled
    unsettled = sql(f"""WITH expected AS (
                            SELECT user_id, SUM(unsettled_paise) AS paise FROM oms.orders
                            WHERE status = 'FILLED' AND trade_date NOT IN ({settled}) GROUP BY user_id),
                        held AS (
                            SELECT CAST(substring(name FROM 10 FOR 36) AS uuid) AS user_id, balance_paise AS paise
                            FROM ledger.accounts WHERE name LIKE 'customer:%:unsettled')
                        SELECT COUNT(*) FROM expected e FULL JOIN held h ON h.user_id = e.user_id
                        WHERE COALESCE(e.paise, 0) <> COALESCE(h.paise, 0)""")
    # clearing balances: what's still owed either way is only the unsettled days' trades
    unsettled_days = f"FROM oms.orders WHERE status = 'FILLED' AND trade_date NOT IN ({settled})"
    open_payable = sql("SELECT COALESCE(SUM(CASE WHEN product = 'CNC' AND side = 'BUY' THEN fill_price_paise * quantity "
                       "WHEN product = 'MIS' AND realised_pnl_paise < 0 THEN -realised_pnl_paise ELSE 0 END), 0) " + unsettled_days)
    open_receivable = sql("SELECT COALESCE(SUM(CASE WHEN product = 'CNC' AND side = 'SELL' THEN fill_price_paise * quantity "
                          "WHEN product = 'MIS' AND realised_pnl_paise > 0 THEN realised_pnl_paise ELSE 0 END), 0) " + unsettled_days)
    payable = sql("SELECT COALESCE(SUM(balance_paise), 0) FROM ledger.accounts WHERE name = 'sprout:clearing-payable'")
    receivable = sql("SELECT COALESCE(SUM(balance_paise), 0) FROM ledger.accounts WHERE name = 'sprout:clearing-receivable'")
    days = sql("SELECT COUNT(*) FROM oms.settled_days")
    rupees = lambda p: f"₹{(p or 0) / 100:,.2f}"
    return result(
        "RECON-03", "After settlement, shares and money agree everywhere",
        "For every client, the shares the depository holds in their demat account are exactly the delivered shares Sprout "
        "shows them; their unsettled money is exactly the proceeds of days not yet settled; and what the ledger says Sprout "
        "owes or is owed by the clearing corporation is exactly the unsettled days' trades.",
        [("Trade dates settled", days),
         ("Clients whose demat holdings differ from Sprout's", shares),
         ("Clients whose unsettled money is wrong", unsettled),
         ("Owed to clearing: ledger / unsettled trades", f"{rupees(payable)} / {rupees(open_payable)}"),
         ("Owed by clearing: ledger / unsettled trades", f"{rupees(receivable)} / {rupees(open_receivable)}")],
        [("at least one day settled", (days or 0) >= 1),
         ("demat holdings match", shares == 0),
         ("unsettled money matches", unsettled == 0),
         ("clearing balances are only the unsettled days'", payable == open_payable and receivable == open_receivable)])


EXPERIMENTS = {"CHAOS-01": chaos_01, "CHAOS-02": chaos_02, "CHAOS-03": chaos_03, "CHAOS-04": chaos_04,
               "CHAOS-05": chaos_05, "CHAOS-06": chaos_06, "SETTLE-01": settle_01, "RECON-01": recon_01, "RECON-02": recon_02,
               "RECON-03": recon_03}


def main():
    out = sys.argv[1]
    wanted = sys.argv[2:] or list(EXPERIMENTS)
    os.makedirs(out, exist_ok=True)
    failed = []
    for eid in wanted:
        print(f"> {eid}", flush=True)
        # each experiment starts from a steady state: an earlier one may have just restarted a host
        if wait_until(all_healthy, 180, 2) is None:
            print("  (hosts not all healthy after 180 s; running anyway)", flush=True)
        try:
            r = EXPERIMENTS[eid]()
        except Exception as e:
            r = result(eid, eid, "", [("error", repr(e))], [("ran to completion", False)])
        with open(os.path.join(out, f"{eid.lower()}.json"), "w", encoding="utf-8") as f:
            json.dump(r, f, indent=2)
        for c in r["checks"]:
            print(f"  {'pass' if c['pass'] else 'FAIL'}  {c['what']}")
        with open(os.path.join(out, "stages.txt"), "a", encoding="utf-8") as f:
            f.write(f"{eid.lower()}={'pass' if r['pass'] else 'fail'}\n")
        if not r["pass"]:
            failed.append(eid)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
