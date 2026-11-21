#!/bin/bash
# hoststop_n.sh N [--xvfb] : stop fork pcbnew instance N (by PID from $KPNS_STATE/hosttestN/pcbnew.pid), remove its socket;
#   --xvfb also stops the Xvfb :9N that hoststart_n.sh started (by PID from hosttestN/xvfb.pid)
# Unsaved changes are lost: save first (tools/save.py).
source "$(cd "$(dirname "$0")" && pwd)/paths.sh"
N=$1; [[ "$N" =~ ^[1-6]$ ]] || { echo "usage: $0 N(1..6) [--xvfb]"; exit 2; }
WD=$KPNS_STATE/hosttest$N
stop() { local P=$1 name=$2
  [ -n "$P" ] && grep -q "$name" /proc/$P/cmdline 2>/dev/null || return 0
  kill $P; for i in $(seq 1 20); do kill -0 $P 2>/dev/null || return 0; sleep 0.5; done; kill -9 $P; }
[ -f "$WD/pcbnew.pid" ] && { stop "$(cat "$WD/pcbnew.pid")" pcbnew; rm -f "$WD/pcbnew.pid"; }
rm -f $KPNS_SOCK_PREFIX$N/kicad/api.sock $KPNS_SOCK_PREFIX$N/kicad/api.lock "$WD"/~*.lck
if [ "$2" = "--xvfb" ] && [ -f "$WD/xvfb.pid" ]; then stop "$(cat "$WD/xvfb.pid")" Xvfb; rm -f "$WD/xvfb.pid"; fi
echo "STOPPED $N"
