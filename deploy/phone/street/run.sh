#!/data/data/com.termux/files/usr/bin/sh
# The street host on the phone (Sprout Bank), started by Backseat as `sh run.sh`.
set -eu
set -a
. "$HOME/.sprout.env"
set +a

export BANK_DB_URL="jdbc:postgresql://127.0.0.1:5432/sprout?currentSchema=bank"
export BANK_DB_USER=sprout
export BANK_DB_PASSWORD="$SPROUT_DB_PASSWORD"
export BANK_BIND=127.0.0.1
export LOG_FORMAT=ecs

java -XX:+UseSerialGC -Xms32m -Xmx128m -Xss512k -XX:MaxMetaspaceSize=192m \
  -XX:ReservedCodeCacheSize=48m -XX:TieredStopAtLevel=1 -jar street-host.jar
