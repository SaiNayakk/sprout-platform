#!/data/data/com.termux/files/usr/bin/sh
# The street host on the phone (Sprout Bank, the exchange, the depository and the clearing corporation),
# started by Backseat as `sh run.sh`.
set -eu
set -a
. "$HOME/.sprout.env"
set +a

export BANK_DB_URL="jdbc:postgresql://127.0.0.1:5432/sprout?currentSchema=bank"
export BANK_DB_USER=sprout
export BANK_DB_PASSWORD="$SPROUT_DB_PASSWORD"
export BANK_BIND=127.0.0.1
export EXCHANGE_DB_URL="jdbc:postgresql://127.0.0.1:5432/sprout?currentSchema=exchange"
export EXCHANGE_DB_USER=sprout
export EXCHANGE_DB_PASSWORD="$SPROUT_DB_PASSWORD"
export EXCHANGE_BIND=127.0.0.1
for svc in DEPOSITORY CLEARING; do
  schema=$(echo "$svc" | tr 'A-Z' 'a-z')
  export "${svc}_DB_URL=jdbc:postgresql://127.0.0.1:5432/sprout?currentSchema=$schema"
  export "${svc}_DB_USER=sprout"
  export "${svc}_DB_PASSWORD=$SPROUT_DB_PASSWORD"
  export "${svc}_BIND=127.0.0.1"
done
export LOG_FORMAT=ecs
if [ "${SPROUT_SANDBOX:-false}" = true ]; then
  export BANK_PAYROLL_FLOAT=100000000.00   # the sandbox's fictional payroll pays its fictional customers
  export CLEARING_SETTLE_EVERY=2s          # a day settles every ~13 minutes at 30x
fi
# everything else (market data, the order service's and back office's callbacks) defaults to 127.0.0.1

# JVM settings sized for the phone; SPROUT_STREET_JAVA_OPTS in ~/.sprout.env overrides them (capacity experiments)
java ${SPROUT_STREET_JAVA_OPTS:--XX:+UseSerialGC -Xms32m -Xmx160m -Xss512k -XX:MaxMetaspaceSize=192m -XX:ReservedCodeCacheSize=48m -XX:TieredStopAtLevel=1} \
  -jar street-host.jar
