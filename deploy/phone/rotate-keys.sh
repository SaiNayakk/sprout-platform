#!/data/data/com.termux/files/usr/bin/sh
# Replaces Sprout's server keys on the phone. Run on the phone: sh ~/sprout/rotate-keys.sh
#
# - token-signing key: new key; everyone is signed out and signs in again.
# - two-factor encryption key: NOT rotated here. Existing users' two-factor secrets are encrypted
#   with it, so changing it needs a re-encryption step that doesn't exist yet.
# - database password: new password, applied to the `sprout` role.
# Then restarts the edge host. Nothing is printed.
set -eu
umask 077
ENV_FILE="$HOME/.sprout.env"
KEYS="$HOME/.sprout/keys"

java "$HOME/sprout/KeyGen.java" "$KEYS/signing.pem"
chmod 600 "$KEYS/signing.pem"

NEW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
psql -d postgres -q -v ON_ERROR_STOP=1 -v pw="$NEW" <<'SQL'
ALTER ROLE sprout PASSWORD :'pw';
SQL
python3 - "$ENV_FILE" "$NEW" <<'PY'
import sys
path, new = sys.argv[1], sys.argv[2]
lines = open(path).read().splitlines()
out = [f"SPROUT_DB_PASSWORD={new}" if l.startswith("SPROUT_DB_PASSWORD=") else l for l in lines]
open(path, "w").write("\n".join(out) + "\n")
PY
chmod 600 "$ENV_FILE"

token=$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.backseat/agent/token.json")))["session_token"])')
curl -s -m 30 -X POST -H "x-backseat-token: $token" http://127.0.0.1:8080/apps/sprout-edge/restart >/dev/null
echo "Rotated the signing key and database password; restarted the edge host. Everyone has to sign in again."
