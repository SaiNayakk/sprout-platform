"""Draws a failover test's timeline (deploy/cells/results/chaos16-*-timeline.csv) as an SVG of lanes, with no libraries.

    python capacity/timeline.py OUT.svg TIMELINE.csv [MARK=seconds_after_fault ...]

One lane per probed route (what a customer of the cell saw: 200 green, 503 orange, 401 grey) and one per cell's published
state. Each MARK draws a labelled vertical line, e.g. "phone takes over"=609.
"""
import csv
import sys
from pathlib import Path

W, L, R, T, LANE, GAP = 760, 96, 20, 44, 22, 6
COLORS = {'200': '#2f7d4f', '503': '#c2410c', '401': '#9ca3af', 'NORMAL': '#2f7d4f', 'NORMAL/sick': '#d4a017',
          'FENCED': '#b4432f', 'FENCED/sick': '#b4432f', 'HOLDING': '#1d4ed8', 'TAKEN_OVER': '#7c3aed',
          'TAKEN_OVER/sick': '#7c3aed', 'silent': '#9ca3af'}
LEGEND = [('200 / NORMAL', '#2f7d4f'), ('503 (host down)', '#c2410c'), ('sick', '#d4a017'), ('fenced', '#b4432f'),
          ('holding', '#1d4ed8'), ('taken over', '#7c3aed'), ('401: test token lapsed', '#9ca3af')]


def main():
    out, path, marks = sys.argv[1], sys.argv[2], sys.argv[3:]
    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    fault = next(int(r['t_seconds']) - int(r['phase'][1:-1]) for r in rows if r['phase'].startswith('+'))
    for r in rows:
        r['t'] = int(r['t_seconds']) - fault
    lanes = [('market', 'market (trading)'), ('orders', 'orders (trading)'), ('funds', 'funds (trading)'),
             ('bank', 'bank (street)'), ('cell_b', 'cell B (laptop)'), ('cell_a', 'cell A (phone)')]
    t0, t1 = rows[0]['t'], rows[-1]['t'] + 6
    px = lambda t: L + (W - L - R) * (t - t0) / (t1 - t0)
    H = T + len(lanes) * (LANE + GAP) + 92
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="system-ui, sans-serif" font-size="12">',
         f'<rect width="{W}" height="{H}" fill="#fff"/>']
    for i, (key, label) in enumerate(lanes):
        y = T + i * (LANE + GAP)
        s.append(f'<text x="{L - 8}" y="{y + 15}" text-anchor="end" fill="#333">{label}</text>')
        for j, r in enumerate(rows):
            end = rows[j + 1]['t'] if j + 1 < len(rows) else r['t'] + 6
            s.append(f'<rect x="{px(r["t"]):.1f}" y="{y}" width="{max(px(end) - px(r["t"]), 1):.1f}" height="{LANE}" '
                     f'fill="{COLORS.get(r[key], "#9ca3af")}"/>')
    bottom = T + len(lanes) * (LANE + GAP)
    step = 120 if t1 - t0 > 600 else 60
    first = (t0 // step) * step
    for t in range(first, int(t1) + 1, step):
        if t < t0:
            continue
        s.append(f'<line x1="{px(t):.1f}" x2="{px(t):.1f}" y1="{T - 4}" y2="{bottom}" stroke="#d1d5db" stroke-dasharray="2 3"/>')
        label = f'{t // 60} min' if t else 'fault'
        s.append(f'<text x="{px(t):.1f}" y="{bottom + 14}" text-anchor="middle" fill="#555">{label}</text>')
    for k, m in enumerate(marks):
        name, sec = m.rsplit('=', 1)
        x = px(float(sec))
        s.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{T - 4}" y2="{bottom}" stroke="#141833" stroke-width="1.5"/>')
        anchor = 'end' if (x > W - 130 or k % 2) else 'start'
        dx = -4 if anchor == 'end' else 4
        s.append(f'<text x="{x + dx:.1f}" y="{T - 10}" text-anchor="{anchor}" fill="#141833" font-weight="600">{name}</text>')
    lx, ly = L, H - 46
    for label, color in LEGEND:
        width = 17 + 6.6 * len(label) + 16
        if lx + width > W - R:
            lx, ly = L, ly + 20
        s.append(f'<rect x="{lx}" y="{ly}" width="12" height="12" fill="{color}"/>'
                 f'<text x="{lx + 17}" y="{ly + 10}" fill="#333">{label}</text>')
        lx += width
    s.append('</svg>')
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text('\n'.join(s), encoding='utf-8')


if __name__ == '__main__':
    main()
