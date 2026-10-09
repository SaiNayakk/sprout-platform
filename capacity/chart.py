"""Draws capacity results as SVG line charts, with no libraries, for the docs.

    python capacity/chart.py OUT.svg METRIC "label=results/<run>" ["label=results/<run>" ...]

METRIC is one of: rps (requests a second served), p95 (95th percentile latency, ms), cpu (the host's average CPU,
% of one core). The x axis is each step's concurrent users. Each run is one line.
"""
import json
import sys
from pathlib import Path

COLORS = ['#2f7d4f', '#c2410c', '#1d4ed8', '#7c3aed', '#a16207', '#be123c']
METRICS = {
    'rps': ('requests a second', lambda s: s.get('requests_per_s') or 0),
    'p95': ('p95 latency (s)', lambda s: (s.get('p95_ms') or 0) / 1000),
    'cpu': ('CPU, cores busy (average)', lambda s: (s.get('phone_cpu_avg_pct') or 0) / 100),
}
W, H, L, R, T, B = 640, 340, 56, 150, 20, 44


def nice_max(v):
    for e in range(-2, 6):
        for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8):
            top = m * 10 ** e
            if top >= v:
                return top
    return v


def main():
    out, metric, runs = sys.argv[1], sys.argv[2], sys.argv[3:]
    title, get = METRICS[metric]
    series = []
    for run in runs:
        label, path = run.split('=', 1)
        steps = json.loads((Path(path) / 'result.json').read_text(encoding='utf-8'))['steps']
        series.append((label, [(s['asked'], get(s)) for s in steps if s.get('requests_per_s') and s.get('p95_ms')]))
    xmax = nice_max(max(x for _, pts in series for x, _ in pts))
    ymax = nice_max(max(y for _, pts in series for _, y in pts) * 1.05)
    if metric == 'p95':
        ymax = min(ymax, 10)   # past 10 s the step is broken anyway; the axis would hide the knee
    px = lambda x: L + (W - L - R) * x / xmax
    py = lambda y: T + (H - T - B) * (1 - min(y, ymax) / ymax)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="system-ui, sans-serif" font-size="12">',
           f'<rect width="{W}" height="{H}" fill="#fff"/>']
    for i in range(6):
        y = ymax * i / 5
        svg.append(f'<line x1="{L}" x2="{W - R}" y1="{py(y):.1f}" y2="{py(y):.1f}" stroke="#e5e7eb"/>')
        svg.append(f'<text x="{L - 6}" y="{py(y) + 4:.1f}" text-anchor="end" fill="#555">{y:g}</text>')
    for i in range(6):
        x = xmax * i / 5
        svg.append(f'<text x="{px(x):.1f}" y="{H - B + 16}" text-anchor="middle" fill="#555">{x:g}</text>')
    svg.append(f'<text x="{(L + W - R) / 2}" y="{H - 8}" text-anchor="middle" fill="#333">concurrent users</text>')
    svg.append(f'<text x="14" y="{(T + H - B) / 2}" text-anchor="middle" fill="#333" transform="rotate(-90 14 {(T + H - B) / 2})">{title}</text>')
    for n, (label, pts) in enumerate(series):
        c = COLORS[n % len(COLORS)]
        svg.append(f'<polyline fill="none" stroke="{c}" stroke-width="2.5" points="{" ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in pts)}"/>')
        for x, y in pts:
            svg.append(f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="3" fill="{c}"/>')
        ly = T + 8 + n * 20
        svg.append(f'<rect x="{W - R + 12}" y="{ly - 9}" width="12" height="12" fill="{c}"/>')
        svg.append(f'<text x="{W - R + 30}" y="{ly + 1}" fill="#333">{label}</text>')
    svg.append('</svg>')
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text('\n'.join(svg), encoding='utf-8')


if __name__ == '__main__':
    main()
