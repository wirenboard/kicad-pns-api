#!/bin/bash
# hoststart.sh BOARD.kicad_pcb PROJECT.kicad_pro : run the fork's pcbnew headless on this host
# (single default instance; for several parallel instances use hoststart_n.sh).
# - only the libraries in $KPNS_HOSTLIB come from the unpacked deps, the host's GTK otherwise
# - short TMPDIR ($KPNS_SOCK_PREFIX) for the API socket (<108 chars), private config with the API server on
# - Xvfb :99; clicks through the first-run dialogs with xdotool; prints READY <socket> when the API answers
source "$(cd "$(dirname "$0")" && pwd)/paths.sh"
[ -f "$1" ] && [ -f "$2" ] || { echo "usage: $0 BOARD.kicad_pcb PROJECT.kicad_pro"; exit 2; }
WD=$KPNS_STATE/hosttest; C=$KPNS_STATE/hostcfg
export LD_LIBRARY_PATH=$KPNS_HOSTLIB KICAD_RUN_FROM_BUILD_DIR=1 KICAD_CONFIG_HOME=$C TMPDIR=$KPNS_SOCK_PREFIX DISPLAY=:99
unset WAYLAND_DISPLAY
mkdir -p $TMPDIR/kicad "$WD"; kpns_config "$C"
[ -S /tmp/.X11-unix/X99 ] || { (setsid Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp >/dev/null 2>&1 &); sleep 2; }
[ -f "$WD/pcbnew.pid" ] && kill $(cat "$WD/pcbnew.pid") 2>/dev/null; sleep 1
cp "$1" "$WD/board.kicad_pcb"; cp "$2" "$WD/board.kicad_pro"; rm -f "$WD"/~*.lck $TMPDIR/kicad/api.sock $TMPDIR/kicad/api.lock
(cd "$WD"; setsid "$KPNS_BUILD/pcbnew/pcbnew" board.kicad_pcb > "$WD/pcbnew.log" 2>&1 & echo $! > "$WD/pcbnew.pid")
S=ipc://$TMPDIR/kicad/api.sock
for i in $(seq 1 45); do
  sleep 4
  W0=$(xdotool search --name "KiCad Setup" 2>/dev/null | head -1)
  if [ -n "$W0" ]; then eval $(xdotool getwindowgeometry --shell $W0); xdotool mousemove $((X+WIDTH-54)) $((Y+HEIGHT-29)) click 1; sleep 3
    # "Are you sure?" -> Yes (left button); screen positions for a 1920x1080 Xvfb without a window manager
    xdotool mousemove 483 398 click 1; sleep 15
    # "Items found on undefined layers" -> Rescue
    xdotool mousemove 793 416 click 1; sleep 5; fi
  kpns_ready "$S" pnsh && { echo "READY $S"; exit 0; }
done
echo NOTREADY; tail -5 "$WD/pcbnew.log"
