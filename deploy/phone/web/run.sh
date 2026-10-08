#!/data/data/com.termux/files/usr/bin/sh
# The Sprout web app on the phone: Termux's nginx serves the built app from html/ and forwards /api to the
# gateway, started by Backseat as `sh run.sh`. The build arrives in html/ with each web deploy.
#
#   sh run.sh           render the configuration and run nginx (in the foreground)
#   sh run.sh reload    render it again and have the running nginx reload it, without stopping
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HERE/tmp"

render() {
  # Only while a capacity test runs (capacity/run.py creates the flag): the test's load generator reaches the web
  # server over Wi-Fi directly, so the phone isn't also encrypting an SSH tunnel's worth of traffic. Off otherwise.
  LAN=""
  [ -f "$HOME/.sprout-capacity-lan" ] && LAN="listen 0.0.0.0:8181;"
  sed -e "s#@PREFIX@#$PREFIX#g" -e "s#@HERE@#$HERE#g" -e "s#@CAPACITY_LISTEN@#$LAN#" "$HERE/nginx.conf.template" > "$HERE/nginx.conf"
  nginx -t -q -c "$HERE/nginx.conf" -p "$HERE"
}

render
if [ "${1:-}" = reload ]; then
  nginx -s reload -c "$HERE/nginx.conf" -p "$HERE"
  exit 0
fi
# no exec: Backseat recognises the app by this shell staying in its folder
nginx -c "$HERE/nginx.conf" -p "$HERE"
