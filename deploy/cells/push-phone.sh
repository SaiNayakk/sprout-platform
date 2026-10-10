#!/usr/bin/env bash
# Copies cellwatch (and the phone's starter) to the phone and restarts cellwatch there:   deploy/cells/push-phone.sh
# The starter script start.sh is only copied: the running one is not restarted (that restarts Sprout: ctl.sh restart sprout).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SSH=(ssh -i "${PHONE_KEY:-$HOME/.ssh/backseat_phone}" -p 8022 -o BatchMode=yes -o IdentitiesOnly=yes "${PHONE:-u0_a1@192.168.0.6}")
for f in cellwatch.py cw_env.py cw_logic.py cw_ops.py cw_failback.py; do
  "${SSH[@]}" "cat > ~/sprout/cellwatch/$f.new && mv ~/sprout/cellwatch/$f.new ~/sprout/cellwatch/$f" < "$HERE/$f"
done
"${SSH[@]}" "cat > ~/sprout/cellwatch/run.sh.new && mv ~/sprout/cellwatch/run.sh.new ~/sprout/cellwatch/run.sh" < "$HERE/../phone/cellwatch/run.sh"
"${SSH[@]}" "pkill -f '[c]ellwatch[.]py' || true"
# the starter restarts a piece it did not find at most every ten minutes: start cellwatch now. The starter leaves a cellwatch
# whose status file is fresh alone, so there will not be two
sleep 3
"${SSH[@]}" "ps -eo args | grep -q '[p]ython3 .*cellwatch.py' || (cd ~/sprout/cellwatch && nohup setsid sh run.sh >> ~/sprout/logs/cellwatch.out 2>&1 < /dev/null &) > /dev/null 2>&1 ; sleep 2; echo started"
echo "cellwatch pushed to the phone and running"
