#!/usr/bin/env bash
# After both cells have taken each other over (a test): stop both standbys, drop both copies and both subscriptions,
# reset both cellwatch states, and let replicate.sh build the copies again. Each cell's own database is kept as it is.
set -uo pipefail
cd /c/Users/sai34/Desktop/Projects/sprout/sprout-platform-cells/deploy/laptop
set -a; . data/.env; set +a
export MSYS_NO_PATHCONV=1
SSH=(ssh -i "$HOME/.ssh/backseat_phone" -p 8022 -o BatchMode=yes -o IdentitiesOnly=yes u0_a1@192.168.0.6)
LPG=(docker exec -i -e PGPASSWORD="$SPROUT_DB_PASSWORD" sprout-laptop-postgres-1 psql -U sprout -q)
COMPOSE=(docker compose --env-file data/.env -f docker-compose.yml)
export SPROUT_WEB_IMAGE="sprout-web:$(tr -d '[:space:]' < web.version)"

echo "> stop both standbys and both cellwatch"
"${COMPOSE[@]}" --profile standby stop standby cellwatch >/dev/null
"${SSH[@]}" "sh ~/sprout/ctl.sh stop sprout-standby >/dev/null; pkill -f '[c]ellwatch[.]py'; true"
echo "> drop the laptop's copy of A and the phone's copy of B"
"${LPG[@]}" -d sprout_a -c "ALTER SUBSCRIPTION from_a DISABLE" -c "ALTER SUBSCRIPTION from_a SET (slot_name = NONE)" -c "DROP SUBSCRIPTION from_a" || true
"${LPG[@]}" -d sprout -c "DROP DATABASE IF EXISTS sprout_a" -c "SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots WHERE slot_name = 'from_b'" || true
"${SSH[@]}" "psql -d sprout_b -q -c 'ALTER SUBSCRIPTION from_b DISABLE' -c 'ALTER SUBSCRIPTION from_b SET (slot_name = NONE)' -c 'DROP SUBSCRIPTION from_b'; psql -d postgres -q -c 'DROP DATABASE IF EXISTS sprout_b'; psql -d sprout -At -c \"SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots WHERE slot_name = 'from_a'\"; true"
echo "> reset states, fences and the partition flags"
rm -f data/cells/state.json data/cells/partition data/journal/fenced data/journal/fenced-a
"${SSH[@]}" "rm -f ~/sprout/cells/state.json ~/sprout/cells/partition ~/sprout/journal/fenced ~/sprout/journal/fenced-b"
"${COMPOSE[@]}" up -d cellwatch >/dev/null
echo "> the phone's starter starts its cellwatch again; then replicate"
sleep 60
cd ..
bash cells/replicate.sh 2>&1 | tail -3
