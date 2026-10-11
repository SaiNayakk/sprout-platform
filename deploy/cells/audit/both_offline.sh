#!/usr/bin/env bash
# X4: both cells' addresses go silent at the same time (the home internet drops), for $1 seconds, then come back.
# Logs both cells' published state every 5 s, as seen from outside, and what each cellwatch decided.
OUT="${2:-/dev/stdout}"
DUR="${1:-180}"
SSH=(ssh -i "$HOME/.ssh/backseat_phone" -p 8022 -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=10 u0_a1@192.168.0.6)
state() { curl -s -m 6 -H 'User-Agent: x4' "https://sprout-$1-saiworks.nncs.in/cells/status.json" | grep -o '"state": "[A-Z_]*"' | cut -d'"' -f4; }
t0=$(date +%s)
log() { echo "+$(( $(date +%s) - t0 ))s $*" >> "$OUT"; }
log "start: A=$(state a) B=$(state b)"
"${SSH[@]}" "pkill -STOP -f '^nginx: '" ; docker pause sprout-laptop-web-1 >/dev/null
log "both addresses silenced"
prev=""
end=$(( t0 + DUR ))
while [ "$(date +%s)" -lt "$end" ]; do sleep 5; done
"${SSH[@]}" "pkill -CONT -f '^nginx: '"; docker unpause sprout-laptop-web-1 >/dev/null
log "both addresses back"
end=$(( $(date +%s) + 420 ))
while [ "$(date +%s)" -lt "$end" ]; do
  cur="A=$(state a) B=$(state b)"
  [ "$cur" != "$prev" ] && log "$cur"
  prev="$cur"
  sleep 5
done
log "end: A=$(state a) B=$(state b)"
log "laptop cellwatch: $(tail -n 4 /c/Users/sai34/Desktop/Projects/sprout/sprout-platform-cells/deploy/laptop/data/cells/cellwatch.log | cut -c1-120 | tr '\n' '|')"
log "phone cellwatch: $("${SSH[@]}" 'uniq ~/sprout/logs/cellwatch.log | tail -4 | cut -c1-120' | tr '\n' '|')"
echo DONE >> "$OUT"
