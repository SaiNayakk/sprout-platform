"""Checks the phone scripts without a phone: shell syntax, and that the Python embedded in them
(the <<'PY' heredocs) compiles. Pre-prod never runs these scripts, so CI is their only check."""
import re
import subprocess
import sys
from pathlib import Path

failed = False
for script in sorted(Path(__file__).parent.rglob("*.sh")):
    text = script.read_text(encoding="utf-8")
    if subprocess.run(["sh", "-n", str(script)]).returncode != 0:
        failed = True
    for n, block in enumerate(re.findall(r"<<'PY'\n(.*?)\nPY\n", text, re.S), 1):
        try:
            compile(block, f"{script.name} (python block {n})", "exec")
        except SyntaxError as e:
            print(f"{script.name}: python block {n}: {e}")
            failed = True
    print(f"checked {script.relative_to(Path(__file__).parent)}")
sys.exit(1 if failed else 0)
