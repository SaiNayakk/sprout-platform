"""The resilience suite:   python deploy/cells/resilience/run.py [scenario ...]    (no names: all of them, one after another)

Needs both cells up. Every scenario ends with both cells NORMAL and replicating again (or fails); the summary says which passed."""
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib  # noqa: E402
import scenarios  # noqa: E402


def main():
    names = sys.argv[1:] or list(scenarios.SCENARIOS)
    out = {}
    for n in names:
        lib.say(f'===== {n}')
        try:
            out[n] = scenarios.SCENARIOS[n]()
        except Exception as e:      # a scenario that cannot run is a failure, and the rest still run
            traceback.print_exc()
            out[n] = {'pass': False, 'error': str(e)}
            lib.heal()
    lib.say('===== summary')
    for n, r in out.items():
        lib.say(f'{n}: {"PASS" if r.get("pass") else "FAIL"}')
    sys.exit(0 if all(r.get('pass') for r in out.values()) else 1)


if __name__ == '__main__':
    main()
