"""Draws the docs' figures from what the runs recorded, with no libraries, and writes the numbers into the pages.

    python docs/figures/build.py

Nothing here is drawn by hand: every figure comes from a file a test or a measurement wrote.
  - deploy/cells/results/<scenario>-<MMDDHHMM>.json and its -timeline.csv: the resilience suite's runs. The latest run of
    kill-cell-a and kill-cell-b becomes a timeline of both regions, marked where the run's states say things happened.
  - docs/figures/data/memory-*.json: memory measured on the phone (Pss + SwapPss of each process, summed by piece).
The numbers table in docs/reliability/resilience.md, between the figures:begin and figures:end markers, is rewritten from
the latest run of every scenario (it is also the figures' table view). Re-run after a new run or measurement; commit what
changes.

The look follows one method: thin marks with 4px rounded ends and 2px gaps of surface between them, solid hairline grids,
text in ink colours (never a series colour), a title that says what to see, a legend, and its own dark mode. The colours
are the first three categorical slots of a palette validated for colour-blind separation in light and dark, plus a
neutral grey; the third is under 3:1 on the light surface, so segments that fit carry their own label.
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

# A cell's state, folded into what it meant for customers: four kinds, one colour each.
KIND = {'NORMAL': 'own', 'HOLDING': 'both', 'TAKING_OVER': 'switching', 'FAILING_BACK': 'switching',
        'TAKEN_OVER': 'out', 'FENCED': 'out', 'silent': 'out'}
KIND_LABEL = {'own': 'its own customers', 'both': "both regions' customers", 'switching': 'switching over',
              'out': 'out: stopped, fenced or handed over'}
KIND_SHORT = {'own': 'own customers', 'both': 'both regions', 'switching': 'switching', 'out': 'out'}
STYLE = """<style>
  .viz { --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7;
         --own:#2a78d6; --both:#eb6834; --switching:#1baf7a; --out:#c3c2b7; --peak:#c3c2b7; --demo:#2a78d6;
         --on-fill:#ffffff; --on-out:#0b0b0b; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
  @media (prefers-color-scheme: dark) {
    .viz { --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --grid:#2c2c2a; --axis:#383835;
           --own:#3987e5; --both:#d95926; --switching:#199e70; --out:#52514e; --peak:#6d6c67; --demo:#3987e5; --on-out:#f0efec; }
  }
  .bg { fill: var(--surface); }
  .t1 { fill: var(--ink); font-size: 15px; font-weight: 600; }
  .t2 { fill: var(--ink2); font-size: 12.5px; }
  .lab { fill: var(--ink2); font-size: 12px; }
  .tick { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
  .grid { stroke: var(--grid); stroke-width: 1; }
  .axis { stroke: var(--axis); stroke-width: 1; }
  .mark { stroke: var(--ink2); stroke-width: 1; }
  .in { fill: var(--on-fill); font-size: 11px; font-weight: 600; }
  .in.dim { fill: var(--on-out); font-weight: 500; }
  .own { fill: var(--own); } .both { fill: var(--both); } .switching { fill: var(--switching); } .out { fill: var(--out); }
  .peak { fill: var(--peak); stroke: var(--surface); stroke-width: 2; }
  .demo { fill: var(--demo); stroke: var(--surface); stroke-width: 2; }
  .link { stroke: var(--axis); stroke-width: 2; stroke-linecap: round; }
</style>"""
SCENARIOS = {'kill-cell-a': "the phone's cell stopped", 'kill-cell-b': "the laptop's cell stopped",
             'dead-host-trading': 'one JVM host killed', 'holder-dies': 'the cell serving both dies',
             'cf-blind': "the cells can't see each other", 'mutual-blind': "the cells can't see each other at all",
             'blind-no-witness': 'blind to each other and to the witness', 'both-offline': 'both public addresses down',
             'failed-takeover': "a takeover that can't finish", 'replication-off': 'replication silently switched off',
             'laptop-restart': "the laptop's containers all restarted"}


def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def text_width(t, size=11):
    return len(t) * size * 0.56


def latest(scenario):
    runs = [p for p in RESULTS.glob(f'{scenario}-[0-9]*.json') if re.fullmatch(rf'{scenario}-\d{{8}}', p.stem)]
    return max(runs, key=lambda p: p.stem.rsplit('-', 1)[1]) if runs else None


def timeline_csv(result):
    """The states CSV written alongside a run: the newest one started before the result was written."""
    scenario, stamp = result.stem.rsplit('-', 1)
    csvs = sorted(p for p in RESULTS.glob(f'{scenario}-*-timeline.csv') if p.stem.split('-')[-2] <= stamp)
    return csvs[-1] if csvs else None


def kind(state):
    return KIND.get(state.split('/')[0], 'out')


def failover_svg(result, out):
    """Two lanes, Region A and Region B, each a run of segments coloured by what the cell meant for its customers."""
    run = json.loads(result.read_text(encoding='utf-8'))
    rows = list(csv.DictReader(open(timeline_csv(result), encoding='utf-8')))
    fault = next((int(r['t']) for r in rows if kind(r['cell_a']) != 'own' or kind(r['cell_b']) != 'own'), 0)
    t0, t1 = max(fault - 60, 0), int(rows[-1]['t']) + 5
    W, L, R, T, LANE, GAP = 760, 128, 24, 96, 24, 14
    px = lambda t: L + (W - L - R) * (t - t0) / (t1 - t0)
    lanes = [('cell_a', 'Region A (phone)'), ('cell_b', 'Region B (laptop)')]
    bottom = T + len(lanes) * LANE + (len(lanes) - 1) * GAP
    H = bottom + 96   # room for the legend on two rows
    stopped = 'A' if run['scenario'].endswith('-a') else 'B'
    o = run.get('orders', {})
    acked = o.get('acknowledged')
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" class="viz" role="img" '
         f'aria-label="Region {stopped} stopped; the other region served its customers, then handed them back">', STYLE,
         f'<rect class="bg" width="{W}" height="{H}" rx="8"/>',
         f'<text class="t1" x="{L}" y="28">Region {stopped} stopped: the other region took its customers, then gave them back</text>',
         f'<text class="t2" x="{L}" y="48">Orders worked again after {run.get("orders_back_after_s", "?")} s. '
         f'{f"{acked:,}" if isinstance(acked, int) else "?"} orders acknowledged during the run: {o.get("missing", "?")} lost, '
         f'{o.get("applied_twice", "?")} applied twice.</text>']
    step = 120 if t1 - fault > 600 else 60
    for t in range(fault, t1, step):
        x = px(t)
        s.append(f'<line class="grid" x1="{x:.1f}" x2="{x:.1f}" y1="{T - 4}" y2="{bottom}"/>')
        s.append(f'<text class="tick" x="{x:.1f}" y="{bottom + 20}" text-anchor="middle">'
                 f'{"stopped" if t == fault else f"+{(t - fault) // 60} min"}</text>')
    s.append(f'<line class="axis" x1="{L}" x2="{W - R}" y1="{bottom + 6}" y2="{bottom + 6}"/>')
    for i, (key, label) in enumerate(lanes):
        y = T + i * (LANE + GAP)
        s.append(f'<text class="lab" x="{L - 10}" y="{y + 16}" text-anchor="end">{label}</text>')
        segs = []   # [kind, start, end]: consecutive rows of one kind merged
        for j, r in enumerate(rows):
            t = int(r['t'])
            end = int(rows[j + 1]['t']) if j + 1 < len(rows) else t + 5
            if end <= t0:
                continue
            k = kind(r[key])
            if segs and segs[-1][0] == k:
                segs[-1][2] = end
            else:
                segs.append([k, max(t, t0), end])
        for k, a, b in segs:
            x, w = px(a) + 1, max(px(b) - px(a) - 2, 1)   # the 2px gap of surface between segments
            s.append(f'<rect class="{k}" x="{x:.1f}" y="{y}" width="{w:.1f}" height="{LANE}" rx="4">'
                     f'<title>{KIND_LABEL[k]}: {a - fault:+d} s to {b - fault:+d} s</title></rect>')
            if text_width(KIND_SHORT[k]) + 12 <= w:
                s.append(f'<text class="in{" dim" if k == "out" else ""}" x="{x + 6:.1f}" y="{y + 16}">{KIND_SHORT[k]}</text>')
    # the moments that matter, marked once each above the lanes
    moments, prev = [], None
    for r in rows:
        now, t = (kind(r['cell_a']), kind(r['cell_b'])), int(r['t'])
        if prev and now != prev:
            if 'both' in now and 'both' not in prev:
                moments.append((t, 'took over'))
            elif 'both' in prev and 'both' not in now:
                moments.append((t, 'handed back'))
        prev = now
    for k, (t, name) in enumerate(moments[:4]):
        x = px(t)
        s.append(f'<line class="mark" x1="{x:.1f}" x2="{x:.1f}" y1="{T - 16}" y2="{bottom}"/>')
        anchor = 'end' if x > W - 150 else 'start'
        s.append(f'<text class="lab" x="{x + (-5 if anchor == "end" else 5):.1f}" y="{T - 20}" text-anchor="{anchor}">'
                 f'{name} at {(t - fault) // 60}:{(t - fault) % 60:02d}</text>')
    lx, ly = L, H - 46
    for k in ('own', 'both', 'switching', 'out'):
        label = KIND_LABEL[k]
        if lx + 17 + text_width(label, 12) * 1.15 > W - R:
            lx, ly = L, ly + 18
        s.append(f'<rect class="{k}" x="{lx}" y="{ly}" width="12" height="12" rx="3"/>'
                 f'<text class="lab" x="{lx + 17}" y="{ly + 10}">{label}</text>')
        lx += 17 + text_width(label, 12) + 18
    s.append('</svg>')
    out.write_text('\n'.join(s), encoding='utf-8')


def memory_svg(measured, out):
    """Before -> after per piece (a dumbbell): the peak profile's size, the demo profile's, and the line between."""
    m = json.loads(measured.read_text(encoding='utf-8'))
    pieces = m['pieces']
    W, L, R, T, ROW = 640, 128, 120, 92, 34
    top = max(p['before_mb'] for p in pieces) * 1.05
    px = lambda v: L + (W - L - R) * v / top
    bottom = T + ROW * (len(pieces) - 1)
    H = bottom + 74
    before, after = sum(p['before_mb'] for p in pieces), sum(p['after_mb'] for p in pieces)
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" class="viz" role="img" aria-label="{esc(m["title"])}">',
         STYLE, f'<rect class="bg" width="{W}" height="{H}" rx="8"/>',
         f'<text class="t1" x="{L}" y="28">{esc(m["title"])}</text>',
         f'<text class="t2" x="{L}" y="48">{before - after} MB less in all, {before} MB to {after} MB: the same services and cells, '
         f'sized for a demo.</text>']
    for v in range(0, int(top) + 1, 50):
        x = px(v)
        s.append(f'<line class="grid" x1="{x:.1f}" x2="{x:.1f}" y1="{T - 16}" y2="{bottom + 14}"/>')
        s.append(f'<text class="tick" x="{x:.1f}" y="{bottom + 30}" text-anchor="middle">{v} MB</text>')
    for i, p in enumerate(pieces):
        y = T + i * ROW
        a, b = px(p['before_mb']), px(p['after_mb'])
        s.append(f'<text class="lab" x="{L - 10}" y="{y + 4}" text-anchor="end">{esc(p["name"])}</text>')
        s.append(f'<line class="link" x1="{b:.1f}" x2="{a:.1f}" y1="{y}" y2="{y}"/>')
        s.append(f'<circle class="peak" cx="{a:.1f}" cy="{y}" r="6"><title>peak: {p["before_mb"]} MB</title></circle>')
        s.append(f'<circle class="demo" cx="{b:.1f}" cy="{y}" r="6"><title>demo: {p["after_mb"]} MB</title></circle>')
        s.append(f'<text class="lab" x="{a + 12:.1f}" y="{y + 4}">{p["after_mb"]} MB '
                 f'<tspan class="tick">from {p["before_mb"]}</tspan></text>')
    lx, ly = L, H - 22
    for cls, label in (('peak', esc(m['before'])), ('demo', esc(m['after']))):
        s.append(f'<circle class="{cls}" cx="{lx + 6}" cy="{ly + 6}" r="6"/><text class="lab" x="{lx + 18}" y="{ly + 10}">{label}</text>')
        lx += 18 + text_width(label, 12) + 24
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
