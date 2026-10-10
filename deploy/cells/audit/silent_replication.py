"""X7: orders into cell A for N seconds while its replication into the laptop is silently off; then compare the databases."""
import datetime
import json
import random
import subprocess
import sys
import threading
import time
import uuid

sys.path.insert(0, r'C:\Users\sai34\Desktop\Projects\sprout\sprout-platform-cells\deploy\cells')
import chaos12 as c12  # noqa: E402

SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 180
run = datetime.datetime.now().strftime('%m%d%H%M')
people = [c12.customer('a', i, 'x7' + run) for i in range(4)]
acked, lock, stop = [], threading.Lock(), threading.Event()


def trade(p):
    while not stop.is_set():
        key = str(uuid.uuid4())
        s, r = c12.call('POST', '/oms/v1/orders', {'symbol': random.choice(c12.CHEAP), 'side': 'BUY', 'quantity': 1,
                                                    'orderType': 'MARKET', 'product': 'CNC'}, token=p['token'], cell='a', key=key)
        if s in (200, 201):
            with lock:
                acked.append(key)
        time.sleep(2)


ts = [threading.Thread(target=trade, args=(p,), daemon=True) for p in people]
[t.start() for t in ts]
time.sleep(SECONDS)
stop.set()
[t.join(timeout=30) for t in ts]
keys = acked
q = "('" + "','".join(keys) + "')"
env = dict(l.rstrip('\n').split('=', 1) for l in open(r'C:\Users\sai34\Desktop\Projects\sprout\sprout-platform-cells\deploy\laptop\data\.env', encoding='utf-8') if '=' in l and not l.startswith('#'))
r = subprocess.run(['docker', 'exec', '-i', '-e', f'PGPASSWORD={env["SPROUT_DB_PASSWORD"]}', 'sprout-laptop-postgres-1', 'psql', '-U', 'sprout', '-d', 'sprout_a', '-At'],
                   input=f"SELECT count(*) FROM oms.orders WHERE idempotency_key IN {q};\n", capture_output=True, text=True)
print(json.dumps({'orders_acknowledged_in_cell_A': len(keys), 'of_them_in_the_laptops_copy': int(r.stdout.strip() or -1)}))
