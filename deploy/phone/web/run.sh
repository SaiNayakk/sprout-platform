#!/data/data/com.termux/files/usr/bin/sh
# The Sprout web app on the phone: Termux's nginx serves the built app from html/ and forwards /api to the
# gateway, started by Backseat as `sh run.sh`. The build arrives in html/ with each web deploy.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HERE/tmp"
sed -e "s#@PREFIX@#$PREFIX#g" -e "s#@HERE@#$HERE#g" "$HERE/nginx.conf.template" > "$HERE/nginx.conf"
nginx -t -q -c "$HERE/nginx.conf" -p "$HERE"
# no exec: Backseat recognises the app by this shell staying in its folder
nginx -c "$HERE/nginx.conf" -p "$HERE"
