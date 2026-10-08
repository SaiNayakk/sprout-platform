"""Samples what Sprout costs the machine it runs on, every INTERVAL seconds, as CSV on stdout, until killed.

Runs on the phone (Termux) or any Linux host:  ssh phone 'python3 -' < capacity/sample.py
Columns: time, memory available (MB), then CPU (% of one core) and memory (MB, proportional) for each Sprout host,
Postgres (all its processes), NATS and nginx, then battery temperature (C) where Termux:API can tell it.
Only the process's own /proc entries are read, which Android allows for the same user.
"""
import os
import subprocess
import sys
import time

INTERVAL = float(os.environ.get('INTERVAL', '2'))
GROUPS = [('edge', 'edge-host.jar'), ('trading', 'trading-host.jar'), ('money', 'money-host.jar'),
          ('street', 'street-host.jar'), ('postgres', 'postgres'), ('nats', 'nats-server'), ('nginx', 'nginx'),
          ('sshd', 'sshd'), ('cloudflared', 'cloudflared')]
TICK = os.sysconf('SC_CLK_TCK')
PAGE_KB = os.sysconf('SC_PAGE_SIZE') // 1024


def group_of(cmdline):
    for name, needle in GROUPS:
        if needle in cmdline:
            return name
    return None


def pss_mb(pid, rss_mb):
    """Proportional memory: shared pages (Postgres's buffers, the JVM's libraries) split between the processes
    sharing them, so summing processes doesn't count them once each. Falls back to resident memory."""
    try:
        with open(f'/proc/{pid}/smaps_rollup') as f:
            for line in f:
                if line.startswith('Pss:'):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return rss_mb


def processes():
    """pid -> (group, cpu ticks, rss MB) for our processes."""
    out = {}
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            with open(f'/proc/{pid}/cmdline', 'rb') as f:
                cmd = f.read().replace(b'\0', b' ').decode('utf-8', 'replace')
            g = group_of(cmd)
            if g is None or 'sample.py' in cmd:
                continue
            with open(f'/proc/{pid}/stat') as f:
                fields = f.read().rsplit(')', 1)[1].split()
            ticks = int(fields[11]) + int(fields[12])        # utime + stime
            out[pid] = (g, ticks, pss_mb(pid, int(fields[21]) * PAGE_KB / 1024))
        except (OSError, ValueError, IndexError):
            continue
    return out


def available_mb():
    try:
        line = subprocess.run(['free', '-m'], capture_output=True, text=True).stdout.splitlines()[1].split()
        return int(line[6])
    except Exception:
        return -1


def battery_c():
    try:
        r = subprocess.run(['termux-battery-status'], capture_output=True, text=True, timeout=5)
        import json
        return json.loads(r.stdout).get('temperature', '')
    except Exception:
        return ''


names = [g for g, _ in GROUPS]
print('t,available_mb,' + ','.join(f'{n}_cpu,{n}_mb' for n in names) + ',battery_c', flush=True)
before, t0 = processes(), time.time()
last_battery, temp = 0.0, ''
while True:
    time.sleep(INTERVAL)
    now, t1 = processes(), time.time()
    cpu = {n: 0.0 for n in names}
    mem = {n: 0.0 for n in names}
    for pid, (g, ticks, rss) in now.items():
        prev = before.get(pid)
        if prev and prev[0] == g:
            cpu[g] += 100.0 * (ticks - prev[1]) / TICK / (t1 - t0)
        mem[g] += rss
    if t1 - last_battery >= 10:
        temp, last_battery = battery_c(), t1
    print(f'{int(t1)},{available_mb()},' + ','.join(f'{cpu[n]:.0f},{mem[n]:.0f}' for n in names) + f',{temp}', flush=True)
    before, t0 = now, t1
