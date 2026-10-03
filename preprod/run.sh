#!/usr/bin/env bash
# The pre-prod gate. Creates a fresh environment from the pinned release, tests it end to end,
# under load and under failure, writes the evidence, and destroys everything.
#
#   preprod/run.sh                 everything (as the release gate does)
#   preprod/run.sh --observability also start Grafana/Prometheus/Loki/Tempo and keep metrics
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
log() { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }
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

log "Building the edge host from its release manifest"
(cd "$ROOT/hosts/edge" && mvn -q -B -DskipTests package) || { echo "host build failed"; exit 1; }

log "Creating a fresh environment"
"${COMPOSE[@]}" --profile observability --profile tools down -v --remove-orphans >/dev/null 2>&1
profiles=(); [ "$OBS" = true ] && profiles=(--profile observability)
export OTEL_ENABLED=$OBS
t0=$(date +%s)
if "${COMPOSE[@]}" "${profiles[@]}" up -d --build --wait; then
  echo "healthy after $(( $(date +%s) - t0 ))s"; stage environment pass
  if [ "$OBS" = true ]; then
    curl -s -o /dev/null -X POST -H 'Content-Type: application/json' http://localhost:3000/api/dashboards/db       --data-binary @"$ROOT/preprod/grafana/sprout-edge.json"       && echo "Dashboard: http://localhost:3000/d/sprout-edge"
  fi
else
  "${COMPOSE[@]}" logs edge | tail -50; stage environment fail; exit 1
fi

log "End-to-end suite"
if (cd "$ROOT/e2e" && mvn -q -B test -Dsprout.baseUrl=http://localhost:8100); then stage e2e pass; else stage e2e fail; fi
cp "$ROOT"/e2e/target/surefire-reports/TEST-*.xml "$OUT/e2e/" 2>/dev/null

log "PERF-01: sign-in throughput"
docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' > "$OUT/memory-before.txt"
( while sleep 5; do docker stats --no-stream --format '{{.Name}} {{.MemUsage}} {{.CPUPerc}}' | grep edge; done ) > "$OUT/memory-during.txt" &
sampler=$!
if "${COMPOSE[@]}" --profile tools run --rm k6 run perf-01-signin.js; then stage perf-01 pass; else stage perf-01 fail; fi
kill $sampler 2>/dev/null

log "CHAOS-01: the database goes away"
B=http://localhost:8100/api/identity
probe() {
  curl -s -o /dev/null -D "$OUT/h.txt" -w '%{http_code} %{time_total}' -X POST "$B/v1/sessions" \
    -H 'Content-Type: application/json' -H "CF-Connecting-IP: 198.19.$1" \
    -d '{"email":"nobody@example.com","password":"whatever-password"}'
}
before=$(probe 0.1)
"${COMPOSE[@]}" stop postgres >/dev/null 2>&1
down1=$(probe 0.2); down2=$(probe 0.3); down3=$(probe 0.4)
retry=$(grep -i '^retry-after' "$OUT/h.txt" | tr -d '\r' | awk '{print $2}')
"${COMPOSE[@]}" start postgres >/dev/null 2>&1
t0=$(date +%s); recovered=-1
for i in $(seq 1 60); do
  code=$(probe 0.$((10 + i)) | cut -d' ' -f1)
  [ "$code" = 401 ] && { recovered=$(( $(date +%s) - t0 )); break; }
  sleep 1
done
edge_restarts=$(docker inspect -f '{{.RestartCount}}' sprout-preprod-edge-1 2>/dev/null || echo "?")
cat > "$OUT/chaos-01.json" <<EOF
{"before": "$before", "down": ["$down1", "$down2", "$down3"], "retryAfter": "${retry:-none}",
 "recoveredAfterSeconds": $recovered, "edgeRestarts": "$edge_restarts"}
EOF
cat "$OUT/chaos-01.json"
ok=true
for d in "$down1" "$down2" "$down3"; do
  c=${d%% *}; t=${d##* }
  [ "$c" = 503 ] || ok=false
  python -c "import sys; sys.exit(0 if float('$t') < 3.0 else 1)" || ok=false
done
[ "${retry:-}" != "" ] || ok=false
[ "$recovered" -ge 0 ] && [ "$recovered" -le 30 ] || ok=false
if [ "$ok" = true ]; then stage chaos-01 pass; else stage chaos-01 fail; fi

log "Collecting evidence"
"${COMPOSE[@]}" logs --no-color edge > "$OUT/edge.log" 2>&1
if [ "$OBS" = true ]; then
  sleep 20   # let the last metrics export land
  chrome=""
  for c in google-chrome chromium chromium-browser "/c/Program Files/Google/Chrome/Application/chrome.exe"            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; do
    command -v "$c" >/dev/null 2>&1 && { chrome="$c"; break; }
  done
  if [ -n "$chrome" ]; then
    shot="$OUT/grafana-edge.png"; command -v cygpath >/dev/null && shot="$(cygpath -w "$shot")"
    "$chrome" --headless=new --disable-gpu --hide-scrollbars --window-size=1600,1000 --virtual-time-budget=20000       --screenshot="$shot" "http://localhost:3000/d/sprout-edge?orgId=1&from=$(( RUN_START * 1000 ))&to=now&kiosk&theme=dark"       >/dev/null 2>&1 && echo "Dashboard captured"
  fi
  for q in 'sum by (result) (identity_signins_total)' 'sum by (result) (identity_signups_total)'            'sum by (status) (http_server_requests_milliseconds_count{uri!~"/actuator.*"})'            'sum(hikaricp_connections_timeout_total)' 'max_over_time(sum(jvm_memory_used_bytes)[30m:15s])'; do
    curl -s -G 'http://localhost:3000/api/datasources/proxy/uid/prometheus/api/v1/query' --data-urlencode "query=$q" >> "$OUT/metrics.jsonl" 2>/dev/null; echo >> "$OUT/metrics.jsonl"
  done
fi
python "$ROOT/preprod/report.py" "$OUT" "$RUN_DIR" "$RUN_ID" "$ROOT/hosts/edge/pom.xml"
echo "Evidence: $RUN_DIR"

exit $status
