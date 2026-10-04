#!/data/data/com.termux/files/usr/bin/sh
# The trading host on the phone (market data), started by Backseat as `sh run.sh`.
set -eu

export MARKETDATA_BIND=127.0.0.1
export MARKETDATA_CLOCK=WALL                  # the market follows real Indian time: open 09:15-15:30 IST
export MARKETDATA_NATS_URL=nats://127.0.0.1:4222
export LOG_FORMAT=ecs

exec java -XX:+UseSerialGC -Xms32m -Xmx128m -Xss512k -XX:MaxMetaspaceSize=192m \
  -XX:ReservedCodeCacheSize=48m -XX:TieredStopAtLevel=1 -jar trading-host.jar
