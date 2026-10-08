#!/data/data/com.termux/files/usr/bin/sh
# Cell B's services, on this phone's copy of cell B's database (ADR-027): what cell A runs for cell B's customers when
# the laptop is lost. A Backseat app, `sprout-standby`, registered stopped by setup.sh and started only by cellwatch.
#
# Every service in one JVM (the cell host), beside this phone's own four hosts: every port is moved up by 100 and every
# database points at sprout_b (standby.env, generated from the services' own configuration by
# deploy/cells/standby_env.py at deploy), and it runs with cell B's own keys, so B's customers' sessions keep working.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
set -a
. "$HOME/.sprout.env"      # this Postgres's password (the copy lives here) and the cells' shared key
. "$HOME/.sprout-b.env"    # cell B's keys: sessions, two-factor, PANs, the services' keys to each other, its market
. "$HERE/standby.env"      # ports +100, databases -> sprout_b
set +a

for svc in IDENTITY SANDBOX OMS PLANS HABITS REWARDS LEDGER ACCOUNTS PAYMENTS SETTLEMENT RECON GOALS BANK EXCHANGE DEPOSITORY CLEARING; do
  export "${svc}_DB_USER=sprout" "${svc}_DB_PASSWORD=$SPROUT_DB_PASSWORD"
done
export GATEWAY_BIND=127.0.0.1 GATEWAY_TRUST_CF_IP=true
export GATEWAY_CELL_ID=b GATEWAY_CELL_KEY="$CELL_KEY" GATEWAY_CELL_JOURNAL_DIR="$HERE/journal"
export IDENTITY_SIGNING_KEY_PATH="$HOME/.sprout/keys/b-signing.pem" IDENTITY_DEMO_ENABLED=true
export MARKETDATA_CLOCK=ACCELERATED MARKETDATA_SPEED=30
# the sandbox's pace, as cell B runs it
export SANDBOX_EVERY=5s PLANS_EVERY=10s OMS_RMS_EVERY=1s SETTLEMENT_EVERY=2s RECON_CHECK_EVERY=10s GOALS_EVERY=10s \
       PAYMENTS_RECONCILE_EVERY=5s CLEARING_SETTLE_EVERY=2s BANK_PAYROLL_FLOAT=100000000.00
export LOG_FORMAT=ecs
mkdir -p "$HERE/journal"

java -XX:+UseSerialGC -Xms32m -Xmx220m -Xss512k -XX:MaxMetaspaceSize=256m -XX:ReservedCodeCacheSize=64m \
  -XX:TieredStopAtLevel=1 -XX:ActiveProcessorCount=2 -jar cell-host.jar
