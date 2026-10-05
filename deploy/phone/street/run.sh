#!/data/data/com.termux/files/usr/bin/sh
# The street host on the phone (Sprout Bank and the exchange), started by Backseat as `sh run.sh`.
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
export LOG_FORMAT=ecs
# market data and the order service's callback default to 127.0.0.1 on their ports

java -XX:+UseSerialGC -Xms32m -Xmx160m -Xss512k -XX:MaxMetaspaceSize=192m \
  -XX:ReservedCodeCacheSize=48m -XX:TieredStopAtLevel=1 -jar street-host.jar
