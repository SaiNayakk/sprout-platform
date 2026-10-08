"""Runs one capacity test against the phone and keeps everything it measured.

    python capacity/run.py users 50,100,200,400,800          (concurrent customers doing everything customers do)
    python capacity/run.py browse 10,20,40,80,120,160,200    (screens a second)
    python capacity/run.py signin 1,2,4,6,8,10,12,15         (sign-ins a second)
    python capacity/run.py demo 1,2,4                        (demo accounts started a second)
    python capacity/run.py streams 100,200,400,800           (clients holding live price streams: PERF-03's client)
    python capacity/run.py orders 2,5,10,20                  (market orders a second: PERF-04's client)

What it does:
  1. reaches the phone's web server (which forwards /api to the gateway) over Wi-Fi: it turns on a test-only listener
     (port 8181) for the run and off again after, so neither Cloudflare's limits nor an SSH tunnel's encryption (on
     the phone's CPU) is what gets measured. --via tunnel uses an SSH tunnel instead.
  2. starts capacity/sample.py on the phone, recording CPU, memory and battery temperature every 2 s
  3. runs the steps one after another: capacity/k6/cap.js in Docker, or the end-to-end module's Java load clients
  4. writes capacity/results/<time>-<test>/: what the client measured, the samples, and result.json (per step: the
     load asked for, latency percentiles, errors by status, and the phone's peak CPU, lowest free memory, temperature)

Settings come from the environment: PHONE (default u0_a1@192.168.0.6), PHONE_KEY (~/.ssh/backseat_phone).
"""
import argparse
import csv
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PHONE = os.environ.get('PHONE', 'u0_a1@192.168.0.6')
PHONE_HOST = PHONE.split('@')[-1]
KEY = os.path.expanduser(os.environ.get('PHONE_KEY', '~/.ssh/backseat_phone'))
SSH = ['ssh', '-i', KEY, '-p', '8022', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'ServerAliveInterval=10']
TUNNEL_PORT = 18180
LAN_PORT = 8181
CODES = ('0', '200', '201', '400', '401', '404', '409', '422', '429', '500', '502', '503', '504')
ACTIONS = ('home', 'quotes', 'orders', 'pots', 'plans', 'buy', 'upi', 'signin')
PROCESSES = ('edge', 'trading', 'money', 'street', 'postgres', 'nats', 'nginx', 'sshd', 'cloudflared')


def wait_port(host, port, seconds=30):
    end = time.time() + seconds
    while time.time() < end:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def lan(on):
    """Turns the web server's test-only Wi-Fi listener on or off: a flag file, then nginx reloads its configuration
    (it keeps serving; nothing restarts)."""
    flag = '~/.sprout-capacity-lan'
    subprocess.run(SSH + [PHONE, (f'touch {flag}' if on else f'rm -f {flag}') + '; sh ~/sprout/web/run.sh reload'],
                   capture_output=True)


def k6_steps(a, steps, out, base_url):
    """One k6 run with a scenario per step; returns per-step results and when each step ran."""
    started = time.time()
    k6 = subprocess.run(['docker', 'run', '--rm', '--add-host=host.docker.internal:host-gateway',
                         '-v', f'{HERE / "k6"}:/scripts:ro', '-v', f'{out / "out"}:/out',
                         '-e', f'TEST={a.test}', '-e', f'STEPS={a.steps}', '-e', f'STEP_SECONDS={a.step_seconds}',
                         '-e', f'USERS={a.users}', '-e', f'BASE_URL={base_url}', '-e', 'OUT=/out/summary.json',
                         'grafana/k6:2.3.0', 'run', '--quiet', '/scripts/cap.js'],
                        env=dict(os.environ, MSYS_NO_PATHCONV='1'))
    summary = json.loads((out / 'out' / 'summary.json').read_text(encoding='utf-8'))
    m = summary['metrics']
    # set-up (customers created, signed in) runs before the first step
    first = started + summary['state']['testRunDurationMs'] / 1000 - len(steps) * a.step_seconds
    per_step, windows = [], []
    for i, n in enumerate(steps):
        name = f'step_{i:02d}_{n}'

        def val(metric, key, extra=''):
            return m.get(f'{metric}{{scenario:{name}{extra}}}', {}).get('values', {}).get(key)

        codes = {c: v for c in CODES if (v := val('responses', 'count', f',code:{c}'))}
        per_step.append({
            'step': i, 'asked': n, 'requests_per_s': round(sum(codes.values()) / a.step_seconds, 1),
            'p50_ms': val('http_req_duration', 'med'), 'p95_ms': val('http_req_duration', 'p(95)'),
            'p99_ms': val('http_req_duration', 'p(99)'), 'max_ms': val('http_req_duration', 'max'),
            'failed_rate': val('http_req_failed', 'rate'), 'checks_ok_rate': val('checks', 'rate'),
            'dropped': val('dropped_iterations', 'count') or 0, 'codes': codes,
            'by_action_p95_ms': {x: round(v) for x in ACTIONS if (v := val('http_req_duration', 'p(95)', f',name:{x}')) is not None},
        })
        windows.append((first + i * a.step_seconds, first + (i + 1) * a.step_seconds))
    return per_step, windows, k6.returncode


