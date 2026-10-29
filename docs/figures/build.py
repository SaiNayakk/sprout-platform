"""Draws the docs' figures from what the runs recorded, with no libraries, and writes the numbers into the pages.

    python docs/figures/build.py

Nothing here is drawn by hand: every figure comes from a file a test or a measurement wrote.
  - deploy/cells/results/<scenario>-<MMDDHHMM>.json and its -timeline.csv: the resilience suite's runs. The latest run of
    kill-cell-a and kill-cell-b becomes a timeline of both cells' states, marked where the timeline says things happened.
  - docs/figures/data/memory-*.json: memory measured on the phone (Pss + SwapPss of each process, summed by piece).
The numbers table in docs/reliability/resilience.md, between the figures:begin and figures:end markers, is rewritten from
the latest run of every scenario. Re-run after a new run or measurement; commit what changes.
"""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / 'deploy' / 'cells' / 'results'
OUT = ROOT / 'docs' / 'assets' / 'figures'
DATA = Path(__file__).resolve().parent / 'data'
PAGE = ROOT / 'docs' / 'reliability' / 'resilience.md'

STATE_COLORS = {'NORMAL': '#2f7d4f', 'TAKING_OVER': '#d4a017', 'HOLDING': '#1d4ed8', 'TAKEN_OVER': '#7c3aed',
                'FAILING_BACK': '#0e7490', 'FENCED': '#b4432f', 'silent': '#4b5563'}
SCENARIOS = {'kill-cell-a': "the phone's cell stopped", 'kill-cell-b': "the laptop's cell stopped",
             'dead-host-trading': 'one JVM host killed', 'holder-dies': 'the cell serving both dies',
             'cf-blind': "the cells can't see each other", 'mutual-blind': "the cells can't see each other at all",
             'blind-no-witness': 'blind to each other and to the witness', 'both-offline': 'both public addresses down',
             'failed-takeover': "a takeover that can't finish", 'replication-off': 'replication silently switched off',
             'laptop-restart': "the laptop's containers all restarted"}


def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def latest(scenario):
    runs = sorted(RESULTS.glob(f'{scenario}-[0-9]*.json'), key=lambda p: re.sub(r'\D', '', p.stem))
    runs = [p for p in runs if re.fullmatch(rf'{scenario}-\d{{8}}', p.stem)]
    return runs[-1] if runs else None


def timeline_csv(result):
    """The states CSV written alongside a run: the newest one written before the result."""
    stamp = result.stem.rsplit('-', 1)[1]
    scenario = result.stem.rsplit('-', 1)[0]
    csvs = sorted(p for p in RESULTS.glob(f'{scenario}-*-timeline.csv') if p.stem.split('-')[-2] <= stamp)
    return csvs[-1] if csvs else None


def failover_svg(result, out):
    """Two lanes, cell A and cell B, coloured by state through the run, with the run's own events marked."""
    run = json.loads(result.read_text(encoding='utf-8'))
    rows = list(csv.DictReader(open(timeline_csv(result), encoding='utf-8')))
    W, L, R, T, LANE, GAP = 760, 110, 20, 64, 26, 8
    t1 = int(rows[-1]['t']) + 5
    px = lambda t: L + (W - L - R) * t / t1
    lanes = [('cell_a', 'Region A (phone)'), ('cell_b', 'Region B (laptop)')]
    bottom = T + len(lanes) * (LANE + GAP)
    H = bottom + 76
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="system-ui, sans-serif" font-size="12" '
         f'role="img" aria-label="{esc(SCENARIOS.get(run["scenario"], run["scenario"]))}: both cells\' states over time">',
         f'<rect width="{W}" height="{H}" fill="#fff"/>']
    for i, (key, label) in enumerate(lanes):
        y = T + i * (LANE + GAP)
        s.append(f'<text x="{L - 8}" y="{y + 17}" text-anchor="end" fill="#333">{label}</text>')
        for j, r in enumerate(rows):
            end = int(rows[j + 1]['t']) if j + 1 < len(rows) else int(r['t']) + 5
            state = r[key].split('/')[0]
            s.append(f'<rect x="{px(int(r["t"])):.1f}" y="{y}" width="{max(px(end) - px(int(r["t"])), 1):.1f}" height="{LANE}" '
                     f'fill="{STATE_COLORS.get(state, "#9ca3af")}"><title>{esc(r[key])} at {r["t"]} s</title></rect>')
    step = 120 if t1 > 600 else 60
    for t in range(0, t1, step):
        s.append(f'<line x1="{px(t):.1f}" x2="{px(t):.1f}" y1="{T - 4}" y2="{bottom}" stroke="#d1d5db" stroke-dasharray="2 3"/>')
        s.append(f'<text x="{px(t):.1f}" y="{bottom + 14}" text-anchor="middle" fill="#555">{t // 60} min</text>')
    # the run's own events: where a cell's state changed, as the suite logged it ("+95s A=silent B=NORMAL")
    marks, last = [], None
    for e in run.get('timeline', []):
        m = re.match(r'\+(\d+)s A=(\S+) B=(\S+)', e)
        if not m:
            continue
        t, a, b = int(m.group(1)), m.group(2), m.group(3)
        if last and (a, b) != last:
            what = [f'{n} {s_.lower().replace("_", " ")}' for n, s_, o in (('A', a, last[0]), ('B', b, last[1])) if s_ != o]
            marks.append((t, ', '.join(what)))
        last = (a, b)
    for k, (t, name) in enumerate(marks[:6]):
        x = px(t)
        s.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{T - 6 - (k % 3) * 14}" y2="{bottom}" stroke="#141833" stroke-width="1"/>')
        anchor = 'end' if x > W - 160 else 'start'
        s.append(f'<text x="{x + (-3 if anchor == "end" else 3):.1f}" y="{T - 8 - (k % 3) * 14}" text-anchor="{anchor}" fill="#141833">'
                 f'{esc(name)}</text>')
    lx, ly = L, H - 40
    for label in ('NORMAL', 'TAKING_OVER', 'HOLDING', 'TAKEN_OVER', 'FAILING_BACK', 'FENCED', 'silent'):
        s.append(f'<rect x="{lx}" y="{ly}" width="12" height="12" fill="{STATE_COLORS[label]}"/>'
                 f'<text x="{lx + 16}" y="{ly + 10}" fill="#333">{label.lower().replace("_", " ")}</text>')
        lx += 22 + 7 * len(label)
    orders = run.get('orders', {})
    s.append(f'<text x="{L}" y="{H - 10}" fill="#333">{orders.get("acknowledged", "?")} orders acknowledged during the run: '
             f'{orders.get("missing", "?")} lost, {orders.get("applied_twice", "?")} applied twice. Orders back after '
             f'{run.get("orders_back_after_s", "?")} s.</text>')
    s.append('</svg>')
    out.write_text('\n'.join(s), encoding='utf-8')


