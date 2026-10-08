#!/data/data/com.termux/files/usr/bin/sh
# cellwatch for cell A (deploy/cells/cellwatch.py, ADR-027): fences this cell when it can't be reached, or takes cell
# B's customers over when the laptop is lost. A piece of start.sh.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
S="$HOME/sprout"
set -a
. "$HOME/.sprout.env"
set +a
mkdir -p "$S/cells" "$S/journal"
export CELL=a PEER=b
export SELF_URL=https://sprout-a-saiworks.nncs.in PEER_URL=https://sprout-b-saiworks.nncs.in
export LOCAL_CHECK=http://127.0.0.1:8100/api/marketdata/v1/market
export STATUS_FILE="$S/cells/status.json" ROUTES_FILE="$S/cells/routes.conf" CELLS_FILE="$S/cells/cells.json"
export STATE_FILE="$S/cells/state.json" LOG_FILE="$S/logs/cellwatch.log"
export FENCE_FILE="$S/journal/fenced" JOURNAL_DIR="$S/journal"
export WEIGHTS="${CELL_WEIGHTS:-a=30,b=70}"
export REPLICA_PSQL="psql -d sprout_b -v ON_ERROR_STOP=1 -q"
export STANDBY_START="sh $S/ctl.sh start sprout-standby" STANDBY_STOP="sh $S/ctl.sh stop sprout-standby"
export STANDBY_GATEWAY=http://127.0.0.1:8200 STANDBY_CHECK=http://127.0.0.1:8200/api/marketdata/v1/market
export RELOAD_ROUTES="sh $S/web/run.sh reload"
exec python3 "$S/cellwatch/cellwatch.py"
