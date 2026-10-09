#!/usr/bin/env bash
# Gives each cell the other cell's keys, which its standby needs to take the other cell's customers over (ADR-027):
# the token-signing key (so customers' sessions keep working), the two-factor encryption key and the PAN pepper (so
# their data still reads), and the keys the services use with each other. Run on the laptop (cell B), with the phone
# (cell A) reachable over SSH. Safe to run again. Nothing is printed.
#
#   deploy/cells/exchange-secrets.sh
#
# Cell A's keys land in deploy/laptop/data/cell-a/ (never committed); cell B's in ~/.sprout-b.env and
# ~/.sprout/keys/b-signing.pem on the phone.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DATA="$HERE/../laptop/data"
PHONE="${PHONE:-u0_a1@192.168.0.6}"
SSH=(ssh -i "${PHONE_KEY:-$HOME/.ssh/backseat_phone}" -p 8022 -o BatchMode=yes -o IdentitiesOnly=yes "$PHONE")
umask 077
mkdir -p "$DATA/cell-a/keys"

# cell A -> here: its env file without what belongs to the phone alone (its database password, the cells' own
# settings, capacity experiments)
"${SSH[@]}" 'grep -vE "^(#|SPROUT_DB_PASSWORD=|CELL_|SPRING_THREADS|SPROUT_[A-Z]+_JAVA_OPTS=)" ~/.sprout.env' > "$DATA/cell-a/cell-a.env"
"${SSH[@]}" 'cat ~/.sprout/keys/signing.pem' > "$DATA/cell-a/keys/signing.pem"
chmod 644 "$DATA/cell-a/keys/signing.pem"   # the standby runs as its own user inside its container
echo "cell A's keys: $(grep -c = "$DATA/cell-a/cell-a.env") settings and its signing key"

# here -> cell A: this cell's secrets under the names the services read (compose maps S_* to them for cell B's own hosts)
python - "$DATA/.env" > /tmp/sprout-b.env <<'PY'
import sys
env = dict(l.rstrip('\n').split('=', 1) for l in open(sys.argv[1], encoding='utf-8') if '=' in l and not l.startswith('#'))
names = {'IDENTITY_TOTP_KEY': 'IDENTITY_TOTP_KEY', 'ACCOUNTS_PAN_PEPPER': 'S_PAN_PEPPER', 'SPROUT_SERVICE_KEY': 'S_SERVICE_KEY',
         'BANK_SPROUT_PARTNER_KEY': 'S_PARTNER_KEY', 'BANK_SPROUT_WEBHOOK_SECRET': 'S_WEBHOOK_SECRET',
         'EXCHANGE_SPROUT_MEMBER_KEY': 'S_MEMBER_KEY', 'EXCHANGE_SPROUT_WEBHOOK_SECRET': 'S_EXCHANGE_WEBHOOK_SECRET',
         'EXCHANGE_CLEARING_KEY': 'S_EXCHANGE_CLEARING_KEY', 'BANK_CLEARING_PARTNER_KEY': 'S_CLEARING_PARTNER_KEY',
         'BANK_CLEARING_WEBHOOK_SECRET': 'S_CLEARING_BANK_WEBHOOK_SECRET', 'DEPOSITORY_SPROUT_PARTICIPANT_KEY': 'S_PARTICIPANT_KEY',
         'DEPOSITORY_CLEARING_KEY': 'S_DEPOSITORY_CLEARING_KEY', 'CLEARING_SPROUT_MEMBER_KEY': 'S_CLEARING_MEMBER_KEY',
         'CLEARING_SPROUT_WEBHOOK_SECRET': 'S_CLEARING_WEBHOOK_SECRET', 'BANK_PAYROLL_PARTNER_KEY': 'S_PAYROLL_PARTNER_KEY',
         'BANK_PAYROLL_WEBHOOK_SECRET': 'S_PAYROLL_WEBHOOK_SECRET', 'MARKETDATA_START_DATE': 'MARKETDATA_START_DATE',
         'MARKETDATA_EPOCH': 'MARKETDATA_EPOCH'}
missing = [src for src in names.values() if not env.get(src)]
if missing:
    sys.exit(f'cell B has no {", ".join(missing)} yet: run deploy/laptop/up.sh first')
print('# Cell B\'s keys, for this phone\'s standby (ADR-027). Written by deploy/cells/exchange-secrets.sh; never copy elsewhere.')
for name, src in names.items():
    print(f'{name}={env[src]}')
print('SPROUT_SANDBOX=true')
PY
tr -d '\r' < /tmp/sprout-b.env | "${SSH[@]}" 'umask 077; cat > ~/.sprout-b.env'   # Windows Python writes CRLF
rm -f /tmp/sprout-b.env
"${SSH[@]}" 'umask 077; mkdir -p ~/.sprout/keys; cat > ~/.sprout/keys/b-signing.pem' < "$DATA/keys/signing.pem"
echo "cell B's keys sent to the phone"
