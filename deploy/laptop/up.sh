#!/usr/bin/env bash
# Runs Sprout on this machine, behind a Cloudflare tunnel, for as long as it is left on. Safe to run again.
#
#   deploy/laptop/up.sh              build, start (or update) everything
#   deploy/laptop/up.sh --local      the same without the tunnel: http://localhost:18080 on this machine only
#   deploy/laptop/up.sh --no-build   start without building the services again (their images exist)
#   deploy/laptop/up.sh --down       stop everything (the data is kept)
#
# What it keeps in deploy/laptop/data/ (never committed): the secrets, the token signing key, the tunnel's
# credentials, and the market's start. Delete the Docker volume sprout-laptop_pgdata to start the data afresh.
#
# It runs as cell B (ADR-027). The cells' shared secrets come from SPROUT_CELLS_SECRETS (a file kept outside the repo,
# default F:/Projects/sprout/cells-secrets/cells.env); cell A's own keys for the standby are fetched from the phone by
# deploy/cells/exchange-secrets.sh, and replication is set up by deploy/cells/replicate.sh.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$HERE"

LOCAL=false
BUILD=true
for a in "$@"; do
  case "$a" in
    --local) LOCAL=true ;;
    --no-build) BUILD=false ;;   # the hosts' images already exist: don't build the services again
    --down) docker compose --env-file data/.env -f docker-compose.yml down; exit 0 ;;
    *) echo "unknown option $a"; exit 2 ;;
  esac
done

CLOUDFLARED="$(command -v cloudflared || true)"
[ -n "$CLOUDFLARED" ] || CLOUDFLARED="/c/Program Files (x86)/cloudflared/cloudflared"

echo "> Secrets, signing key and the compose file"
mkdir -p data
CELLS_SECRETS="${SPROUT_CELLS_SECRETS:-/f/Projects/sprout/cells-secrets/cells.env}"
[ -f "$CELLS_SECRETS" ] || { echo "no cells secrets file at $CELLS_SECRETS"; exit 1; }
touch data/.env
for k in CELL_KEY CELL_A_REPLICATOR_PASSWORD CELL_B_REPLICATOR_PASSWORD; do
  grep -q "^$k=" data/.env || grep "^$k=" "$CELLS_SECRETS" >> data/.env
done
# new customers are split between the cells by what each carries (measured: see the capacity docs)
grep -q '^CELL_WEIGHTS=' data/.env || echo 'CELL_WEIGHTS=a=30,b=70' >> data/.env
python render.py
mkdir -p data/keys data/cloudflared data/cloudflared-front data/cells data/journal data/cell-a/keys
chmod 777 data/journal       # the gateway runs as its own user inside its container
# the web server needs a routes file before cellwatch has written one: until then, every cell's customers are local or
# forwarded as normal
if [ ! -f data/cells/routes.conf ]; then
  printf 'map $http_x_sprout_cell $sprout_route {\n    default local;\n    b local;\n    a peer;\n}\n' > data/cells/routes.conf
  echo '{"cells":[{"id":"a","weight":30},{"id":"b","weight":70}]}' > data/cells/cells.json
fi
[ -f data/cell-a/cell-a.env ] || : > data/cell-a/cell-a.env
if [ ! -f data/keys/signing.pem ]; then
  java "$ROOT/deploy/phone/KeyGen.java" data/keys/signing.pem
  chmod 644 data/keys/signing.pem    # the services run as a user of their own inside their containers
fi
set -a; . data/.env; set +a

if [ "$BUILD" = true ]; then
  echo "> Building the hosts from their release manifests"
  "$ROOT/hosts/install-services.sh"
  for host in edge trading money street cell; do
    (cd "$ROOT/hosts/$host" && mvn -q -B -DskipTests package)
  done
fi

if [ "$LOCAL" = false ]; then
  echo "> The tunnel to $SPROUT_HOSTNAME"
  # The tunnel is found by its exact name. (Never `tunnel info NAME`: for a name it doesn't know it quietly answers
  # about the default tunnel in ~/.cloudflared/config.yml, which belongs to something else entirely.)
  find_tunnel() {
    "$CLOUDFLARED" tunnel list --name "$1" --output json 2>/dev/null |
      python -c "import sys,json; t=[x for x in json.load(sys.stdin) if x['name']=='$1']; print(t[0]['id'] if t else '')"
  }
  id="$(find_tunnel sprout-laptop)"
  if [ -z "$id" ]; then
    "$CLOUDFLARED" tunnel create sprout-laptop >/dev/null
    id="$(find_tunnel sprout-laptop)"
  fi
  [ -n "$id" ] || { echo "couldn't create or find the tunnel sprout-laptop"; exit 1; }
  [ -f "$HOME/.cloudflared/$id.json" ] || { echo "no credentials for tunnel $id in ~/.cloudflared"; exit 1; }
  cp "$HOME/.cloudflared/$id.json" data/cloudflared/creds.json
  # this cell's own address, and its database's for cell A's replication client (a Postgres login, password only)
  cat > data/cloudflared/config.yml <<EOF
tunnel: $id
credentials-file: /etc/cloudflared/creds.json
ingress:
  - hostname: sprout-b-saiworks.nncs.in
    service: http://web:80
  - hostname: pg-b-saiworks.nncs.in
    service: tcp://postgres:5432
  - service: http_status:404
EOF
  # the front door both cells share: a connector here, one in cell A
  front="$(find_tunnel sprout-front)"
  [ -n "$front" ] && [ -f "$HOME/.cloudflared/$front.json" ] || { echo "no tunnel sprout-front (or its credentials)"; exit 1; }
  cp "$HOME/.cloudflared/$front.json" data/cloudflared-front/creds.json
  cat > data/cloudflared-front/config.yml <<EOF
tunnel: $front
credentials-file: /etc/cloudflared/creds.json
ingress:
  - hostname: $SPROUT_HOSTNAME
    service: http://web:80
  - service: http_status:404
EOF
fi

echo "> The web app"
# `docker build` takes a git address; docker compose can't on Windows, so the image is built here and compose just runs it
if [ -n "${SPROUT_WEB_SRC:-}" ]; then
  export SPROUT_WEB_IMAGE=sprout-web:dev          # a local checkout, while developing
  docker build -q -t "$SPROUT_WEB_IMAGE" "$SPROUT_WEB_SRC" >/dev/null
else
  WEB_VERSION="$(tr -d '[:space:]' < web.version)"   # the release this platform release pins
  export SPROUT_WEB_IMAGE="sprout-web:$WEB_VERSION"
  docker build -q -t "$SPROUT_WEB_IMAGE" "https://github.com/SaiNayakk/sprout-web.git#$WEB_VERSION" >/dev/null
fi

echo "> Starting"
SERVICES=(postgres nats edge trading money street web cellwatch pgpeer)
[ "$LOCAL" = true ] || SERVICES+=(cloudflared front)
if [ "$BUILD" = true ]; then
  docker compose --env-file data/.env -f docker-compose.yml up -d --build --wait "${SERVICES[@]}"
  # cell A's standby: built and created now, started only by cellwatch when cell A is lost
  docker compose --env-file data/.env -f docker-compose.yml --profile standby build standby >/dev/null
  docker compose --env-file data/.env -f docker-compose.yml --profile standby create standby >/dev/null
else
  docker compose --env-file data/.env -f docker-compose.yml up -d --wait "${SERVICES[@]}"
fi

echo
if [ "$LOCAL" = true ]; then
  echo "Sprout is up at http://localhost:18080"
else
  echo "Sprout is up at https://$SPROUT_HOSTNAME"
fi
