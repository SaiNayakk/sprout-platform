#!/data/data/com.termux/files/usr/bin/sh
# The edge host on the phone (gateway + identity, and the sandbox when SPROUT_SANDBOX=true in ~/.sprout.env),
# started by Backseat as `sh run.sh`.
set -eu
set -a
. "$HOME/.sprout.env"
set +a

export IDENTITY_DB_URL="jdbc:postgresql://127.0.0.1:5432/sprout?currentSchema=identity"
export IDENTITY_DB_USER=sprout
export IDENTITY_DB_PASSWORD="$SPROUT_DB_PASSWORD"
export IDENTITY_SIGNING_KEY_PATH="$HOME/.sprout/keys/signing.pem"
export IDENTITY_BIND=127.0.0.1
export GATEWAY_BIND=127.0.0.1                 # only the Cloudflare tunnel reaches it
export GATEWAY_TRUST_CF_IP=true               # behind Cloudflare: the real client is CF-Connecting-IP
export GATEWAY_IDENTITY_URL=http://127.0.0.1:8101
export GATEWAY_JWKS_URL=http://127.0.0.1:8101/.well-known/jwks.json
export GATEWAY_MARKETDATA_URL=http://127.0.0.1:8103
export LOG_FORMAT=ecs
if [ -n "${CELL_KEY:-}" ]; then
  # cell A (ADR-027): customers' writes are journalled in cell B before they are forwarded; cell B's journal is kept here
  export GATEWAY_CELL_ID=a GATEWAY_CELL_PEER_URL=https://sprout-b-saiworks.nncs.in GATEWAY_CELL_KEY="$CELL_KEY"
  export GATEWAY_CELL_JOURNAL_DIR="$HOME/sprout/journal" GATEWAY_CELL_FENCE_FILE="$HOME/sprout/journal/fenced"
fi
if [ "${SPROUT_SANDBOX:-false}" = true ]; then
  # the public sandbox: fictional customers visitors explore as (the market runs fast: see trading/run.sh)
  export IDENTITY_DEMO_ENABLED=true
  export SANDBOX_DB_URL="jdbc:postgresql://127.0.0.1:5432/sprout?currentSchema=sandbox"
  export SANDBOX_DB_USER=sprout
  export SANDBOX_DB_PASSWORD="$SPROUT_DB_PASSWORD"
  export SANDBOX_BIND=127.0.0.1
  export SANDBOX_EVERY=5s              # the personas act at the pace the 30x market needs
fi

# JVM settings sized for the phone; SPROUT_EDGE_JAVA_OPTS in ~/.sprout.env overrides them (capacity experiments)
java ${SPROUT_EDGE_JAVA_OPTS:--XX:+UseSerialGC -Xms32m -Xmx160m -Xss512k -XX:MaxMetaspaceSize=192m -XX:ReservedCodeCacheSize=48m -XX:TieredStopAtLevel=1} \
  -jar edge-host.jar
