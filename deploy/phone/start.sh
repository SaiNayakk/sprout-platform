#!/data/data/com.termux/files/usr/bin/sh
# Starts Sprout on the phone one piece at a time, and keeps it running. Backseat runs this as ONE app,
# `sprout` (`sh start.sh` in ~/sprout); stopping that app stops all of Sprout, because everything started
# here is in its process group.
#
# Why staged: at boot Backseat starts every app at once. Postgres, NATS and four JVMs warming up on top of
# the phone's own boot made Android reboot, and then reboot again (2026-10-08). So this script:
#   1. waits until the phone has been up a while (SPROUT_SETTLE_SECONDS, default 5 minutes)
#   2. starts one piece, waits until it answers its health check, then lets it settle before the next
#   3. starts nothing while memory is short (SPROUT_MIN_FREE_MB, default 600 MB available)
#   4. runs everything at a lower priority than the phone's own work, with fewer JVM threads
#   5. restarts a piece that dies, after the same checks, and gives up (letting Backseat retry the whole
#      thing later) if pieces keep dying
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
LOGS="$HERE/logs"
SETTLE=${SPROUT_SETTLE_SECONDS:-300}
MIN_FREE_MB=${SPROUT_MIN_FREE_MB:-600}
GAP=${SPROUT_START_GAP_SECONDS:-20}       # after each piece is healthy, before the next
export JAVA_TOOL_OPTIONS="-XX:ActiveProcessorCount=2"   # fewer compiler and GC threads per JVM
mkdir -p "$LOGS"

# name, folder, health check: started in this order, stopped in the reverse
PIECES="postgres nats trading street money edge web"
dir_of() { echo "$HERE/$1"; }
healthy() {
  case "$1" in
    postgres) pg_isready -q -h 127.0.0.1 -p 5432 ;;
    nats)     curl -fs -m 2 -o /dev/null http://127.0.0.1:8222/healthz ;;
    trading)  curl -fs -m 2 -o /dev/null http://127.0.0.1:8103/actuator/health ;;
    street)   curl -fs -m 2 -o /dev/null http://127.0.0.1:8107/actuator/health ;;
    money)    curl -fs -m 2 -o /dev/null http://127.0.0.1:8104/actuator/health ;;
    edge)     curl -fs -m 2 -o /dev/null http://127.0.0.1:8101/actuator/health ;;
    web)      curl -fs -m 2 -o /dev/null http://127.0.0.1:8180/healthz ;;
  esac
}

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }
booted_for() { python3 -c 'import time; print(int(time.clock_gettime(time.CLOCK_BOOTTIME)))'; }
free_mb() { free -m | awk 'NR==2 {print $7}'; }

pid_file() { echo "$LOGS/$1.pid"; }
running() { p=$(cat "$(pid_file "$1")" 2>/dev/null) && [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }

stop_pieces() {
  for name in web edge money street trading nats postgres; do
    p=$(cat "$(pid_file "$name")" 2>/dev/null) || continue
    # the piece's own children too (run.sh starts the real process without exec)
    pkill -TERM -P "$p" 2>/dev/null; kill -TERM "$p" 2>/dev/null
  done
  sleep 3   # Backseat sends SIGKILL to anything left after 5 seconds
  rm -f "$LOGS"/*.pid
}
stop_all() { log "stopping Sprout"; stop_pieces; exit 0; }
# something is wrong: stop, wait ten minutes, and exit, so Backseat starts this again later (not in a tight loop)
give_up() { log "$1; stopping, trying again in 10 minutes"; stop_pieces; sleep 600 & wait $!; exit 1; }
trap stop_all TERM INT

wait_for_memory() {
  i=0
  while [ "$(free_mb)" -lt "$MIN_FREE_MB" ]; do
    [ $((i % 12)) -eq 0 ] && log "waiting for memory before $1: $(free_mb) MB available, want $MIN_FREE_MB"
    i=$((i + 1)); sleep 5
  done
}

start_piece() {
  wait_for_memory "$1"
  f="$LOGS/$1.log"
  [ -f "$f" ] && [ "$(wc -c < "$f")" -gt 10485760 ] && mv -f "$f" "$f.1"   # keep logs to 10 MB each
  (cd "$(dir_of "$1")" && exec nice -n 10 sh run.sh >> "$f" 2>&1) &
  echo $! > "$(pid_file "$1")"
  i=0
  until healthy "$1"; do
    if ! running "$1"; then log "$1 exited while starting (see logs/$1.log)"; return 1; fi
    i=$((i + 1))
    [ $i -gt 90 ] && { log "$1 not healthy after 3 minutes"; return 1; }
    sleep 2
  done
  log "$1 up after $((i * 2))s, $(free_mb) MB available"
  sleep "$GAP"
}

# 1. let the phone finish booting
up=$(booted_for)
if [ "$up" -lt "$SETTLE" ]; then
  log "phone up for ${up}s: waiting $((SETTLE - up))s more before starting Sprout"
  sleep $((SETTLE - up)) & wait $!
fi

# 2. one piece at a time
for name in $PIECES; do
  if healthy "$name"; then log "$name already answering; not starting another"; continue; fi
  start_piece "$name" || give_up "Sprout didn't start"
done
log "Sprout is up"

# 3. keep it up
restarts=0
while :; do
  sleep 15 &
  wait $!
  for name in $PIECES; do
    running "$name" && continue
    healthy "$name" && continue   # answering, though not started here (an old app): leave it
    restarts=$((restarts + 1))
    [ $restarts -gt 5 ] && give_up "pieces keep dying"
    log "$name stopped; starting it again (restart $restarts)"
    start_piece "$name" || give_up "couldn't restart $name"
  done
done
