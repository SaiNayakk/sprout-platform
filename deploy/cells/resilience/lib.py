"""Shared pieces of the resilience suite: the two cells as a cluster you can poke, customers who keep ordering, a timeline of what
each cell said, and the check that matters: every order a customer was told succeeded exists in the end, once.

Run from the laptop with both cells up. Customers are real (created through the public address in the cell under test), so a
scenario exercises the whole path: web, gateway, services, journal, replication, takeover, failback."""
import csv
import datetime
import json
import os
import random
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'deploy' / 'cells'))
import chaos12 as c12  # noqa: E402  (call, customer, SSH, CHEAP: the helpers every chaos test here shares)

LAPTOP_DATA = ROOT / 'deploy' / 'laptop' / 'data'
PHONE_CELLS = '~/sprout/cells'
ENVF = dict(l.rstrip('\n').split('=', 1) for l in open(LAPTOP_DATA / '.env', encoding='utf-8') if '=' in l and not l.startswith('#'))
RESULTS = ROOT / 'deploy' / 'cells' / 'results'


def now():
    return time.time()


def say(msg):
    print(f'{datetime.datetime.now():%H:%M:%S} {msg}', flush=True)


# ── the cluster ──────────────────────────────────────────────────────────────

def status(cell, timeout=8):
    """A cell's published status, as anyone outside sees it, or None."""
    try:
        req = urllib.request.Request(f'https://sprout-{cell}-saiworks.nncs.in/cells/status.json',
                                     headers={'User-Agent': 'sprout-resilience', 'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def state(cell):
    s = status(cell)
    return (s['state'] + ('' if s.get('healthy', True) else '/sick')) if s else 'silent'


def states():
    return state('a'), state('b')


def wait_states(pred, timeout, every=4):
    """Waits until pred(state_a, state_b) is true; returns the seconds it took, or None."""
    t0 = now()
    while now() - t0 < timeout:
        a, b = states()
        if pred(a, b):
            return round(now() - t0)
        time.sleep(every)
    return None


def phone(cmd, stdin=None, timeout=90):
    r = subprocess.run(c12.SSH + [cmd], input=stdin, capture_output=True, text=True, timeout=timeout)
    if r.returncode == 255:     # ssh itself failed: never read that as an empty answer (2026-10-28: a stale address made every order look missing)
        raise RuntimeError(f'cannot reach the phone: {r.stderr.strip()[:200]}')
    return r.stdout.strip()


def laptop_psql(db, sql, timeout=60):
    r = subprocess.run(['docker', 'exec', '-i', '-e', f'PGPASSWORD={ENVF["SPROUT_DB_PASSWORD"]}', 'sprout-laptop-postgres-1', 'psql', '-U', 'sprout',
                        '-d', db, '-At'], input=sql + ';\n', capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()


def phone_psql(db, sql, timeout=60):
    return phone(f'psql -d {db} -At', stdin=sql + ';\n', timeout=timeout)


def own_db_orders(cell, keys):
    """The idempotency keys among `keys` that exist, with counts, in `cell`'s own database."""
    q = "('" + "','".join(keys) + "')"
    sql = f"SELECT idempotency_key || ' ' || count(*) FROM oms.orders WHERE idempotency_key IN {q} GROUP BY idempotency_key"
    out = laptop_psql('sprout', sql) if cell == 'b' else phone_psql('sprout', sql)
    return dict(l.split() for l in out.split('\n') if l.strip())


def partition(laptop=None, phone_side=None):
    """Blind a cell to the other: 'all' (both paths to the other cell), 'cf' (only the Cloudflare path), 'lan', 'witness' (only the
    witness) or 'everything' (the other cell and the witness); None leaves that side alone."""
    if laptop:
        (LAPTOP_DATA / 'cells' / 'partition').write_text('' if laptop == 'all' else laptop)
    if phone_side:
        phone(f"printf '%s' '{'' if phone_side == 'all' else phone_side}' > {PHONE_CELLS}/partition")


def heal():
    (LAPTOP_DATA / 'cells' / 'partition').unlink(missing_ok=True)
    phone(f'rm -f {PHONE_CELLS}/partition')


def laptop_cellwatch_log(n=12):
    p = LAPTOP_DATA / 'cells' / 'cellwatch.log'
    return p.read_text(encoding='utf-8').splitlines()[-n:] if p.exists() else []


def phone_cellwatch_log(n=12):
    return phone(f'tail -n {n} ~/sprout/logs/cellwatch.log').splitlines()


def freeze_phone_web(on):
    phone("pkill -%s -f '^nginx: '" % ('STOP' if on else 'CONT'))


def docker(*args, check=False):
    return subprocess.run(['docker', *args], capture_output=True, text=True, check=check).stdout


def ensure_clean(timeout=900):
    """Both cells NORMAL and replicating, or fail: every scenario starts and ends here."""
    t0 = now()
    while now() - t0 < timeout:
        a, b = states()
        if (a, b) == ('NORMAL', 'NORMAL'):
            ra, rb = status('a') or {}, status('b') or {}
            if (ra.get('repl') or {}).get('copy') and (rb.get('repl') or {}).get('copy'):
                return True
        time.sleep(5)
    return False


# ── customers who keep ordering ──────────────────────────────────────────────

class Load:
    """`n` customers of `cell` placing market orders through the public address, each with its own idempotency key; every order the
    cell acknowledged is recorded as it happens (the key, when, and what the cell said)."""

    def __init__(self, cell, n=6, tag='r'):
        self.cell, self.lock, self.stop_ev = cell, threading.Lock(), threading.Event()
        self.acked, self.statuses, self.threads = [], {}, []
        run = datetime.datetime.now().strftime('%m%d%H%M%S')
        say(f'creating {n} customers in cell {cell.upper()}')
        self.people = [c12.customer(cell, i, f'{tag}{run}') for i in range(n)]

    def _refresh(self, p):
        s, r = c12.call('POST', '/identity/v1/sessions', {'email': p['email'], 'password': c12.PASSWORD}, cell=self.cell)
        if s == 200 and r:
            p['token'] = r['tokens']['accessToken']

    def _trade(self, p):
        while not self.stop_ev.is_set():
            key = str(uuid.uuid4())
            sent = now()
            body = {'symbol': random.choice(c12.CHEAP), 'side': 'BUY', 'quantity': 1, 'orderType': 'MARKET', 'product': 'CNC'}
            s, r = 0, None
            for _ in range(3):
                s, r = c12.call('POST', '/oms/v1/orders', body, token=p['token'], cell=self.cell, key=key, timeout=20)
                if s == 401:
                    self._refresh(p)
                    continue
                if s != 0 and s < 500:
                    break
                time.sleep(2)
            with self.lock:
                self.statuses[s] = self.statuses.get(s, 0) + 1
                if s in (200, 201) and r and r.get('id'):
                    self.acked.append({'key': key, 'sent': sent, 'at': now()})
            time.sleep(random.uniform(2, 4))

    def start(self):
        self.threads = [threading.Thread(target=self._trade, args=(p,), daemon=True) for p in self.people]
        [t.start() for t in self.threads]
        return self

    def stop(self):
        self.stop_ev.set()
        [t.join(timeout=40) for t in self.threads]

    def verify(self, home=None):
        """Every acknowledged order, once, in `home`'s own database (the customers' cell, after everything is back)."""
        found = own_db_orders(home or self.cell, [x['key'] for x in self.acked])
        missing = [x for x in self.acked if x['key'] not in found]
        doubled = [k for k, n in found.items() if int(n) > 1]
        return {'acknowledged': len(self.acked), 'missing': len(missing), 'applied_twice': len(doubled),
                'missing_at_seconds': sorted(round(x['at'] - self.t0, 1) for x in missing)[:20] if hasattr(self, 't0') else None}


class Timeline:
    """Both cells' states every few seconds, and the moments they change."""

    def __init__(self, name):
        RESULTS.mkdir(exist_ok=True)
        self.t0, self.rows, self.stop_ev = now(), [], threading.Event()
        self.path = RESULTS / f'{name}-{datetime.datetime.now():%m%d%H%M}-timeline.csv'
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        with open(self.path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['t', 'cell_a', 'cell_b'])
            while not self.stop_ev.is_set():
                a, b = states()
                self.rows.append((round(now() - self.t0), a, b))
                w.writerow(self.rows[-1])
                f.flush()
                time.sleep(4)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.stop_ev.set()
        self.thread.join(timeout=30)

    def first(self, pred, after=0):
        """Seconds (on this timeline) of the first row at or after `after` for which pred(a, b) holds."""
        for t, a, b in self.rows:
            if t >= after and pred(a, b):
                return t
        return None

    def changes(self):
        out, prev = [], None
        for t, a, b in self.rows:
            if (a, b) != prev:
                out.append(f'+{t}s A={a} B={b}')
                prev = (a, b)
        return out


def record(name, result):
    RESULTS.mkdir(exist_ok=True)
    p = RESULTS / f'{name}-{datetime.datetime.now():%m%d%H%M}.json'
    p.write_text(json.dumps(result, indent=1, default=str), encoding='utf-8')
    say(f'{name}: {"PASS" if result.get("pass") else "FAIL"}  ->  {p.name}')
    return result
