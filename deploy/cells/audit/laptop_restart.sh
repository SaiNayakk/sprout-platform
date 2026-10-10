#!/usr/bin/env bash
# X13: a laptop "reboot": every cell B container stops together, stays down for $1 seconds, then all start at the same instant
# (Docker's restart policy does that after Docker Desktop starts: no start order). How long until cell B is healthy, and does
# the phone take it over meanwhile?
DOWN="${1:-30}"
cd /c/Users/sai34/Desktop/Projects/sprout/sprout-platform-cells/deploy/laptop
export MSYS_NO_PATHCONV=1
SSH=(ssh -i "$HOME/.ssh/backseat_phone" -p 8022 -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=10 u0_a1@192.168.0.6)
state() { curl -s -m 6 -H 'User-Agent: x13' "https://sprout-$1-saiworks.nncs.in/cells/status.json" | grep -o '"state": "[A-Z_]*"' | cut -d'"' -f4; }
t0=$(date +%s); log() { echo "+$(( $(date +%s) - t0 ))s $*"; }
ALL=$(docker ps -a --format '{{.Names}}' | grep '^sprout-laptop-' | grep -v standby | tr '\n' ' ')
log "stopping: $(echo $ALL | wc -w) containers"
docker stop $ALL >/dev/null 2>&1
log "all stopped"
sleep "$DOWN"
docker start $ALL >/dev/null 2>&1
log "all started at once"
healthy_at=""; prev=""
for i in $(seq 1 120); do
  sleep 5
  cur="A=$(state a) B=$(state b)"
  [ "$cur" != "$prev" ] && log "$cur"; prev="$cur"
  if [ -z "$healthy_at" ] && curl -s -m 5 -o /dev/null -w '%{http_code}' https://sprout-b-saiworks.nncs.in/api/marketdata/v1/market 2>/dev/null | grep -q 200; then healthy_at=$(( $(date +%s) - t0 )); log "cell B answers customers again"; fi
  case "$cur" in *B=NORMAL*) [ $i -gt 30 ] && break;; esac
done
log "end: A=$(state a) B=$(state b)"
log "phone cellwatch: $("${SSH[@]}" 'uniq ~/sprout/logs/cellwatch.log | tail -3 | cut -c1-110' | tr '\n' '|')"
log "laptop cellwatch: $(tail -n 3 data/cells/cellwatch.log | cut -c1-110 | tr '\n' '|')"
