#!/data/data/com.termux/files/usr/bin/sh
# The client end of the connection to cell B's database (pg-b-..., through Cloudflare): 127.0.0.1:15433 here reaches
# the laptop's Postgres, for the subscription that copies cell B into sprout_b (ADR-027). A piece of start.sh.
set -eu
exec cloudflared access tcp --hostname pg-b-saiworks.nncs.in --url 127.0.0.1:15433
