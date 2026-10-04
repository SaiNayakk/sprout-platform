#!/usr/bin/env bash
# The pre-prod gate. Creates a fresh environment from the pinned releases, tests it end to end,
# under load and under failure, writes the evidence, and destroys everything.
#
#   preprod/run.sh                 everything (as the release gate does)
#   preprod/run.sh --observability also start Grafana/Prometheus/Loki/Tempo and capture the dashboard
#   preprod/run.sh --keep          leave the environment running afterwards, to explore
#
# Exit code is non-zero if any stage fails. The environment is destroyed even then.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/preprod/docker-compose.yml")
OBS=false; KEEP=false
for a in "$@"; do
  case "$a" in
    --observability) OBS=true ;;
    --keep) KEEP=true ;;
    *) echo "unknown option $a"; exit 2 ;;
  esac
done

RUN_ID="$(date -u +%Y-%m-%d-%H%M)-preprod"
RUN_START=$(date +%s)
OUT="$ROOT/preprod/out"
RUN_DIR="$ROOT/docs/reliability/runs/$RUN_ID"
rm -rf "$OUT" && mkdir -p "$OUT/e2e" "$RUN_DIR"
status=0
log() { printf '\n\033[1m> %s\033[0m\n' "$*"; }
stage() { echo "$1=$2" >> "$OUT/stages.txt"; [ "$2" = pass ] || status=1; }

cleanup() {
  if [ "$KEEP" = true ]; then
    log "Leaving the environment running (--keep). Destroy it with: ${COMPOSE[*]} down -v"
  else
    log "Destroying the environment"
    "${COMPOSE[@]}" --profile observability --profile tools down -v --remove-orphans >/dev/null 2>&1
  fi
}
trap cleanup EXIT

log "Building the hosts from their release manifests"
"$ROOT/hosts/install-services.sh" || { echo "building the services at their release tags failed"; exit 1; }
for host in edge trading; do
  (cd "$ROOT/hosts/$host" && mvn -q -B -DskipTests package) || { echo "$host host build failed"; exit 1; }
done

log "Creating a fresh environment"
"${COMPOSE[@]}" --profile observability --profile tools down -v --remove-orphans >/dev/null 2>&1
profiles=(); [ "$OBS" = true ] && profiles=(--profile observability)
export OTEL_ENABLED=$OBS
t0=$(date +%s)
if "${COMPOSE[@]}" "${profiles[@]}" up -d --build --wait; then
  echo "healthy after $(( $(date +%s) - t0 ))s"; stage environment pass
  if [ "$OBS" = true ]; then
    curl -s -o /dev/null -X POST -H 'Content-Type: application/json' http://localhost:3000/api/dashboards/db \
      --data-binary @"$ROOT/preprod/grafana/sprout-edge.json" \
      && echo "Dashboard: http://localhost:3000/d/sprout-edge"
  fi
else
  "${COMPOSE[@]}" logs edge trading | tail -80; stage environment fail; exit 1
fi

log "End-to-end suite"
if (cd "$ROOT/e2e" && mvn -q -B test -Dsprout.baseUrl=http://localhost:8100); then stage e2e pass; else stage e2e fail; fi
cp "$ROOT"/e2e/target/surefire-reports/TEST-*.xml "$OUT/e2e/" 2>/dev/null

# memory and CPU of the hosts every 5 s while under load
( while sleep 5; do docker stats --no-stream --format '{{.Name}} {{.MemUsage}} {{.CPUPerc}}' | grep -E "edge|trading"; done ) > "$OUT/memory-during.txt" &
sampler=$!

log "PERF-01: sign-in throughput"
if "${COMPOSE[@]}" --profile tools run --rm k6 run perf-01-signin.js; then stage perf-01 pass; else stage perf-01 fail; fi

log "PERF-03: price fan-out"
if "${COMPOSE[@]}" --profile tools run --rm loadgen -Dgroups=perf -De2e.excludedGroups= ; then stage perf-03 pass; else stage perf-03 fail; fi
kill $sampler 2>/dev/null

log "Chaos experiments"
python "$ROOT/preprod/chaos.py" "$OUT" || status=1

log "Collecting evidence"
"${COMPOSE[@]}" logs --no-color edge > "$OUT/edge.log" 2>&1
"${COMPOSE[@]}" logs --no-color trading > "$OUT/trading.log" 2>&1
if [ "$OBS" = true ]; then
  sleep 20   # let the last metrics export land
  for q in 'sum by (result) (identity_signins_total)' \
           'sum by (status) (http_server_requests_milliseconds_count{job="sprout-gateway"})' \
           'sum by (type) (md_stream_events_total)' 'sum(md_stream_conflated_total)' \
           'sum by (result) (md_nats_ticks_total)' 'sum(hikaricp_connections_timeout_total)'; do
    curl -s -G 'http://localhost:3000/api/datasources/proxy/uid/prometheus/api/v1/query' --data-urlencode "query=$q" >> "$OUT/metrics.jsonl" 2>/dev/null; echo >> "$OUT/metrics.jsonl"
  done
  chrome=""
  for c in google-chrome chromium chromium-browser "/c/Program Files/Google/Chrome/Application/chrome.exe" \
           "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; do
    command -v "$c" >/dev/null 2>&1 && { chrome="$c"; break; }
  done
  if [ -n "$chrome" ]; then
    shot="$OUT/grafana-edge.png"; command -v cygpath >/dev/null && shot="$(cygpath -w "$shot")"
    "$chrome" --headless=new --disable-gpu --hide-scrollbars --window-size=1600,1900 --virtual-time-budget=20000 \
      --screenshot="$shot" "http://localhost:3000/d/sprout-edge?orgId=1&from=$(( RUN_START * 1000 ))&to=now&kiosk&theme=dark" \
      >/dev/null 2>&1 && echo "Dashboard captured"
  fi
fi
python "$ROOT/preprod/report.py" "$OUT" "$RUN_DIR" "$RUN_ID" "$ROOT/hosts"
echo "Evidence: $RUN_DIR"

exit $status
