#!/bin/bash
# hoststart_n.sh N BOARD.kicad_pcb PROJECT.kicad_pro [--force] : independent headless fork pcbnew instance N (1..6)
#   TMPDIR    ${KPNS_SOCK_PREFIX}N  -> socket ipc://${KPNS_SOCK_PREFIX}N/kicad/api.sock (default /tmp/kpnsN)
#   display   Xvfb :9N (started if missing; :99 stays for hoststart.sh); $KPNS_DISPLAY overrides it (an
#             existing display is used as is, with $XAUTHORITY if it needs one)
#   work dir  $KPNS_STATE/hosttestN (board.kicad_pcb/.kicad_pro/.kicad_dru copied there; pcbnew.pid, pcbnew.log, xvfb.pid)
#   config    $KPNS_STATE/hostcfgN (copied once from $KPNS_STATE/hostcfg, which is created with the API server on)
# A PROJECT.kicad_dru next to PROJECT.kicad_pro is copied as board.kicad_dru (custom rules).
# Refuses if instance N is running (someone's unsaved work) unless --force (then kills it by PID).
# Prints "READY <socket> pid <pid>" or NOTREADY. The instance never writes back to BOARD: save via tools/save.py.
source "$(cd "$(dirname "$0")" && pwd)/paths.sh"
N=$1
[[ "$N" =~ ^[1-6]$ ]] && [ -f "$2" ] && [ -f "$3" ] || { echo "usage: $0 N(1..6) BOARD.kicad_pcb PROJECT.kicad_pro [--force]"; exit 2; }
WD=$KPNS_STATE/hosttest$N; C=$KPNS_STATE/hostcfg$N
export LD_LIBRARY_PATH=$KPNS_HOSTLIB KICAD_RUN_FROM_BUILD_DIR=1 KICAD_CONFIG_HOME=$C TMPDIR=$KPNS_SOCK_PREFIX$N DISPLAY=${KPNS_DISPLAY:-:9$N}
unset WAYLAND_DISPLAY
mkdir -p $TMPDIR/kicad "$WD"
kpns_config "$KPNS_STATE/hostcfg"; [ -d "$C" ] || cp -a "$KPNS_STATE/hostcfg" "$C"
# own Xvfb
DN=${DISPLAY#:}
if [ ! -S /tmp/.X11-unix/X$DN ]; then
  rm -f /tmp/.X$DN-lock
  setsid Xvfb $DISPLAY -screen 0 1920x1080x24 -nolisten tcp >"$WD/xvfb.log" 2>&1 < /dev/null & echo $! > "$WD/xvfb.pid"
  for i in $(seq 1 20); do [ -S /tmp/.X11-unix/X$DN ] && break; sleep 0.5; done
fi
# previous instance N
if [ -f "$WD/pcbnew.pid" ]; then P=$(cat "$WD/pcbnew.pid")
  if [ -n "$P" ] && grep -q pcbnew /proc/$P/cmdline 2>/dev/null; then
    [ "$4" = "--force" ] || { echo "BUSY: instance $N is running (pid $P); stop it with hoststop_n.sh $N or pass --force"; exit 3; }
    kill $P; for i in $(seq 1 20); do kill -0 $P 2>/dev/null || break; sleep 0.5; done; kill -9 $P 2>/dev/null; fi
fi
rm -f "$WD"/~*.lck "$WD/board.kicad_dru" $TMPDIR/kicad/api.sock $TMPDIR/kicad/api.lock
cp "$2" "$WD/board.kicad_pcb"; cp "$3" "$WD/board.kicad_pro"
D="${3%.kicad_pro}.kicad_dru"; [ -f "$D" ] && cp "$D" "$WD/board.kicad_dru"
(cd "$WD"; setsid "$KPNS_BUILD/pcbnew/pcbnew" board.kicad_pcb > "$WD/pcbnew.log" 2>&1 < /dev/null & echo $! > "$WD/pcbnew.pid")
PID=$(cat "$WD/pcbnew.pid")
S=ipc://$TMPDIR/kicad/api.sock
for i in $(seq 1 60); do
  sleep 3
  kill -0 $PID 2>/dev/null || { echo "NOTREADY (pcbnew exited)"; tail -5 "$WD/pcbnew.log"; exit 1; }
  # first-run wizard / "are you sure" / "undefined layers -> Rescue" (positions for a 1920x1080 Xvfb, no WM)
  W0=$(timeout 5 xdotool search --name "KiCad Setup" 2>/dev/null | head -1)
  if [ -n "$W0" ]; then eval $(timeout 5 xdotool getwindowgeometry --shell $W0); timeout 5 xdotool mousemove $((X+WIDTH-54)) $((Y+HEIGHT-29)) click 1; sleep 3
    timeout 5 xdotool mousemove 483 398 click 1; sleep 15
    timeout 5 xdotool mousemove 793 416 click 1; sleep 5; fi
  kpns_ready "$S" pnsh$N && { echo "READY $S pid $PID"; exit 0; }
done
echo NOTREADY; tail -5 "$WD/pcbnew.log"; exit 1
