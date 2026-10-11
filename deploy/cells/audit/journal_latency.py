"""X1: how much does cell B's write path slow down while cell A (the peer, where its journal goes) is slow or unreachable?
12 customers place orders back to back at the laptop's own address; the phone's web server is frozen for FREEZE seconds."""
import datetime
import json
import random
import statistics
import subprocess
import sys
import threading
import time
import uuid

sys.path.insert(0, r'C:\Users\sai34\Desktop\Projects\sprout\sprout-platform-cells\deploy\cells')
import chaos12 as c12  # noqa: E402

c12.PUBLIC = 'https://sprout-b-saiworks.nncs.in/api'    # straight to the laptop, not to whichever connector Cloudflare picks
import urllib.request, urllib.error
LOCAL = 'http://127.0.0.1:18080/api'   # the laptop's own web server: the load generator is on the same machine


def order(token, key):
    ip = f'198.18.{random.randint(0, 255)}.{random.randint(1, 254)}'   # a different client each time, as the capacity runs do
    body = json.dumps({'symbol': random.choice(c12.CHEAP), 'side': 'BUY', 'quantity': 1, 'orderType': 'MARKET', 'product': 'CNC'}).encode()
    req = urllib.request.Request(LOCAL + '/oms/v1/orders', data=body, method='POST', headers={
        'Content-Type': 'application/json', 'Authorization': f'Bearer {token}', 'X-Sprout-Cell': 'b',
        'Idempotency-Key': key, 'CF-Connecting-IP': ip})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0
WARM, FREEZE, AFTER, THREADS = 30, 90, 40, 12
run = datetime.datetime.now().strftime('%m%d%H%M')
print('creating customers')
people = [c12.customer('b', i, 'x1' + run) for i in range(THREADS)]
rows, lock, stop = [], threading.Lock(), threading.Event()
t0 = time.time()


def trade(p):
    while not stop.is_set():
        key = str(uuid.uuid4())
        start = time.time()
        s = order(p['token'], key)
        with lock:
            rows.append((start - t0, time.time() - start, s))


ts = [threading.Thread(target=trade, args=(p,), daemon=True) for p in people]
[t.start() for t in ts]
time.sleep(WARM)
f0 = time.time() - t0
subprocess.run(c12.SSH + ["pkill -STOP -f '^nginx: '"], capture_output=True)
print(f'phone web server frozen at +{f0:.0f}s')
time.sleep(FREEZE)
subprocess.run(c12.SSH + ["pkill -CONT -f '^nginx: '"], capture_output=True)
f1 = time.time() - t0
print(f'resumed at +{f1:.0f}s')
time.sleep(AFTER)
stop.set()
[t.join(timeout=40) for t in ts]


def phase(lo, hi, name):
    xs = [(l, s) for (st, l, s) in rows if lo <= st < hi]
    if not xs:
        print(name, 'none')
        return
    lat = sorted(l for l, _ in xs)
    ok = sum(1 for _, s in xs if s in (200, 201))
    from collections import Counter
    mix = dict(Counter(s for _, s in xs))
    print(f'{name:<22} status {mix}')
    print(f'{name:<22} orders/s {len(xs) / (hi - lo):5.1f}  ok {ok}/{len(xs)}  p50 {lat[len(lat) // 2] * 1000:6.0f} ms  '
          f'p95 {lat[int(len(lat) * .95)] * 1000:6.0f} ms  max {lat[-1] * 1000:6.0f} ms')


phase(5, f0, 'peer healthy')
phase(f0 + 5, f1, 'peer frozen (slow)')
phase(f1 + 10, f1 + AFTER, 'peer back')
