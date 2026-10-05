#!/data/data/com.termux/files/usr/bin/sh
# The money host on the phone (ledger, accounts, payments, settlement, statements, recon, goals), started by
# Backseat as `sh run.sh`.
set -eu
set -a
. "$HOME/.sprout.env"
set +a

for svc in LEDGER ACCOUNTS PAYMENTS SETTLEMENT RECON GOALS; do
  schema=$(echo "$svc" | tr 'A-Z' 'a-z')
  export "${svc}_DB_URL=jdbc:postgresql://127.0.0.1:5432/sprout?currentSchema=$schema"
  export "${svc}_DB_USER=sprout"
  export "${svc}_DB_PASSWORD=$SPROUT_DB_PASSWORD"
  export "${svc}_BIND=127.0.0.1"
done
export STATEMENTS_BIND=127.0.0.1   # statements has no database
export LOG_FORMAT=ecs
# service URLs default to 127.0.0.1 on their ports; the bank calls back on 127.0.0.1:8105

java -XX:+UseSerialGC -Xms32m -Xmx160m -Xss512k -XX:MaxMetaspaceSize=192m \
  -XX:ReservedCodeCacheSize=48m -XX:TieredStopAtLevel=1 -jar money-host.jar
