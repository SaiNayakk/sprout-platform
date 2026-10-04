#!/data/data/com.termux/files/usr/bin/sh
# NATS on the phone, local only, started by Backseat as `sh run.sh` (setup.sh copies this into ~/sprout/nats).
exec ./nats-server -a 127.0.0.1 -p 4222 -m 8222
