"""CHAOS-17: a cell's address goes silent for nearly three minutes and comes back, after the other cell has begun taking it over.

Run on the laptop, both cells healthy and replicating:   python deploy/cells/chaos17.py

This is what happened for real on 2026-10-09 (see the incident): the phone's tunnel dropped, the phone fenced itself, the
laptop took cell A over, and the phone, back after a minute, unfenced itself before the takeover had finished and went on
serving beside it. Here the phone's web server is frozen (SIGSTOP) for FREEZE seconds, so its address stops answering while
the process stays up, then resumed. The other cell must take over, and the returning cell must stay out of service:

  1. creates CUSTOMERS customers in cell A and has them place orders, each with its own idempotency key
  2. the phone's nginx is frozen for FREEZE s (170 by default: longer than the 2 minutes the laptop waits, shorter than the
     phone's starter would tolerate), then resumed
  3. every 5 s both cells' published state is read; the run goes on until the laptop is HOLDING cell A, the phone is
     TAKEN_OVER, and orders have worked again for a minute
  4. checks: the phone ends TAKEN_OVER and fenced; no order the customers were acknowledged for is missing from the
     laptop's copy or applied twice; and the phone's own database took **no** order from them after the laptop began holding

Written to deploy/cells/results/chaos17-<time>.json and -timeline.csv.
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
import chaos12 as c12  # noqa: E402

STATUS = {'a': 'https://sprout-a-saiworks.nncs.in/cells/status.json', 'b': 'https://sprout-b-saiworks.nncs.in/cells/status.json'}


def cell_state(cell):
    try:
        req = urllib.request.Request(STATUS[cell], headers={'User-Agent': 'sprout-chaos17', 'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read())
            return d.get('state', '?') + ('' if d.get('healthy', True) else '/sick')
    except Exception:
        return 'silent'


def verify(run, out, laptop_sql, phone):
    """The checks of a finished run, from what it wrote down: the acknowledged orders and the timeline."""
    acked = [json.loads(l) for l in open(out / f'chaos17-{run}-acknowledged.jsonl', encoding='utf-8') if l.strip()]
    rows = list(csv.DictReader(open(out / f'chaos17-{run}-timeline.csv', encoding='utf-8')))
    freeze_t = next(int(r['t_seconds']) - int(r['phase'][1:-1]) for r in rows if r['phase'].startswith('+'))
    after = lambda pred, who: next((int(r['t_seconds']) - freeze_t for r in rows if pred(r[who])), None)
    fenced = after(lambda s: s.startswith('FENCED'), 'cell_a')
    holding = after(lambda s: s.startswith('HOLDING'), 'cell_b')
    taken = after(lambda s: s.startswith('TAKEN_OVER'), 'cell_a')
    went_normal = any(r['cell_a'].startswith('NORMAL') for r in rows if fenced is not None and int(r['t_seconds']) - freeze_t > fenced)
    keys = [x['key'] for x in acked]
    quoted = "('" + "','".join(keys) + "')"
    in_copy = dict(l.split() for l in laptop_sql(
        f"SELECT idempotency_key || ' ' || count(*) FROM oms.orders WHERE idempotency_key IN {quoted} GROUP BY idempotency_key").split('\n') if l.strip())
    missing = [k for k in keys if k not in in_copy]
    doubled = [k for k, n in in_copy.items() if int(n) > 1]
    # when the laptop began holding: its cellwatch's own line
    hold_line = [l for l in open(HERE / '../laptop/data/cells/cellwatch.log', encoding='utf-8') if 'holding cell a' in l][-1]
    iso = hold_line.split(' ')[0]
    after_hold = int(phone('psql -d sprout -At', stdin=f"SELECT count(*) FROM oms.orders WHERE idempotency_key IN {quoted} AND created_at > '{iso}';\n") or -1)
    ours_total = int(phone('psql -d sprout -At', stdin=f"SELECT count(*) FROM oms.orders WHERE idempotency_key IN {quoted};\n") or -1)
    result = {
        'run': run, 'orders_acknowledged': len(acked),
        'phone_fenced_after_s': fenced, 'laptop_holding_after_s': holding, 'phone_taken_over_after_s': taken,
        'phone_went_back_to_normal_after_fencing': went_normal,
        'phone_state_at_end': rows[-1]['cell_a'], 'laptop_state_at_end': rows[-1]['cell_b'],
        'laptop_began_holding_at': iso,
        'of_them_in_the_phones_database': ours_total,
        'phone_database_orders_after_the_laptop_held': after_hold,
        'missing_from_laptop_copy': len(missing), 'applied_twice': len(doubled), 'missing_keys': missing[:20],
    }
    (out / f'chaos17-{run}.json').write_text(json.dumps(result, indent=1), encoding='utf-8')
    print(json.dumps(result, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--customers', type=int, default=8)
    ap.add_argument('--before', type=int, default=90)
    ap.add_argument('--freeze', type=int, default=170)
    ap.add_argument('--max', type=int, default=1200, help='give up this many seconds after the freeze')
    ap.add_argument('--verify', metavar='RUN', help='only check a finished run (its files in results/), e.g. 10102130')
    a = ap.parse_args()
    cell = 'a'
    run = datetime.datetime.now().strftime('%m%d%H%M')
    out = HERE / 'results'
    out.mkdir(exist_ok=True)
    laptop_env = dict(l.rstrip('\n').split('=', 1) for l in open(HERE / '../laptop/data/.env', encoding='utf-8')
                      if '=' in l and not l.startswith('#'))

    def laptop_sql(sql):
        cmd = ['docker', 'exec', '-i', '-e', f'PGPASSWORD={laptop_env["SPROUT_DB_PASSWORD"]}', 'sprout-laptop-postgres-1',
               'psql', '-U', 'sprout', '-d', 'sprout_a', '-At']
        r = subprocess.run(cmd, input=sql + ';\n', capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr[-400:])
        return r.stdout

    def phone(cmd, stdin=None):
        r = subprocess.run(c12.SSH + [cmd], input=stdin, capture_output=True, text=True)
        return r.stdout.strip()

    if a.verify:
        return verify(a.verify, out, laptop_sql, phone)
    print(f'creating {a.customers} customers in cell {cell}')
    people = [c12.customer(cell, i, run) for i in range(a.customers)]
    acked, attempts, lock = [], {'total': 0, 'by_status': {}}, threading.Lock()
    ledger = open(out / f'chaos17-{run}-acknowledged.jsonl', 'a', encoding='utf-8')
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
                if status == 401:
                    refresh(p)
                    continue
                if status != 0 and status < 500:
                    break
                time.sleep(2)
            with lock:
                attempts['total'] += 1
                attempts['by_status'][str(status)] = attempts['by_status'].get(str(status), 0) + 1
                if status in (200, 201) and res and res.get('id'):
                    acked.append({'key': key, 'id': res['id'], 'at': time.time(), 'sent': sent})
                    ledger.write(json.dumps(acked[-1]) + '\n')
                    ledger.flush()
            time.sleep(random.uniform(2, 4))

    t0 = time.time()
    timeline = open(out / f'chaos17-{run}-timeline.csv', 'w', newline='', encoding='utf-8')
    tl = csv.writer(timeline)
    tl.writerow(['t_seconds', 'phase', 'market', 'orders', 'bank', 'funds', 'cell_a', 'cell_b', 'orders_acked_total'])
    marks = {'freeze_at': None, 'resume_at': None}
    first_seen = {}

    def watch():
        while not stop.is_set():
            ph = 'before' if marks['freeze_at'] is None else f'+{round(time.time() - marks["freeze_at"])}s'
            row = [round(time.time() - t0), ph]
            for path in ('/marketdata/v1/market', '/oms/v1/orders', '/bank/v1/accounts/me', '/oms/v1/funds'):
                row.append(c12.call('GET', path, token=people[0]['token'], cell=cell, timeout=10)[0])
            sa, sb = cell_state('a'), cell_state('b')
            for who, st in (('a', sa), ('b', sb)):
                first_seen.setdefault((who, st), time.time())
            row += [sa, sb]
            with lock:
                row.append(len(acked))
            tl.writerow(row)
            timeline.flush()
            time.sleep(5)

    threads = [threading.Thread(target=trade, args=(p,), daemon=True) for p in people] + [threading.Thread(target=watch, daemon=True)]
    for t in threads:
        t.start()
    print(f'trading for {a.before}s')
    time.sleep(a.before)

    marks['freeze_at'] = time.time()
    print(f'freezing the phone\'s web server for {a.freeze}s: its address stops answering, the process stays up')
    phone("pkill -STOP -f '^nginx: '")
    try:
        time.sleep(a.freeze)
    finally:
        phone("pkill -CONT -f '^nginx: '")
        marks['resume_at'] = time.time()
    print('resumed; waiting for the laptop to hold cell A and the phone to be TAKEN_OVER')

    deadline = marks['resume_at'] + a.max
    settled_at = None
    while time.time() < deadline:
        time.sleep(5)
        if cell_state('a').startswith('TAKEN_OVER') and cell_state('b').startswith('HOLDING'):
            settled_at = settled_at or time.time()
            if time.time() - settled_at > 120:
                break
    stop.set()
    for t in threads:
        t.join(timeout=40)

    final_a, final_b = cell_state('a'), cell_state('b')
    holding_at = first_seen.get(('b', 'HOLDING'))
    fenced_at = first_seen.get(('a', 'FENCED')) or first_seen.get(('a', 'FENCED/sick'))
    back_normal = [t for (who, st), t in first_seen.items() if who == 'a' and st == 'NORMAL' and fenced_at and t > fenced_at]
    keys = [x['key'] for x in acked]
    quoted = "('" + "','".join(keys) + "')"
    in_copy = dict(l.split() for l in laptop_sql(
        f"SELECT idempotency_key || ' ' || count(*) FROM oms.orders WHERE idempotency_key IN {quoted} GROUP BY idempotency_key").split('\n') if l.strip())
    missing = [k for k in keys if k not in in_copy]
    doubled = [k for k, n in in_copy.items() if int(n) > 1]
    after_hold = None
    if holding_at:
        iso = datetime.datetime.fromtimestamp(holding_at, datetime.timezone.utc).isoformat()
        after_hold = int(phone('psql -d sprout -At', stdin=f"SELECT count(*) FROM oms.orders WHERE idempotency_key IN {quoted} AND created_at > '{iso}';\n") or -1)
    fence_file = phone('ls ~/sprout/journal/fenced 2>/dev/null && echo present || echo absent').split('\n')[-1]
    result = {
        'scenario': f'the phone\'s address was silent for {a.freeze}s, then came back', 'run': run,
        'customers': a.customers, 'orders_tried': attempts['total'], 'orders_acknowledged': len(acked),
        'orders_by_status': attempts['by_status'],
        'phone_fenced_after_s': None if not fenced_at else round(fenced_at - marks['freeze_at']),
        'laptop_holding_after_s': None if not holding_at else round(holding_at - marks['freeze_at']),
        'phone_state_at_end': final_a, 'laptop_state_at_end': final_b, 'phone_fence_file': fence_file,
        'phone_went_back_to_normal_after_fencing': bool(back_normal),
        'phone_database_orders_after_the_laptop_held': after_hold,
        'missing_from_laptop_copy': len(missing), 'applied_twice': len(doubled), 'missing_keys': missing[:20],
    }
    (out / f'chaos17-{run}.json').write_text(json.dumps(result, indent=1), encoding='utf-8')
    print(json.dumps(result, indent=1))


if __name__ == '__main__':
    main()
