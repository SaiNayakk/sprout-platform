#!/data/data/com.termux/files/usr/bin/sh
# The trading host on the phone (market data and orders), started by Backseat as `sh run.sh`.
set -eu
set -a
. "$HOME/.sprout.env"
set +a

export MARKETDATA_BIND=127.0.0.1
export MARKETDATA_CLOCK=WALL                  # the market follows real Indian time: open 09:15-15:30 IST
export MARKETDATA_NATS_URL=nats://127.0.0.1:4222
export OMS_DB_URL="jdbc:postgresql://127.0.0.1:5432/sprout?currentSchema=oms"
export OMS_DB_USER=sprout
export OMS_DB_PASSWORD="$SPROUT_DB_PASSWORD"
export OMS_BIND=127.0.0.1
export LOG_FORMAT=ecs
# accounts, ledger and the exchange default to 127.0.0.1 on their ports

java -XX:+UseSerialGC -Xms32m -Xmx160m -Xss512k -XX:MaxMetaspaceSize=192m \
  -XX:ReservedCodeCacheSize=48m -XX:TieredStopAtLevel=1 -jar trading-host.jar
