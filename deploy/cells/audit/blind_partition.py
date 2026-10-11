"""X2: the cells cannot see each other (cellwatch's view only; nothing on the network is touched) while customers can
reach both. --mode oneway: only the laptop is blind. --mode mutual: both are.

Customers of cell A order through the public address throughout. Reports each cell's state over time, and afterwards where
every acknowledged order is: the laptop's copy of A, the phone's own database, or both."""
import argparse
import csv
import datetime
import json
import random
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(r'C:\Users\sai34\Desktop\Projects\sprout\sprout-platform-cells')
sys.path.insert(0, str(ROOT / 'deploy' / 'cells'))
import chaos12 as c12  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--mode', choices=['oneway', 'mutual'], required=True)
ap.add_argument('--start', type=int, default=60)
ap.add_argument('--blind', type=int, default=330)
ap.add_argument('--after', type=int, default=150)
a = ap.parse_args()
run = datetime.datetime.now().strftime('%m%d%H%M')
env = dict(l.rstrip('\n').split('=', 1) for l in open(ROOT / 'deploy/laptop/data/.env', encoding='utf-8') if '=' in l and not l.startswith('#'))
LAPTOP_FLAG = ROOT / 'deploy/laptop/data/cells/partition'
out = Path(r'C:\Users\sai34\AppData\Local\Temp\claude\C--Users-sai34-Desktop-Projects-invoicesnap\7fce7444-5c6d-4272-85ae-59c203d76835\scratchpad')


def state(cell):
    import urllib.request
    try:
        req = urllib.request.Request(f'https://sprout-{cell}-saiworks.nncs.in/cells/status.json', headers={'User-Agent': 'sprout-x2', 'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read())
            return d['state'] + ('' if d.get('healthy', True) else '/sick')
    except Exception:
        return 'silent'


def psql_laptop(db, sql):
    r = subprocess.run(['docker', 'exec', '-i', '-e', f'PGPASSWORD={env["SPROUT_DB_PASSWORD"]}', 'sprout-laptop-postgres-1', 'psql', '-U', 'sprout', '-d', db, '-At'],
                       input=sql + ';\n', capture_output=True, text=True)
    return r.stdout


def psql_phone(db, sql):
    return subprocess.run(c12.SSH + [f'psql -d {db} -At'], input=sql + ';\n', capture_output=True, text=True).stdout


print('creating customers in cell A')
people = [c12.customer('a', i, 'x2' + run) for i in range(6)]
acked, lock, stop = [], threading.Lock(), threading.Event()
attempts = {'n': 0, 'fail': 0}


def refresh(p):
    s, r = c12.call('POST', '/identity/v1/sessions', {'email': p['email'], 'password': c12.PASSWORD}, cell='a')
    if s == 200 and r:
        p['token'] = r['tokens']['accessToken']


def trade(p):
    while not stop.is_set():
        key = str(uuid.uuid4())
        sent = time.time()
        body = {'symbol': random.choice(c12.CHEAP), 'side': 'BUY', 'quantity': 1, 'orderType': 'MARKET', 'product': 'CNC'}
        for _ in range(3):
            s, r = c12.call('POST', '/oms/v1/orders', body, token=p['token'], cell='a', key=key, timeout=20)
            if s == 401:
                refresh(p)
                continue
            if s != 0 and s < 500:
                break
            time.sleep(2)
        with lock:
            attempts['n'] += 1
            if s in (200, 201) and r and r.get('id'):
                acked.append({'key': key, 'sent': sent, 'at': time.time()})
            else:
                attempts['fail'] += 1
        time.sleep(random.uniform(2, 4))


t0 = time.time()
tl = csv.writer(open(out / f'x2-{a.mode}-{run}.csv', 'w', newline=''))
tl.writerow(['t', 'cell_a', 'cell_b', 'acked'])
marks = {}


def watch():
    while not stop.is_set():
        sa, sb = state('a'), state('b')
        tl.writerow([round(time.time() - t0), sa, sb, len(acked)])
        marks.setdefault('last', (sa, sb))
        time.sleep(5)


ts = [threading.Thread(target=trade, args=(p,), daemon=True) for p in people] + [threading.Thread(target=watch, daemon=True)]
[t.start() for t in ts]
time.sleep(a.start)
marks['blind_at'] = time.time()
LAPTOP_FLAG.write_text('x')
if a.mode == 'mutual':
    subprocess.run(c12.SSH + ['touch ~/sprout/cells/partition'])
print(f'{a.mode}: partition injected at +{marks["blind_at"] - t0:.0f}s')
time.sleep(a.blind)
LAPTOP_FLAG.unlink(missing_ok=True)
subprocess.run(c12.SSH + ['rm -f ~/sprout/cells/partition'])
marks['healed_at'] = time.time()
print(f'healed at +{marks["healed_at"] - t0:.0f}s; watching {a.after}s more')
time.sleep(a.after)
final = (state('a'), state('b'))
stop.set()
[t.join(timeout=40) for t in ts]

keys = [x['key'] for x in acked]
q = "('" + "','".join(keys) + "')"
laptop = {l.strip() for l in psql_laptop('sprout_a', f"SELECT idempotency_key FROM oms.orders WHERE idempotency_key IN {q}").split('\n') if l.strip()}
phone = {l.strip() for l in psql_phone('sprout', f"SELECT idempotency_key FROM oms.orders WHERE idempotency_key IN {q}").split('\n') if l.strip()}
both, only_l, only_p = laptop & phone, laptop - phone, phone - laptop
neither = [k for k in keys if k not in laptop and k not in phone]
log = [l for l in (ROOT / 'deploy/laptop/data/cells/cellwatch.log').read_text(encoding='utf-8').splitlines() if ('holding cell' in l or 'is lost' in l)][-2:]
hold_a = next((l.split(' ')[0] for l in reversed(log) if 'holding cell a' in l), None)
only_p_times = sorted(round(x['at'] - marks['blind_at']) for x in acked if x['key'] in only_p)
only_l_times = sorted(round(x['at'] - marks['blind_at']) for x in acked if x['key'] in only_l)
print(json.dumps({
    'mode': a.mode, 'orders_acknowledged': len(keys), 'orders_failed': attempts['fail'],
    'final_state_cell_a': final[0], 'final_state_cell_b': final[1],
    'laptop_began_holding_a_at': hold_a,
    'acked_orders_in_both_databases': len(both),
    'only_in_the_laptops_copy': len(only_l), 'only_in_the_phones_database': len(only_p), 'in_neither': len(neither),
    'seconds_after_the_partition_of_orders_only_in_the_phone': only_p_times[:40],
    'seconds_after_the_partition_of_orders_only_in_the_laptop': only_l_times[:40],
}, indent=1))
