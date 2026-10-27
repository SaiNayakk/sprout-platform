#!/usr/bin/env bash
# Copies cellwatch (and the phone's starter) to the phone and restarts cellwatch there:   deploy/cells/push-phone.sh
# The starter script start.sh is only copied: the running one is not restarted (that restarts Sprout: ctl.sh restart sprout).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# nothing that does not compile reaches a live cell (2026-10-28: a quote broke cw_ops.py and cellwatch crashed on start)
python -m py_compile "$HERE"/cellwatch.py "$HERE"/cw_*.py || { echo "cellwatch does not compile: not pushing"; exit 1; }
SSH=(ssh -i "${PHONE_KEY:-$HOME/.ssh/backseat_phone}" -p 8022 -o BatchMode=yes -o IdentitiesOnly=yes "${PHONE:-u0_a1@192.168.0.6}")
for f in cellwatch.py cw_env.py cw_logic.py cw_ops.py cw_failback.py cw_witness.py; do
  "${SSH[@]}" "cat > ~/sprout/cellwatch/$f.new && mv ~/sprout/cellwatch/$f.new ~/sprout/cellwatch/$f" < "$HERE/$f"
done
"${SSH[@]}" "cat > ~/sprout/cellwatch/run.sh.new && mv ~/sprout/cellwatch/run.sh.new ~/sprout/cellwatch/run.sh" < "$HERE/../phone/cellwatch/run.sh"
# the standby's launcher (read when the standby next starts) and the web server's template (rendered and reloaded now)
"${SSH[@]}" "cat > ~/sprout/standby/run.sh.new && mv ~/sprout/standby/run.sh.new ~/sprout/standby/run.sh" < "$HERE/../phone/standby/run.sh"
"${SSH[@]}" "cat > ~/sprout/web/nginx.conf.template.new && mv ~/sprout/web/nginx.conf.template.new ~/sprout/web/nginx.conf.template && (sh ~/sprout/web/run.sh reload || true)" < "$HERE/../phone/web/nginx.conf.template"
"${SSH[@]}" "pkill -f '[c]ellwatch[.]py' || true"
# The starter (start.sh) starts it again: within its next check, but it starts a piece it did not find at most every ten minutes.
# `--now` starts one by hand instead, which is quicker but then nothing manages it (it survives `ctl.sh stop sprout`).
if [ "${1:-}" = "--now" ]; then
  sleep 3
  "${SSH[@]}" "ps -eo args | grep -q '[p]ython3 .*cellwatch.py' || (cd ~/sprout/cellwatch && nohup setsid sh run.sh >> ~/sprout/logs/cellwatch.out 2>&1 < /dev/null &) > /dev/null 2>&1 ; sleep 2; echo started"
fi
echo "cellwatch pushed to the phone"
