"""Summarises shapes runs (preprod/shapes/results/<stamp>/<shape>/) as the median of each figure across runs.

    python preprod/shapes/summarize.py <stamp> [<stamp>...]     prints a JSON summary per shape

A run counts for a figure only if it produced that figure: a shape that didn't start, or a load step whose test
didn't finish, is left out of that median and reported in "runs".
"""
import csv
import json
import pathlib
import re
import statistics
import sys
from collections import defaultdict

RESULTS = pathlib.Path(__file__).resolve().parent / 'results'
NOT_JVMS = ('postgres', 'nats', 'lgtm', 'loadgen', 'k6')
RATES = (5, 10, 20, 40, 80)


def mib(text):
    used = text.split('/')[0].strip()
    n = float(re.match(r'[\d.]+', used).group())
    return n * 1024 if 'GiB' in used else n / 1024 if 'KiB' in used else n


def idle(stats):
    """Median over the idle samples of the JVMs' total memory (MiB) and CPU (% of one core)."""
    mem, cpu = defaultdict(float), defaultdict(float)
    for row in csv.reader(stats.open()):
        t, phase, name, used, pct = row[:5]
        if phase != 'idle' or any(f'-{s}-' in name for s in NOT_JVMS):
            continue
        mem[t] += mib(used)
        cpu[t] += float(pct.rstrip('%'))
    return (round(statistics.median(mem.values())), round(statistics.median(cpu.values()))) if mem else (None, None)


def med(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values)) if values else None


def main(stamps):
    out = {}
    for shape in ('one-jvm', 'four-hosts', 'per-service'):
        runs = [RESULTS / s / shape for s in stamps if (RESULTS / s / shape / 'start.json').exists()]
        if not runs:
            continue
        start = [json.loads((r / 'start.json').read_text())['healthyAfterMs'] for r in runs]
        idles = [idle(r / 'stats.csv') for r in runs]
        blasts = [json.loads((r / 'blast.json').read_text()) for r in runs if (r / 'blast.json').exists()]
        load = {}
        for rate in RATES:
            steps = [json.loads((r / f'load-{rate}.json').read_text()) for r in runs if (r / f'load-{rate}.json').exists()]
            if steps:
                load[rate] = {
                    'runs': len(steps),
                    'p50Ms': med(s['p50Ms'] for s in steps),
                    'p95Ms': med(s['p95Ms'] for s in steps),
                    'p99Ms': med(s['p99Ms'] for s in steps),
                    'p95Range': [min(s['p95Ms'] for s in steps), max(s['p95Ms'] for s in steps)],
                    'filled': sum(s.get('filled', 0) for s in steps),
                    'orders': sum(s.get('orders', 0) for s in steps),
                    'outcomes': [s.get('outcomes') for s in steps],
                }
        out[shape] = {
            'runs': [r.parent.name for r in runs],
            'healthyAfterS': med(s / 1000 for s in start),
            'healthyRangeS': [round(min(start) / 1000), round(max(start) / 1000)],
            'idleMemMiB': med(m for m, _ in idles),
            'idleMemRangeMiB': [min(m for m, _ in idles if m), max(m for m, _ in idles if m)],
            'idleCpuPct': med(c for _, c in idles),
            'answeringWhileDown': sorted({b['answeringWhileDown'] for b in blasts}),
            'recoveredAfterS': med(b['recoveredAfterMs'] / 1000 for b in blasts),
            'recoveredRangeS': [round(min(b['recoveredAfterMs'] for b in blasts) / 1000),
                                round(max(b['recoveredAfterMs'] for b in blasts) / 1000)],
            'load': load,
        }
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main(sys.argv[1:])
