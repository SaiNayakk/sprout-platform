#!/data/data/com.termux/files/usr/bin/sh
# One-time (and safe to re-run) setup of Sprout on the phone. Run on the phone:
#
#   sh ~/sprout/setup.sh
#
# It never prints, logs or uploads a secret. What it does, skipping whatever is already done:
#   1. starts Postgres (Termux's cluster) for the steps below, if nothing is listening on 5432 (stopped again after)
#   2. creates the `sprout` role and database
#   3. writes the server keys to ~/.sprout.env and ~/.sprout/keys (owner-only)
#   4. installs NATS from its official release, checksum-verified
#   5. installs nginx and registers Sprout with Backseat as ONE app, `sprout` (start.sh), which starts Postgres,
#      NATS, the hosts and the web app one at a time, never all at once (the per-piece apps of earlier releases
#      are removed: Backseat starting them together at boot made the phone reboot)
set -eu

SPROUT="$HOME/sprout"
ENV_FILE="$HOME/.sprout.env"
KEYS="$HOME/.sprout/keys"
PGDATA="${PREFIX}/var/lib/postgresql"
NATS_VERSION="2.10.29"
AGENT="http://127.0.0.1:8080"

say() { printf '> %s\n' "$*"; }

agent() { # METHOD PATH [JSON]
  token=$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.backseat/agent/token.json")))["session_token"])')
  if [ $# -ge 3 ]; then
    curl -s -m 30 -X "$1" -H "x-backseat-token: $token" -H 'Content-Type: application/json' -d "$3" "$AGENT$2"
  else
    curl -s -m 30 -X "$1" -H "x-backseat-token: $token" "$AGENT$2"
  fi
}

has_app() { curl -s -m 10 "$AGENT/public/status" | python3 -c "import json,sys; sys.exit(0 if any(a['name']=='$1' for a in json.load(sys.stdin)['apps']) else 1)"; }

register() { # NAME DIR
  if has_app "$1"; then
    say "Backseat app $1 already registered"
  else
    cmd="sh run.sh"; [ "$1" = sprout ] && cmd="sh start.sh"
    agent POST /apps "{\"name\":\"$1\",\"command\":\"$cmd\",\"cwd\":\"$2\"}" >/dev/null
    say "registered Backseat app $1"
  fi
}

# 1. Postgres, for the steps below only: start.sh runs it from now on
mkdir -p "$SPROUT/postgres"
# no exec: postgres changes into its data directory, and start.sh follows the piece by this shell
printf '#!/data/data/com.termux/files/usr/bin/sh
postgres -D "%s"
' "$PGDATA" > "$SPROUT/postgres/run.sh"
STARTED_PG=false
if pg_isready -q -h 127.0.0.1 -p 5432; then
  say "Postgres already running"
else
  pg_ctl -D "$PGDATA" -l "$SPROUT/postgres/setup.log" -w start >/dev/null
  STARTED_PG=true
  say "Postgres started for set-up"
fi

# 3 (first, so step 2 can use the password). Server keys, owned by the operator, never shown.
umask 077
mkdir -p "$KEYS"
if [ ! -f "$ENV_FILE" ]; then
  python3 - "$ENV_FILE" <<'PY'
import base64, secrets, sys
with open(sys.argv[1], "w") as f:
    f.write("# Sprout server secrets. Generated on this phone; never copy them elsewhere.\n")
    f.write("# Rotate with: sh ~/sprout/rotate-keys.sh\n")
    f.write(f"SPROUT_DB_PASSWORD={secrets.token_urlsafe(32)}\n")
    f.write(f"IDENTITY_TOTP_KEY={base64.b64encode(secrets.token_bytes(32)).decode()}\n")
PY
  say "wrote $ENV_FILE"
else
  say "$ENV_FILE already exists; keeping it"
fi
# secrets added in later releases: appended if missing, existing ones never changed
python3 - "$ENV_FILE" <<'PY'
import secrets, sys
path = sys.argv[1]
have = {l.split("=", 1)[0] for l in open(path) if "=" in l}
new = {"SPROUT_SERVICE_KEY": secrets.token_urlsafe(32), "BANK_SPROUT_PARTNER_KEY": secrets.token_urlsafe(32),
       "BANK_SPROUT_WEBHOOK_SECRET": secrets.token_urlsafe(32), "ACCOUNTS_PAN_PEPPER": secrets.token_urlsafe(32),
       "EXCHANGE_SPROUT_MEMBER_KEY": secrets.token_urlsafe(32), "EXCHANGE_SPROUT_WEBHOOK_SECRET": secrets.token_urlsafe(32),
       "EXCHANGE_CLEARING_KEY": secrets.token_urlsafe(32), "BANK_CLEARING_PARTNER_KEY": secrets.token_urlsafe(32),
       "BANK_CLEARING_WEBHOOK_SECRET": secrets.token_urlsafe(32), "DEPOSITORY_SPROUT_PARTICIPANT_KEY": secrets.token_urlsafe(32),
       "DEPOSITORY_CLEARING_KEY": secrets.token_urlsafe(32), "CLEARING_SPROUT_MEMBER_KEY": secrets.token_urlsafe(32),
       "CLEARING_SPROUT_WEBHOOK_SECRET": secrets.token_urlsafe(32)}
missing = {k: v for k, v in new.items() if k not in have}
if missing:
    with open(path, "a") as f:
        f.writelines(f"{k}={v}\n" for k, v in missing.items())
print("> added server secrets: " + (", ".join(missing) if missing else "none needed"))
PY
if [ ! -f "$KEYS/signing.pem" ]; then
  java "$SPROUT/KeyGen.java" "$KEYS/signing.pem"
  say "generated the token-signing key"
else
  say "token-signing key already exists; keeping it"
fi
chmod 600 "$ENV_FILE" "$KEYS/signing.pem"
umask 022

# 2. Role and database
DB_PASSWORD=$(sed -n 's/^SPROUT_DB_PASSWORD=//p' "$ENV_FILE")
if psql -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='sprout'" | grep -q 1; then
  say "role sprout exists"
else
  psql -d postgres -q -v ON_ERROR_STOP=1 -v pw="$DB_PASSWORD" <<'SQL'
CREATE ROLE sprout LOGIN PASSWORD :'pw';
SQL
  say "created role sprout"
fi
if psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='sprout'" | grep -q 1; then
  say "database sprout exists"
else
  psql -d postgres -q -v ON_ERROR_STOP=1 -c "CREATE DATABASE sprout OWNER sprout"
  say "created database sprout"
fi

# 4. NATS, from the official release, checksum-verified
mkdir -p "$SPROUT/nats"
if [ -x "$SPROUT/nats/nats-server" ] && "$SPROUT/nats/nats-server" --version | grep -q "v$NATS_VERSION"; then
  say "NATS $NATS_VERSION installed"
else
  tmp=$(mktemp -d)
  base="https://github.com/nats-io/nats-server/releases/download/v$NATS_VERSION"
  file="nats-server-v$NATS_VERSION-linux-arm64.tar.gz"
  curl -fsSL -o "$tmp/$file" "$base/$file"
  curl -fsSL -o "$tmp/SHA256SUMS" "$base/SHA256SUMS"
  want=$(grep " $file\$" "$tmp/SHA256SUMS" | awk '{print $1}')
  got=$(sha256sum "$tmp/$file" | awk '{print $1}')
  [ -n "$want" ] && [ "$want" = "$got" ] || { echo "NATS checksum mismatch; not installing"; rm -rf "$tmp"; exit 1; }
  tar xzf "$tmp/$file" -C "$tmp"
  mv "$tmp/nats-server-v$NATS_VERSION-linux-arm64/nats-server" "$SPROUT/nats/nats-server"
  rm -rf "$tmp"
  say "installed NATS $NATS_VERSION (checksum verified)"
fi
cp "$SPROUT/nats-run.sh" "$SPROUT/nats/run.sh"

# 5. Sprout as one Backseat app
# the web app is served by Termux's nginx
command -v nginx >/dev/null || { pkg install -y nginx >/dev/null && say "installed nginx"; }
mkdir -p "$SPROUT/edge" "$SPROUT/trading" "$SPROUT/money" "$SPROUT/street" "$SPROUT/web"
for old in sprout-web sprout-edge sprout-money sprout-street sprout-trading sprout-nats sprout-postgres; do
  if has_app "$old"; then
    agent DELETE "/apps/$old" >/dev/null
    say "removed the old Backseat app $old"
  fi
done
if [ "$STARTED_PG" = true ]; then
  pg_ctl -D "$PGDATA" -m fast -w stop >/dev/null
  say "Postgres stopped (start.sh runs it)"
fi
missing=""
for host in trading street money edge web; do
  [ -f "$SPROUT/$host/run.sh" ] || missing="$missing $host"
done
if [ -n "$missing" ]; then
  say "not registering Sprout yet: waiting for the first deploy of:$missing"
else
  register sprout "$SPROUT"
  # cell B's standby (ADR-027): registered stopped, started only by cellwatch when the laptop is lost
  if [ -f "$HOME/.sprout-b.env" ] && [ -f "$SPROUT/standby/cell-host.jar" ] && ! has_app sprout-standby; then
    register sprout-standby "$SPROUT/standby"
    agent POST /apps/sprout-standby/stop >/dev/null
    say "registered the standby for cell B (stopped)"
  fi
  say "Sprout starts piece by piece (after the phone has been up 5 minutes): tail -f ~/sprout/logs/*.log"
fi
say "done"