def memory_svg(measured, out):
    """Paired bars per piece: before and after, in MB."""
    m = json.loads(measured.read_text(encoding='utf-8'))
    pieces = m['pieces']
    W, L, R, T, ROW = 640, 150, 70, 34, 34
    top = max(max(p['before_mb'], p['after_mb']) for p in pieces)
    px = lambda v: (W - L - R) * v / top
    H = T + ROW * len(pieces) + 46
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="system-ui, sans-serif" font-size="12" '
         f'role="img" aria-label="{esc(m["title"])}">', f'<rect width="{W}" height="{H}" fill="#fff"/>',
         f'<text x="{L}" y="18" fill="#141833" font-weight="600">{esc(m["title"])}</text>']
    for i, p in enumerate(pieces):
        y = T + i * ROW
        s.append(f'<text x="{L - 8}" y="{y + 16}" text-anchor="end" fill="#333">{esc(p["name"])}</text>')
        s.append(f'<rect x="{L}" y="{y}" width="{px(p["before_mb"]):.1f}" height="11" fill="#9ca3af"/>'
                 f'<text x="{L + px(p["before_mb"]) + 4:.1f}" y="{y + 10}" fill="#555">{p["before_mb"]} MB</text>')
        s.append(f'<rect x="{L}" y="{y + 13}" width="{px(p["after_mb"]):.1f}" height="11" fill="#2f7d4f"/>'
                 f'<text x="{L + px(p["after_mb"]) + 4:.1f}" y="{y + 23}" fill="#2f7d4f">{p["after_mb"]} MB</text>')
    y = H - 22
    s.append(f'<rect x="{L}" y="{y}" width="12" height="12" fill="#9ca3af"/><text x="{L + 16}" y="{y + 10}" fill="#333">{esc(m["before"])}</text>'
             f'<rect x="{L + 190}" y="{y}" width="12" height="12" fill="#2f7d4f"/><text x="{L + 206}" y="{y + 10}" fill="#333">{esc(m["after"])}</text>')
    s.append('</svg>')
    out.write_text('\n'.join(s), encoding='utf-8')


def numbers_table():
    lines = ['| Scenario | Latest run | Result | Orders back after | Orders acknowledged | Lost | Applied twice |',
             '|---|---|---|---|---|---|---|']
    for scenario, what in SCENARIOS.items():
        p = latest(scenario)
        if not p:
            continue
        r = json.loads(p.read_text(encoding='utf-8'))
        o = r.get('orders') or {}
        stamp = p.stem.rsplit('-', 1)[1]
        back = r.get('orders_back_after_s')
        lines.append(f'| `{scenario.replace("-", "_")}`: {what} | {stamp[2:4]}/{stamp[:2]} {stamp[4:6]}:{stamp[6:]} | '
                     f'{"pass" if r.get("pass") else "**fail**"} | {f"{back} s" if back is not None else "-"} | '
                     f'{o.get("acknowledged", "-")} | {o.get("missing", "-")} | {o.get("applied_twice", "-")} |')
    return '\n'.join(lines)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    made = []
    for scenario in ('kill-cell-a', 'kill-cell-b'):
        p = latest(scenario)
        if p and timeline_csv(p):
            failover_svg(p, OUT / f'{scenario}.svg')
            made.append(f'{scenario}.svg (from {p.name})')
    for measured in sorted(DATA.glob('memory-*.json')):
        memory_svg(measured, OUT / f'{measured.stem}.svg')
        made.append(f'{measured.stem}.svg')
    page = PAGE.read_text(encoding='utf-8')
    block = f'<!-- figures:begin (written by docs/figures/build.py) -->\n{numbers_table()}\n<!-- figures:end -->'
    page, n = re.subn(r'<!-- figures:begin.*?<!-- figures:end -->', lambda _: block, page, flags=re.S)
    if n:
        PAGE.write_text(page, encoding='utf-8', newline='\n')
        made.append('the numbers table in reliability/resilience.md')
    print('\n'.join(made))


if __name__ == '__main__':
    main()
