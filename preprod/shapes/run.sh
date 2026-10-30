#!/usr/bin/env bash
# The deployment shapes experiment (docs/architecture/shapes.md): the same services, at the same releases, packed
# as four hosts, one JVM and one JVM per service, each put through the same measurements on the same machine.
#
#   preprod/shapes/run.sh [shape...]     default: four-hosts one-jvm per-service
#
# For each shape: start it from nothing and time it to healthy, let it settle and record its memory, put it through
# an order-load ladder (PERF-04 at rising rates) while sampling memory and CPU, kill the process that runs the ledger
# and count which services still answer, time its recovery, then destroy it. Results go to preprod/shapes/results/.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$ROOT/preprod/shapes"
PYHERE="$(cygpath -m "$HERE" 2>/dev/null || echo "$HERE")"   # Python on Windows needs a Windows path
SHAPES=("$@"); [ ${#SHAPES[@]} -eq 0 ] && SHAPES=(four-hosts one-jvm per-service)
RATES=(${RATES:-5 10 20 40 80})
SECONDS_PER_RATE=${SECONDS_PER_RATE:-60}
STAMP="$(date -u +%Y-%m-%d-%H%M)"
RESULTS="$HERE/results/$STAMP"
mkdir -p "$RESULTS" "$ROOT/preprod/out/keys" && chmod 777 "$ROOT/preprod/out"
[ -f "$ROOT/preprod/out/keys/signing.pem" ] || { java "$ROOT/deploy/phone/KeyGen.java" "$ROOT/preprod/out/keys/signing.pem" && chmod 644 "$ROOT/preprod/out/keys/signing.pem"; }

log() { printf '\n\033[1m> %s\033[0m\n' "$*"; }
now_ms() { python -c 'import time; print(int(time.time()*1000))'; }

# Where each service answers in a shape: the container (or alias) and its health port.
address() {   # shape service -> host:port
  local shape=$1 svc=$2 port
  port=$(python -c "import sys; sys.path.insert(0, '$PYHERE'); import render as r; print(r.HEALTH.get('$svc', r.PORTS_BY_NAME['$svc']))")
  case $shape in
    per-service) echo "$svc:$port" ;;
    one-jvm) echo "cell:$port" ;;
    four-hosts) echo "$(python -c "import sys; sys.path.insert(0, '$PYHERE'); import render as r; print(r.HOST_OF['$svc'])"):$port" ;;
  esac
}
SERVICES=$(python -c "import sys; sys.path.insert(0, '$PYHERE'); import render as r; print(' '.join(r.PORTS_BY_NAME))")

answering() {   # shape -> how many services answer their health check, probed from the database's container
  local shape=$1 n=0 c
  for s in $SERVICES; do
    "${C[@]}" exec -T postgres wget -q -T 2 -O /dev/null "http://$(address "$shape" "$s")/actuator/health" 2>/dev/null && n=$((n+1))
  done
  echo $n
}

sample() {   # shape phase -> appends one docker stats sample per container to stats.csv, until stopped
  while true; do
    docker stats --no-stream --format "{{.Name}},{{.MemUsage}},{{.CPUPerc}}" \
      | grep "sprout-shape-$1" | sed "s/^/$(date +%s),$2,/" >> "$RESULTS/$1/stats.csv"
  done
}

log "Building the host jars"
for host in edge trading money street cell; do
  (cd "$ROOT/hosts/$host" && mvn -q -B -o -DskipTests package) || { echo "$host host build failed"; exit 1; }
done
python "$HERE/render.py"

for shape in "${SHAPES[@]}"; do
  C=(docker compose -f "$HERE/out/$shape.yml")
  mkdir -p "$RESULTS/$shape"
  out="$RESULTS/$shape"
  PYOUT="$(cygpath -m "$out" 2>/dev/null || echo "$out")"
  "${C[@]}" --profile tools down -v --remove-orphans >/dev/null 2>&1
  "${C[@]}" build -q || { echo "$shape: build failed"; continue; }

  log "$shape: start from nothing"
  t0=$(now_ms)
  if ! "${C[@]}" up -d --wait >/dev/null 2>"$out/up.err"; then
    echo "$shape did not become healthy"; "${C[@]}" logs --tail 80 > "$out/up.log" 2>&1
    "${C[@]}" --profile tools down -v --remove-orphans >/dev/null 2>&1; continue
  fi
  echo "{\"healthyAfterMs\": $(( $(now_ms) - t0 ))}" > "$out/start.json"; cat "$out/start.json"

  log "$shape: settle 60 s, then idle memory"
  sleep 60
  sample "$shape" idle & sp=$!; sleep 20; kill $sp 2>/dev/null; wait $sp 2>/dev/null

  log "$shape: warm up (PERF-04 at 2/s for 30 s, not recorded)"
  "${C[@]}" --profile tools run --rm -e PERF04_OUT=/out/warm.json loadgen -Dgroups=perf-orders -De2e.excludedGroups= \
    -Dperf.rate=2 -Dperf.seconds=30 >/dev/null 2>&1

  for rate in "${RATES[@]}"; do
    log "$shape: orders at $rate/s for ${SECONDS_PER_RATE}s"
    sample "$shape" "load-$rate" & sp=$!
    "${C[@]}" --profile tools run --rm -e PERF04_OUT=/out/perf-04-$shape-$rate.json loadgen -Dgroups=perf-orders \
      -De2e.excludedGroups= -Dperf.rate="$rate" -Dperf.seconds="$SECONDS_PER_RATE" -Dperf.customers="${CUSTOMERS:-40}" > "$out/load-$rate.log" 2>&1
    kill $sp 2>/dev/null; wait $sp 2>/dev/null
    cp "$ROOT/preprod/out/perf-04-$shape-$rate.json" "$out/load-$rate.json" 2>/dev/null \
      && python -c "import json; d=json.load(open(r'$PYOUT/load-$rate.json')); print({k: d.get(k) for k in ('orders','p50Ms','p95Ms','p99Ms','outcomes')})"
  done

  log "$shape: kill what runs the ledger"
  case $shape in per-service) victim=ledger ;; one-jvm) victim=cell ;; four-hosts) victim=money ;; esac
  total=$(echo $SERVICES | wc -w)
  "${C[@]}" kill -s KILL "$victim" >/dev/null 2>&1
  up=$(answering "$shape")
  t0=$(now_ms)
  "${C[@]}" up -d --wait "$victim" >/dev/null 2>&1
  echo "{\"killed\": \"$victim\", \"services\": $total, \"answeringWhileDown\": $up, \"recoveredAfterMs\": $(( $(now_ms) - t0 ))}" \
    | tee "$out/blast.json"

  "${C[@]}" --profile tools down -v --remove-orphans >/dev/null 2>&1
done
log "Results in $RESULTS"
