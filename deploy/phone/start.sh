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
PIECES="postgres nats trading street money edge web front pgpeer cellwatch"
# The cell's own pieces (ADR-027): the front-door connector (last, so visitors only come once everything answers), the
# replication client and cellwatch. If one of them fails, Sprout keeps running without it and it is tried again later.
OPTIONAL="front pgpeer cellwatch"
optional() { case " $OPTIONAL " in *" $1 "*) return 0 ;; esac; return 1; }
port_open() { python3 -c "import socket,sys; socket.create_connection(('127.0.0.1', int(sys.argv[1])), 2)" "$1" 2>/dev/null; }
fresh() { python3 -c "import os,sys,time; sys.exit(0 if time.time() - os.path.getmtime(sys.argv[1]) < 60 else 1)" "$1" 2>/dev/null; }
dir_of() { echo "$HERE/$1"; }
# A host is healthy only when every service in it answers: a host whose first service is up can still have
# one that failed to start (2026-10-08: the street host's bank answered while its depository's migration failed).
answers() { for p in "$@"; do curl -fs -m "${CHECK_SECONDS:-2}" -o /dev/null "http://127.0.0.1:$p/actuator/health" || return 1; done; }
sandbox_on() { grep -q '^SPROUT_SANDBOX=true' "$HOME/.sprout.env" 2>/dev/null; }
healthy() {
  case "$1" in
    postgres) pg_isready -q -h 127.0.0.1 -p 5432 ;;
    nats)     curl -fs -m 2 -o /dev/null http://127.0.0.1:8222/healthz ;;
    trading)  answers 8103 8109 8115 8116 8118 ;;                   # market data, orders, plans, habits, rewards
    street)   answers 8107 8108 8111 8110 ;;                        # bank, exchange, depository, clearing
    money)    answers 8106 8104 8105 8112 8113 8114 8117 ;;         # ledger, accounts, payments, settlement, statements, recon, goals
    edge)     answers 8101 && curl -fs -m 2 -o /dev/null http://127.0.0.1:8100/api/marketdata/v1/market                 && { ! sandbox_on || answers 8119; } ;;               # identity, the gateway (through it), the sandbox
    web)      curl -fs -m 2 -o /dev/null http://127.0.0.1:8180/healthz ;;
    front)    curl -fs -m 2 -o /dev/null http://127.0.0.1:8183/ready ;;   # connected to Cloudflare
    pgpeer)   port_open 15433 ;;
    cellwatch) fresh "$HOME/sprout/cells/status.json" ;;
  esac
}

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }
booted_for() { python3 -c 'import time; print(int(time.clock_gettime(time.CLOCK_BOOTTIME)))'; }
free_mb() { free -m | awk 'NR==2 {print $7}'; }

pid_file() { echo "$LOGS/$1.pid"; }
TICKS=$(getconf CLK_TCK 2>/dev/null || echo 100)
# CPU time (ticks) used so far by a piece's process and its children (run.sh starts the real process as a child)
cpu_ticks() {
  p=$(cat "$(pid_file "$1")" 2>/dev/null) || { echo 0; return; }
  t=0
  for c in $p $(pgrep -P "$p" 2>/dev/null); do
    s=$(awk '{print $14 + $15}' "/proc/$c/stat" 2>/dev/null) && t=$((t + s))
  done
  echo $t
}
running() { p=$(cat "$(pid_file "$1")" 2>/dev/null) && [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }

stop_pieces() {
  for name in cellwatch pgpeer front web edge money street trading nats postgres; do
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
  if ! start_piece "$name"; then
    optional "$name" && { log "$name didn't start; Sprout runs without it and it is tried again"; continue; }
    give_up "Sprout didn't start"
  fi
done
log "Sprout is up"

# 3. keep it up: more than five restarts within an hour means something is wrong; the odd one over days doesn't
restarts=0
last_restart=0
while :; do
  sleep 15 &
  wait $!
  for name in $PIECES; do
    if running "$name"; then
      # alive but not answering is as bad as dead (2026-10-08: the edge host hung with every thread stuck and its
      # process still up): eight failed checks in a row, about two minutes, and it is killed and started again. The
      # bar is deliberately low (5 s per check, two minutes): a host that is only busy must not be killed for it,
      # which would make an overload worse
      if CHECK_SECONDS=5 healthy "$name"; then
        eval "silent_$name=0"
        continue
      fi
      eval "n=\${silent_$name:-0}"; n=$((n + 1)); eval "silent_$name=$n"
      [ $n -eq 1 ] && eval "cpu_$name=$(cpu_ticks "$name")"
      [ $n -lt 8 ] && continue
      # busy is not hung (2026-10-09: an overloaded edge host answered too slowly, was killed, and the two minutes it
      # took to start made the overload an outage). A hung process (2026-10-08's every thread stuck) uses no CPU; a
      # busy one uses plenty. Killed only when it has used under 5 s of CPU in the two minutes it didn't answer
      eval "was=\$cpu_$name"; used=$(( $(cpu_ticks "$name") - was ))
      if [ "$used" -gt $((5 * TICKS)) ]; then
        log "$name answered nothing for two minutes but used $((used / TICKS))s of CPU: busy, not hung; left alone"
        eval "silent_$name=0"
        continue
      fi
      log "$name stopped answering for two minutes and used $((used / TICKS))s of CPU: hung; killing it"
      p=$(cat "$(pid_file "$name")" 2>/dev/null)
      pkill -KILL -P "$p" 2>/dev/null; kill -KILL "$p" 2>/dev/null
      eval "silent_$name=0"
    elif healthy "$name"; then
      continue   # answering, though not started here (an old app): leave it
    fi
    if optional "$name"; then
      # not one of Sprout's own services: started again at most every ten minutes, never counted, never fatal
      eval "next=\${retry_$name:-0}"
      [ "$(date +%s)" -lt "$next" ] && continue
      eval "retry_$name=$(( $(date +%s) + 600 ))"
      log "$name isn't running; starting it again"
      start_piece "$name" || log "$name didn't start; tried again in ten minutes"
      continue
    fi
    now=$(date +%s)
    [ $((now - last_restart)) -gt 3600 ] && restarts=0
    last_restart=$now
    restarts=$((restarts + 1))
    [ $restarts -gt 5 ] && give_up "pieces keep dying"
    log "$name stopped; starting it again (restart $restarts)"
    start_piece "$name" || give_up "couldn't restart $name"
  done
done
