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


EXPERIMENTS = {"CHAOS-01": chaos_01, "CHAOS-02": chaos_02, "CHAOS-03": chaos_03, "CHAOS-04": chaos_04,
               "CHAOS-05": chaos_05, "RECON-01": recon_01}


def main():
    out = sys.argv[1]
    wanted = sys.argv[2:] or list(EXPERIMENTS)
    os.makedirs(out, exist_ok=True)
    failed = []
    for eid in wanted:
        print(f"> {eid}", flush=True)
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
