#!/data/data/com.termux/files/usr/bin/sh
# cellwatch for cell A (deploy/cells/cellwatch.py and cw_*.py, ADR-027): keeps this cell safe and served, takes cell B's customers
# over when the laptop is lost, and takes its own back when it returns. A piece of start.sh.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
S="$HOME/sprout"
set -a
. "$HOME/.sprout.env"
set +a
mkdir -p "$S/cells" "$S/journal"
export PYTHONPATH="$HERE" PYTHONDONTWRITEBYTECODE=1
export CELL=a PEER=b PREFERRED_SURVIVOR=b
export SELF_URL=https://sprout-a-saiworks.nncs.in PEER_URL=https://sprout-b-saiworks.nncs.in
export LOCAL_CHECK=http://127.0.0.1:8100/api/marketdata/v1/market
# every service of every host: the health of the cell, one host at a time
H=http://127.0.0.1
export HOST_CHECKS="edge=$H:8101/actuator/health,$H:8119/actuator/health;trading=$H:8103/actuator/health,$H:8109/actuator/health,$H:8115/actuator/health,$H:8116/actuator/health,$H:8118/actuator/health;money=$H:8106/actuator/health,$H:8104/actuator/health,$H:8105/actuator/health,$H:8112/actuator/health,$H:8113/actuator/health,$H:8114/actuator/health,$H:8117/actuator/health;street=$H:8107/actuator/health,$H:8108/actuator/health,$H:8111/actuator/health,$H:8110/actuator/health"
export STATUS_FILE="$S/cells/status.json" ROUTES_FILE="$S/cells/routes.conf" CELLS_FILE="$S/cells/cells.json"
export STATE_FILE="$S/cells/state.json" LOG_FILE="$S/logs/cellwatch.log"
export FENCE_FILE="$S/journal/fenced" STANDBY_FENCE_FILE="$S/journal/fenced-b" JOURNAL_DIR="$S/journal" JOURNAL_ARCHIVE_DIR="$S/journal/archive"
export WEIGHTS="${CELL_WEIGHTS:-a=35,b=65}"
export PSQL_BASE="psql -v ON_ERROR_STOP=1 -q" PGDUMP_BASE="pg_dump" OWNER_PSQL="psql -U sprout -v ON_ERROR_STOP=1 -q"
export PEER_PG="host=127.0.0.1 port=15433 user=replicator sslmode=disable password=$CELL_B_REPLICATOR_PASSWORD"
export STANDBY_START="sh $S/ctl.sh start sprout-standby" STANDBY_STOP="sh $S/ctl.sh stop sprout-standby"
export OWN_GATEWAY=http://127.0.0.1:8100 STANDBY_GATEWAY=http://127.0.0.1:8200 STANDBY_CHECK=http://127.0.0.1:8200/api/marketdata/v1/market
export RELOAD_ROUTES="sh $S/web/run.sh reload"
# CELLWATCH_CMD runs something else in the same environment, e.g. a one-off: CELLWATCH_CMD='python3 -c "import cw_ops; cw_ops.rebuild_copy()"' sh run.sh
eval "exec ${CELLWATCH_CMD:-python3 \"$HERE/cellwatch.py\"}"
