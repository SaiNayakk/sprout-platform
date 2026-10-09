"""CHAOS-10: a cell is lost mid-load; the other takes its customers over, and no acknowledged write is lost or doubled.

Run on the laptop, both cells healthy and replicating:   python deploy/cells/chaos10.py --kill a
  (--kill a: the phone's cell is lost and the laptop takes over; --kill b: the other way round)

  1. creates CUSTOMERS customers in the cell to be killed, each funded through the bank like anyone
  2. they place market orders through the public address, each with its own idempotency key; every order the cell
     acknowledges (201) is recorded with its key
  3. LAG_SECONDS before the kill, replication from the doomed cell is paused, so its last orders exist only in the
     journal kept by the other cell: the takeover can only find them by replaying it
  4. the cell is killed (its whole Sprout stopped), while orders keep being tried
  5. the other cell takes over (cellwatch: fence, promote, replay, route); orders succeed again
  6. every acknowledged order must exist exactly once in the promoted copy, with the same key, and none be missing

The result is written to deploy/cells/results/chaos10-<time>.json and printed.
"""
import argparse
import datetime
import json
import os
import random
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
PUBLIC = 'https://sprout-saiworks.nncs.in/api'
PHONE = os.environ.get('PHONE', 'u0_a1@192.168.0.6')
SSH = ['ssh', '-i', os.path.expanduser(os.environ.get('PHONE_KEY', '~/.ssh/backseat_phone')), '-p', '8022',
       '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', PHONE]
PASSWORD = 'chaos-ten-mango-42'
CHEAP = ['SUNROOT', 'THREADS', 'IRONLEAF', 'NIGHTOWL']


