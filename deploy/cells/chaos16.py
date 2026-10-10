"""CHAOS-16: one service in a cell dies while the cell's front door stays up; the other cell takes its customers over.

Run on the laptop, both cells healthy and replicating:   python deploy/cells/chaos16.py --service trading
  --mode stop  (default) the host is stopped and stays down: the case failover is for
  --mode kill  the host is killed, and Docker's restart policy brings it back by itself (the usual real crash): the cell
               must neither fence nor be taken over, and the customers' errors must end within a minute or so
  (cell B, the laptop, loses one host: trading holds orders and market data; money, street or edge also work)

CHAOS-12 stops a whole cell, so its public address goes silent and the other cell takes over after 2 minutes. Here the
address keeps answering: the gateway and web server are up, and only the routes behind the dead host fail. A cell that
is slow or part-broken is not "lost" (a slow cell was once taken over while it was still serving, and two cells ran
one set of customers), so the rules are longer on purpose:

  - the broken cell fences itself (takes no more writes) after 5 minutes of its own services failing
  - the other cell takes it over after 10 minutes of it being unable to serve

  1. creates CUSTOMERS customers in cell B and has them place orders, each with its own idempotency key
  2. LAG_SECONDS before the fault, replication from cell B is paused (so its last orders exist only in the journal)
  3. the host is stopped. Every 5 s a probe, as a customer of cell B, asks one route behind each host and reads both
     cells' published state; every acknowledged order is written down as it happens
  4. the run goes on until orders succeed again, then a while longer
  5. every acknowledged order must exist exactly once in cell B's copy on the phone, and none be missing

Written to deploy/cells/results/chaos16-<time>.json (the result) and -timeline.csv (what was seen, every 5 s).
"""
import argparse
import csv
import datetime
import json
import random
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import chaos12 as c12  # noqa: E402  (its helpers: call, customer, sh, SSH, PUBLIC)

STATUS = {'a': 'https://sprout-a-saiworks.nncs.in/cells/status.json', 'b': 'https://sprout-b-saiworks.nncs.in/cells/status.json'}
# one route behind each host, so the timeline shows which parts of the cell failed
PROBES = {'market': ('GET', '/marketdata/v1/market'), 'orders': ('GET', '/oms/v1/orders'),
          'bank': ('GET', '/bank/v1/accounts/me'), 'funds': ('GET', '/oms/v1/funds')}


