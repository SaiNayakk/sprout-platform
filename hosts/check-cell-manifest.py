"""Fails when the cell host's release manifest differs from the four hosts' (ADR-027): the standby must run exactly the
service versions the cells run. CI runs it.   python hosts/check-cell-manifest.py"""
import re
import sys
from pathlib import Path

HOSTS = Path(__file__).resolve().parent


def pins(host):
    text = (HOSTS / host / 'pom.xml').read_text(encoding='utf-8')
    return dict(re.findall(r'<sprout-([a-z]+)\.version>([^<]+)</sprout-\1\.version>', text))


union = {}
for host in ('edge', 'trading', 'money', 'street'):
    union.update(pins(host))
cell = pins('cell')
wrong = {n: (cell.get(n), v) for n, v in union.items() if cell.get(n) != v}
extra = set(cell) - set(union)
if wrong or extra:
    for n, (got, want) in sorted(wrong.items()):
        print(f'cell host pins sprout-{n} {got}; the hosts pin {want}')
    for n in sorted(extra):
        print(f'cell host pins sprout-{n}, which no host runs')
    sys.exit(1)
print(f'cell host manifest matches the hosts ({len(cell)} services)')