def call(method, path, body=None, token=None, cell=None, key=None, timeout=15):
    headers = {'Content-Type': 'application/json', 'User-Agent': 'sprout-chaos10'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if cell:
        headers['X-Sprout-Cell'] = cell
    if key:
        headers['Idempotency-Key'] = key
    req = urllib.request.Request(PUBLIC + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b'null')
        except ValueError:
            return e.code, None
    except Exception:
        return 0, None


def customer(cell, i, run):
    email = f'chaos10-{run}-{i}@example.invalid'
    call('POST', '/identity/v1/users', {'email': email, 'password': PASSWORD, 'displayName': f'Chaos {i}'}, cell=cell)
    _, s = call('POST', '/identity/v1/sessions', {'email': email, 'password': PASSWORD}, cell=cell)
    t = s['tokens']['accessToken']
    call('POST', '/bank/v1/accounts', {'holderName': f'Chaos {i}', 'upiPin': '2580'}, token=t, cell=cell)
    _, acct = call('GET', '/bank/v1/accounts/me', token=t, cell=cell)
    pan = f'CHAP{random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ")}{random.randint(0, 9999):04d}Z'
    call('POST', '/accounts/v1/accounts', {'legalName': f'Chaos {i}', 'dateOfBirth': '1995-06-15', 'pan': pan,
                                           'bankVpa': acct['vpa']}, token=t, cell=cell)
    call('POST', '/payments/v1/deposits', {'amount': '50000'}, token=t, cell=cell, key=str(uuid.uuid4()))
    _, reqs = call('GET', '/bank/v1/requests?status=PENDING', token=t, cell=cell)
    for r in (reqs or {}).get('requests', []):
        call('POST', f'/bank/v1/requests/{r["id"]}/approve', {'upiPin': '2580'}, token=t, cell=cell)
    return {'email': email, 'token': t}


def sh(cmd, check=True):
    r = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f'{cmd} failed: {r.stderr[-400:]}')
    return r.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--kill', choices=['a', 'b'], required=True)
    ap.add_argument('--customers', type=int, default=8)
    ap.add_argument('--before', type=int, default=120, help='seconds of orders before the kill')
    ap.add_argument('--lag', type=int, default=60, help='replication paused this long before the kill')
    ap.add_argument('--after', type=int, default=420, help='seconds of orders after the kill')
    a = ap.parse_args()
    cell = a.kill
    run = datetime.datetime.now().strftime('%m%d%H%M')
    laptop_env = dict(l.rstrip('\n').split('=', 1) for l in open(HERE / '../laptop/data/.env', encoding='utf-8') if '=' in l and not l.startswith('#'))

    def copy_sql(sql):
        """SQL against the other cell's copy of the doomed cell's database."""
        if cell == 'a':
            return sh(['docker', 'exec', '-i', '-e', f'PGPASSWORD={laptop_env["SPROUT_DB_PASSWORD"]}', 'sprout-laptop-postgres-1',
                       'psql', '-U', 'sprout', '-d', 'sprout_a', '-Atc', sql])
        return sh(SSH + [f'psql -d sprout_b -Atc "{sql}"'])

    print(f'creating {a.customers} customers in cell {cell}')
    people = [customer(cell, i, run) for i in range(a.customers)]
    acked, attempts, lock = [], {'total': 0, 'failed': 0}, threading.Lock()
    stop = threading.Event()

    def trade(p):
        while not stop.is_set():
            key = str(uuid.uuid4())
            sent = time.time()
            body = {'symbol': random.choice(CHEAP), 'side': 'BUY', 'quantity': 1, 'orderType': 'MARKET', 'product': 'CNC'}
            for _ in range(3):   # a customer retries an unanswered order with the same key, as the app does
                status, res = call('POST', '/oms/v1/orders', body, token=p['token'], cell=cell, key=key, timeout=20)
                if status != 0 and status < 500:
                    break
                time.sleep(2)
            with lock:
                attempts['total'] += 1
                if status in (200, 201) and res and res.get('id'):
                    acked.append({'key': key, 'id': res['id'], 'at': time.time(), 'sent': sent, 'email': p['email']})
                else:
                    attempts['failed'] += 1
            time.sleep(random.uniform(2, 4))

    threads = [threading.Thread(target=trade, args=(p,), daemon=True) for p in people]
    for t in threads:
        t.start()
    print(f'trading for {a.before}s; replication paused for the last {a.lag}s of it')
    time.sleep(a.before - a.lag)
    copy_sql(f'ALTER SUBSCRIPTION from_{cell} DISABLE')
    paused_at = time.time()
    time.sleep(a.lag)
    killed_at = time.time()
    print(f'killing cell {cell}')
    if cell == 'a':
        sh(SSH + ['sh ~/sprout/ctl.sh stop sprout'])
    else:
        sh('docker stop sprout-laptop-edge-1 sprout-laptop-trading-1 sprout-laptop-money-1 sprout-laptop-street-1 '
           'sprout-laptop-web-1 sprout-laptop-front-1 sprout-laptop-cellwatch-1 sprout-laptop-cloudflared-1')
    first_ok_after = None
    deadline = killed_at + a.after
    while time.time() < deadline:
        time.sleep(5)
        with lock:
            recent = [x for x in acked if x['sent'] > killed_at + 5]   # sent after the cell was gone
        if recent and first_ok_after is None:
            first_ok_after = recent[0]['at'] - killed_at
            print(f'orders succeed again {first_ok_after:.0f}s after the kill')
    stop.set()
    for t in threads:
        t.join(timeout=30)

    # every acknowledged order, once, in the promoted copy
    keys = [x['key'] for x in acked]
    rows = copy_sql("SELECT idempotency_key || ' ' || count(*) FROM oms.orders WHERE idempotency_key IN ('"
                    + "','".join(keys) + "') GROUP BY idempotency_key")
    found = dict(line.split() for line in rows.split('\n') if line.strip())
    missing = [k for k in keys if k not in found]
    doubled = [k for k, n in found.items() if int(n) > 1]
    only_in_journal = [x for x in acked if paused_at <= x['at'] < killed_at]
    result = {
        'scenario': f'cell {cell} lost mid-load; replication {a.lag}s behind when it died', 'run': run,
        'customers': a.customers, 'orders_tried': attempts['total'], 'orders_acknowledged': len(acked),
        'acknowledged_while_replication_paused': len(only_in_journal),
        'missing_after_takeover': len(missing), 'applied_twice': len(doubled),
        'seconds_until_orders_succeed_again': None if first_ok_after is None else round(first_ok_after),
        'missing_keys': missing[:20],
    }
    out = HERE / 'results'
    out.mkdir(exist_ok=True)
    (out / f'chaos10-{run}-{cell}.json').write_text(json.dumps(result, indent=1), encoding='utf-8')
    print(json.dumps(result, indent=1))


if __name__ == '__main__':
    main()