def cell_state(cell):
    try:
        # Cloudflare refuses Python's default User-Agent
        req = urllib.request.Request(STATUS[cell], headers={'User-Agent': 'sprout-chaos16', 'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read())
            return d.get('state', '?') + ('' if d.get('healthy', True) else '/sick')
    except Exception:
        return 'silent'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--service', choices=['trading', 'money', 'street', 'edge'], default='trading')
    ap.add_argument('--mode', choices=['stop', 'kill'], default='stop')
    ap.add_argument('--customers', type=int, default=8)
    ap.add_argument('--before', type=int, default=120)
    ap.add_argument('--lag', type=int, default=60)
    ap.add_argument('--after', type=int, default=None, help='seconds to watch after the fault (default 1500: the takeover is at ~11 min; 300 for --mode kill)')
    a = ap.parse_args()
    if a.after is None:
        a.after = 300 if a.mode == 'kill' else 1500
    if a.mode == 'kill':
        a.lag = 0   # nothing is taken over, so replication stays on and the laptop's own database is checked
    cell = 'b'
    container = f'sprout-laptop-{a.service}-1'
    run = datetime.datetime.now().strftime('%m%d%H%M')
    out = HERE / 'results'
    out.mkdir(exist_ok=True)

    print(f'creating {a.customers} customers in cell {cell}')
    people = [c12.customer(cell, i, run) for i in range(a.customers)]
    acked, attempts, lock = [], {'total': 0, 'failed': 0, 'by_status': {}}, threading.Lock()
    suffix = '' if a.mode == 'stop' else '-kill'
    ledger = open(out / f'chaos16-{run}{suffix}-acknowledged.jsonl', 'a', encoding='utf-8')
    stop = threading.Event()

    def refresh(p):
        s, res = c12.call('POST', '/identity/v1/sessions', {'email': p['email'], 'password': c12.PASSWORD}, cell=cell)
        if s == 200 and res:
            p['token'] = res['tokens']['accessToken']

    def trade(p):
        while not stop.is_set():
            key = str(uuid.uuid4())
            sent = time.time()
            body = {'symbol': random.choice(c12.CHEAP), 'side': 'BUY', 'quantity': 1, 'orderType': 'MARKET', 'product': 'CNC'}
            for _ in range(3):
                status, res = c12.call('POST', '/oms/v1/orders', body, token=p['token'], cell=cell, key=key, timeout=20)
                if status == 401:   # the access token lapsed (15 minutes): sign in again, as the app does
                    refresh(p)
                    continue
                if status != 0 and status < 500:
                    break
                time.sleep(2)
            with lock:
                attempts['total'] += 1
                attempts['by_status'][str(status)] = attempts['by_status'].get(str(status), 0) + 1
                if status in (200, 201) and res and res.get('id'):
                    acked.append({'key': key, 'id': res['id'], 'at': time.time(), 'sent': sent, 'email': p['email']})
                    ledger.write(json.dumps(acked[-1]) + '\n')
                    ledger.flush()
                else:
                    attempts['failed'] += 1
            time.sleep(random.uniform(2, 4))

    t0 = time.time()
    timeline = open(out / f'chaos16-{run}{suffix}-timeline.csv', 'w', newline='', encoding='utf-8')
    tl = csv.writer(timeline)
    tl.writerow(['t_seconds', 'phase'] + list(PROBES) + ['cell_a', 'cell_b', 'orders_acked_total'])
    state = {'fault_at': None}
    states_seen = {'a': set(), 'b': set()}

    def watch():
        while not stop.is_set():
            probe_token = people[0]['token']
            row = [round(time.time() - t0), 'before' if state['fault_at'] is None else f'+{round(time.time() - state["fault_at"])}s']
            for name, (method, path) in PROBES.items():
                row.append(c12.call(method, path, token=probe_token, cell=cell, timeout=10)[0])
            sa, sb = cell_state('a'), cell_state('b')
            states_seen['a'].add(sa)
            states_seen['b'].add(sb)
            row += [sa, sb]
            with lock:
                row.append(len(acked))
            tl.writerow(row)
            timeline.flush()
            time.sleep(5)

    threads = [threading.Thread(target=trade, args=(p,), daemon=True) for p in people]
    threads.append(threading.Thread(target=watch, daemon=True))
    for t in threads:
        t.start()

    laptop_env = dict(l.rstrip('\n').split('=', 1) for l in open(HERE / '../laptop/data/.env', encoding='utf-8')
                      if '=' in l and not l.startswith('#'))

    def copy_sql(sql):
        """SQL on stdin against the database that serves cell B afterwards: the phone's copy after a takeover, the laptop's
        own database when the host came back by itself."""
        if a.mode == 'kill':
            cmd = ['docker', 'exec', '-i', '-e', f'PGPASSWORD={laptop_env["SPROUT_DB_PASSWORD"]}', 'sprout-laptop-postgres-1',
                   'psql', '-U', 'sprout', '-d', 'sprout', '-At']
        else:
            cmd = c12.SSH + ['psql -d sprout_b -At']
        r = subprocess.run(cmd, input=sql + ';\n', capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr[-400:])
        return r.stdout

    print(f'trading for {a.before}s; replication paused for the last {a.lag}s of it')
    if a.mode == 'stop':
        time.sleep(a.before - a.lag)
        copy_sql('ALTER SUBSCRIPTION from_b DISABLE')
    else:
        time.sleep(a.before)
    paused_at = time.time()
    time.sleep(a.lag)
    killed_at = state['fault_at'] = time.time()
    print(f'{"stopping" if a.mode == "stop" else "killing"} the {a.service} host of cell {cell} ({container}); its web server and gateway stay up')
    if a.mode == 'stop':
        c12.sh(['docker', 'stop', container])
    else:
        # the JVM (pid 1) exits by itself, as in a crash. Neither `docker kill` (a manual stop: the restart policy would
        # leave the container down) nor `kill -9 1` from inside (a namespace's init ignores signals from within) works
        c12.sh(['docker', 'exec', container, 'kill', '-TERM', '1'])

    first_ok_after = None
    ok_since = None
    deadline = killed_at + a.after
    while time.time() < deadline:
        time.sleep(5)
        with lock:
            recent = [x for x in acked if x['sent'] > killed_at + 5]
        if recent and first_ok_after is None:
            first_ok_after = recent[0]['at'] - killed_at
            print(f'orders succeed again {first_ok_after:.0f}s after the fault')
        if first_ok_after is not None and ok_since is None:
            ok_since = time.time()
        if ok_since and time.time() - ok_since > 90:
            break   # recovered, and seen to stay recovered
    stop.set()
    for t in threads:
        t.join(timeout=30)

    keys = [x['key'] for x in acked]
    rows = copy_sql("SELECT idempotency_key || ' ' || count(*) FROM oms.orders WHERE idempotency_key IN ('"
                    + "','".join(keys) + "') GROUP BY idempotency_key")
    found = dict(line.split() for line in rows.split('\n') if line.strip())
    missing = [k for k in keys if k not in found]
    doubled = [k for k, n in found.items() if int(n) > 1]
    result = {
        'scenario': f'the {a.service} host of cell {cell} {"stopped and stayed down" if a.mode == "stop" else "was killed and restarted by itself"}; its front door stayed up',
        'run': run, 'mode': a.mode,
        'cell_states_seen': {k: sorted(v) for k, v in states_seen.items()},
        'customers': a.customers, 'orders_tried': attempts['total'], 'orders_acknowledged': len(acked),
        'orders_by_status': attempts['by_status'],
        'acknowledged_while_replication_paused': len([x for x in acked if paused_at <= x['at'] < killed_at]),
        'acknowledged_after_the_fault': len([x for x in acked if x['at'] >= killed_at]),
        'missing_after_takeover': len(missing), 'applied_twice': len(doubled),
        'seconds_until_orders_succeed_again': None if first_ok_after is None else round(first_ok_after),
        'missing_keys': missing[:20],
    }
    (out / f'chaos16-{run}{suffix}.json').write_text(json.dumps(result, indent=1), encoding='utf-8')
    print(json.dumps(result, indent=1))


if __name__ == '__main__':
    main()
