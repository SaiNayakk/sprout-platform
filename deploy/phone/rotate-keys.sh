#!/data/data/com.termux/files/usr/bin/sh
# Replaces Sprout's server keys on the phone. Run on the phone: sh ~/sprout/rotate-keys.sh
#
# - token-signing key: new key; everyone is signed out and signs in again.
# - database password: new password, applied to the `sprout` role.
# - keys services use with each other (service key; bank, exchange, depository and clearing keys and
#   callback secrets): new values; both sides read the same file, so they still agree.
# - NOT rotated: the two-factor encryption key and the PAN pepper. Stored data depends on them
#   (two-factor secrets are encrypted with one, PAN fingerprints are made with the other), so changing
#   them needs a re-encryption step that doesn't exist yet.
# Then restarts every Sprout host. Nothing is printed.
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
import secrets
import sys
path, new = sys.argv[1], sys.argv[2]
fresh = {"SPROUT_DB_PASSWORD": new}
for name in ("SPROUT_SERVICE_KEY", "BANK_SPROUT_PARTNER_KEY", "BANK_SPROUT_WEBHOOK_SECRET",
             "EXCHANGE_SPROUT_MEMBER_KEY", "EXCHANGE_SPROUT_WEBHOOK_SECRET", "EXCHANGE_CLEARING_KEY",
             "BANK_CLEARING_PARTNER_KEY", "BANK_CLEARING_WEBHOOK_SECRET", "DEPOSITORY_SPROUT_PARTICIPANT_KEY",
             "DEPOSITORY_CLEARING_KEY", "CLEARING_SPROUT_MEMBER_KEY", "CLEARING_SPROUT_WEBHOOK_SECRET"):
    fresh[name] = secrets.token_urlsafe(32)
out = []
for line in open(path).read().splitlines():
    name = line.split("=", 1)[0]
    out.append(f"{name}={fresh[name]}" if "=" in line and name in fresh else line)
open(path, "w").write("\n".join(out) + "\n")
PY
chmod 600 "$ENV_FILE"

token=$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.backseat/agent/token.json")))["session_token"])')
for app in sprout-street sprout-money sprout-trading sprout-edge; do
  curl -s -m 30 -X POST -H "x-backseat-token: $token" "http://127.0.0.1:8080/apps/$app/restart" >/dev/null
done
echo "Rotated the signing key, database password and service keys; restarted the Sprout hosts. Everyone has to sign in again."
