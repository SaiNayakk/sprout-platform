#!/data/data/com.termux/files/usr/bin/sh
# This cell's connector to the front door both cells share (sprout-saiworks..., the tunnel sprout-front; ADR-027). A
# piece of start.sh, started last, so the front door only sends visitors here once this cell's services all answer.
# Its credentials are ~/.cloudflared/front.json (copied there from the laptop, which created the tunnel).
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
cat > "$HERE/config.yml" <<EOF
tunnel: $(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.cloudflared/front.json")))["TunnelID"])')
credentials-file: $HOME/.cloudflared/front.json
metrics: 127.0.0.1:8183
ingress:
  - hostname: sprout-saiworks.nncs.in
    service: http://localhost:8180
  - service: http_status:404
EOF
exec cloudflared tunnel --no-autoupdate --config "$HERE/config.yml" run
