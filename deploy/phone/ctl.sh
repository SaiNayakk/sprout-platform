#!/data/data/com.termux/files/usr/bin/sh
# Starts, stops or restarts Backseat apps on the phone, through the agent on this phone.
#   sh ~/sprout/ctl.sh start|stop|restart NAME...
set -eu
act=$1; shift
token=$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.backseat/agent/token.json")))["session_token"])')
for n in "$@"; do
  r=$(curl -s -m 60 -X POST -H "x-backseat-token: $token" "http://127.0.0.1:8080/apps/$n/$act")
  echo "$n $act: $(echo "$r" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("status") or d.get("state") or d.get("detail") or d)' 2>/dev/null || echo "$r" | head -c 200)"
done