def java_steps(a, steps, out, base_url):
    """The stream and order tests are the end-to-end module's own load clients (k6 can't hold streams open, and the
    order test checks every customer's holdings afterwards). One run per step."""
    e2e = HERE.parent / 'e2e'
    mvn = 'mvn.cmd' if os.name == 'nt' else 'mvn'
    per_step, windows = [], []
    for i, n in enumerate(steps):
        summary = out / 'out' / f'step-{i:02d}.json'
        if a.test == 'streams':
            props, env = ['-Dgroups=perf', f'-Dperf.clients={n}', f'-Dperf.out={summary}'], {}
        else:
            props, env = ['-Dgroups=perf-orders', f'-Dperf.rate={n}', f'-Dperf.customers={max(10, n * 4)}'], {'PERF04_OUT': str(summary)}
        t0 = time.time()
        run = subprocess.run([mvn, '-q', '-B', '-f', str(e2e / 'pom.xml'), 'test', '-De2e.excludedGroups=',
                              f'-Dperf.seconds={a.step_seconds}', f'-Dsprout.baseUrl={base_url}'] + props,
                             env=dict(os.environ, **env), capture_output=True, text=True)
        windows.append((t0, time.time()))
        r = json.loads(summary.read_text(encoding='utf-8')) if summary.exists() else {'error': run.stdout[-2000:]}
        r.update({'step': i, 'asked': n, 'passed_gate': run.returncode == 0})
        per_step.append(r)
        print(json.dumps(r))
    return per_step, windows, 0


def phone_during(rows, lo, hi):
    window = [r for r in rows if lo <= int(r['t']) < hi]
    if not window:
        return {}
    total = [sum(float(r.get(f'{p}_cpu') or 0) for p in PROCESSES) for r in window]
    temps = [float(r['battery_c']) for r in window if r.get('battery_c')]
    peak = {f'{p}_cpu_peak_pct': round(max(float(r.get(f'{p}_cpu') or 0) for r in window)) for p in PROCESSES}
    return {'phone_cpu_peak_pct': round(max(total)), 'phone_cpu_avg_pct': round(sum(total) / len(total)), **peak,
            'available_mb_min': min(int(r['available_mb']) for r in window), 'battery_c_max': max(temps) if temps else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('test', choices=['users', 'browse', 'signin', 'demo', 'streams', 'orders'])
    ap.add_argument('steps')
    ap.add_argument('--step-seconds', type=int, default=60)
    ap.add_argument('--users', type=int, default=30, help='customers created for the test (k6 tests)')
    ap.add_argument('--via', choices=['lan', 'tunnel'], default='lan')
    ap.add_argument('--label', default='', help='a note kept with the result, e.g. what was changed')
    a = ap.parse_args()
    steps = [int(s) for s in a.steps.split(',')]

    out = HERE / 'results' / f'{datetime.now():%Y%m%d-%H%M}-{a.test}'
    (out / 'out').mkdir(parents=True, exist_ok=True)
    tunnel = sampler = None
    try:
        if a.via == 'lan':
            lan(True)
            if not wait_port(PHONE_HOST, LAN_PORT):
                sys.exit('the phone\'s test listener didn\'t come up')
            k6_url, java_url = f'http://{PHONE_HOST}:{LAN_PORT}', f'http://{PHONE_HOST}:{LAN_PORT}'
        else:
            tunnel = subprocess.Popen(SSH + ['-N', '-L', f'0.0.0.0:{TUNNEL_PORT}:127.0.0.1:8180', PHONE])
            if not wait_port('127.0.0.1', TUNNEL_PORT):
                sys.exit('the tunnel to the phone didn\'t open')
            k6_url, java_url = f'http://host.docker.internal:{TUNNEL_PORT}', f'http://localhost:{TUNNEL_PORT}'
        samples = open(out / 'samples.csv', 'w', newline='')
        sampler = subprocess.Popen(SSH + [PHONE, 'INTERVAL=2 python3 -'], stdin=open(HERE / 'sample.py', 'rb'), stdout=samples)
        time.sleep(6)   # a baseline before the load
        if a.test in ('streams', 'orders'):
            per_step, windows, code = java_steps(a, steps, out, java_url)
        else:
            per_step, windows, code = k6_steps(a, steps, out, k6_url)
        time.sleep(6)   # and the recovery after it
    finally:
        if sampler:
            sampler.terminate()
        if tunnel:
            tunnel.terminate()
        if a.via == 'lan':
            lan(False)

    rows = list(csv.DictReader(open(out / 'samples.csv')))
    for s, (lo, hi) in zip(per_step, windows):
        s.update(phone_during(rows, lo, hi))
    result = {'test': a.test, 'target': 'phone', 'via': a.via, 'label': a.label, 'step_seconds': a.step_seconds,
              'client_exit': code, 'started': datetime.fromtimestamp(windows[0][0]).isoformat(timespec='seconds'), 'steps': per_step}
    (out / 'result.json').write_text(json.dumps(result, indent=1), encoding='utf-8')
    print(f'results in {out}')


if __name__ == '__main__':
    main()
