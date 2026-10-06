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
python render.py
mkdir -p data/keys data/cloudflared
if [ ! -f data/keys/signing.pem ]; then
  java "$ROOT/deploy/phone/KeyGen.java" data/keys/signing.pem
  chmod 644 data/keys/signing.pem    # the services run as a user of their own inside their containers
fi
set -a; . data/.env; set +a

if [ "$BUILD" = true ]; then
  echo "> Building the hosts from their release manifests"
  "$ROOT/hosts/install-services.sh"
  for host in edge trading money street; do
    (cd "$ROOT/hosts/$host" && mvn -q -B -DskipTests package)
  done
fi

if [ "$LOCAL" = false ]; then
  echo "> The tunnel to $SPROUT_HOSTNAME"
  if [ ! -f data/cloudflared/config.yml ]; then
    # The tunnel is found by its exact name. (Never `tunnel info NAME`: for a name it doesn't know it quietly answers
    # about the default tunnel in ~/.cloudflared/config.yml, which belongs to something else entirely.)
    find_tunnel() {
      "$CLOUDFLARED" tunnel list --name sprout-laptop --output json 2>/dev/null |
        python -c "import sys,json; t=[x for x in json.load(sys.stdin) if x['name']=='sprout-laptop']; print(t[0]['id'] if t else '')"
    }
    id="$(find_tunnel)"
    if [ -z "$id" ]; then
      "$CLOUDFLARED" tunnel create sprout-laptop >/dev/null
      id="$(find_tunnel)"
    fi
    [ -n "$id" ] || { echo "couldn't create or find the tunnel sprout-laptop"; exit 1; }
    [ -f "$HOME/.cloudflared/$id.json" ] || { echo "no credentials for tunnel $id in ~/.cloudflared"; exit 1; }
    cp "$HOME/.cloudflared/$id.json" data/cloudflared/creds.json
    cat > data/cloudflared/config.yml <<EOF
tunnel: $id
credentials-file: /etc/cloudflared/creds.json
ingress:
  - hostname: $SPROUT_HOSTNAME
    service: http://web:80
  - service: http_status:404
EOF
    # by id, and without overwriting: a hostname that already points somewhere is somebody's, not ours to take
    "$CLOUDFLARED" tunnel route dns "$id" "$SPROUT_HOSTNAME"
  fi
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
SERVICES=(postgres nats edge trading money street web)
[ "$LOCAL" = true ] || SERVICES+=(cloudflared)
if [ "$BUILD" = true ]; then
  docker compose --env-file data/.env -f docker-compose.yml up -d --build --wait "${SERVICES[@]}"
else
  docker compose --env-file data/.env -f docker-compose.yml up -d --wait "${SERVICES[@]}"
fi

echo
if [ "$LOCAL" = true ]; then
  echo "Sprout is up at http://localhost:18080"
else
  echo "Sprout is up at https://$SPROUT_HOSTNAME"
fi
