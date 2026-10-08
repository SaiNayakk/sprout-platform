#!/data/data/com.termux/files/usr/bin/sh
# The trading host on the phone (market data, orders, plans, habits, rewards), started by Backseat as `sh run.sh`.
set -eu
set -a
. "$HOME/.sprout.env"
set +a

export MARKETDATA_BIND=127.0.0.1
export MARKETDATA_CLOCK=WALL                  # the market follows real Indian time: open 09:15-15:30 IST
export MARKETDATA_NATS_URL=nats://127.0.0.1:4222
for svc in OMS PLANS HABITS REWARDS; do
  schema=$(echo "$svc" | tr 'A-Z' 'a-z')
  export "${svc}_DB_URL=jdbc:postgresql://127.0.0.1:5432/sprout?currentSchema=$schema"
  export "${svc}_DB_USER=sprout"
  export "${svc}_DB_PASSWORD=$SPROUT_DB_PASSWORD"
  export "${svc}_BIND=127.0.0.1"
done
export LOG_FORMAT=ecs
if [ "${SPROUT_SANDBOX:-false}" = true ]; then
  export MARKETDATA_CLOCK=ACCELERATED   # the sandbox's market runs fast, so its fictional customers build months of history
  export MARKETDATA_SPEED=30
  # a trading day passes in ~13 minutes, so the loops run at the pace the laptop and pre-prod proved
  export PLANS_EVERY=10s OMS_RMS_EVERY=1s
  # MARKETDATA_START_DATE and MARKETDATA_EPOCH come from ~/.sprout.env: the market resumes where it was
fi
# accounts, ledger and the exchange default to 127.0.0.1 on their ports

java -XX:+UseSerialGC -Xms32m -Xmx160m -Xss512k -XX:MaxMetaspaceSize=192m \
  -XX:ReservedCodeCacheSize=48m -XX:TieredStopAtLevel=1 -jar trading-host.jar
