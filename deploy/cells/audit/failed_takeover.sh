#!/usr/bin/env bash
# X6: the laptop wrongly decides the phone is lost, and the takeover fails at "start the standby" (the container is gone),
# AFTER it has already disabled the subscription. Then the phone becomes visible again. What state is the system left in?
cd /c/Users/sai34/Desktop/Projects/sprout/sprout-platform-cells/deploy/laptop
set -a; . data/.env; set +a
export MSYS_NO_PATHCONV=1
PSQL=(docker exec -i -e PGPASSWORD="$SPROUT_DB_PASSWORD" sprout-laptop-postgres-1 psql -U sprout -d sprout_a -At)
state() { curl -s -m 6 -H 'User-Agent: x6' "https://sprout-$1-saiworks.nncs.in/cells/status.json" | grep -o '"state": "[A-Z_]*"' | cut -d'"' -f4; }
t0=$(date +%s); log() { echo "+$(( $(date +%s) - t0 ))s $*"; }

docker rm -f sprout-laptop-standby-1 >/dev/null; log "standby container removed"
echo x > data/cells/partition; log "laptop made blind to the phone"
for i in $(seq 1 60); do
  if grep -q "taking cell a over failed" data/cells/cellwatch.log 2>/dev/null; then break; fi
  sleep 5
done
log "$(grep 'taking cell a over failed' data/cells/cellwatch.log | tail -1 | cut -c1-200)"
rm -f data/cells/partition; log "partition removed (the phone was healthy the whole time)"
sleep 60
log "states: A=$(state a) B=$(state b)"
log "subscription from_a enabled? $("${PSQL[@]}" -c "select subenabled from pg_subscription where subname='from_a'")"
log "laptop state.json: $(tr -d '\n ' < data/cells/state.json)"
