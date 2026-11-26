#!/bin/bash
# smoke.sh [PKGROOT] : start the packaged pcbnew headless on the bundled demo board and run smoke.py
# against its IPC API (version, board, RouteTrack, DragTrack, RunDrc, save).
#   PKGROOT      unpacked package (default: two levels above this file, i.e. the package this script is in)
#   KPNS_PY      python with protobuf 5.29 and pynng (default: python3)
#   KPNS_DISPLAY X display for a private Xvfb (default :97); never use your desktop display
# Needs Xvfb. Exit code 0 when every check passes.
set -u
H=$(cd "$(dirname "$0")" && pwd)
R=$(cd "${1:-$H/../..}" && pwd)
PY=${KPNS_PY:-python3}
DSP=${KPNS_DISPLAY:-:97}
W=$(mktemp -d /tmp/kpns-smoke.XXXXXX)   # short: the API socket path must stay below 108 chars
XPID= KPID=
cleanup() {
  [ -n "$KPID" ] && kill "$KPID" 2>/dev/null
  [ -n "$XPID" ] && kill "$XPID" 2>/dev/null
  wait 2>/dev/null
  [ "${KEEP:-0}" = 1 ] || rm -rf "$W"
}
trap cleanup EXIT
unset WAYLAND_DISPLAY
export QT_QPA_PLATFORM=xcb GDK_BACKEND=x11 DISPLAY=$DSP
n=${DSP#:}
if [ ! -S /tmp/.X11-unix/X$n ]; then
  Xvfb "$DSP" -screen 0 1920x1080x24 -nolisten tcp > "$W/xvfb.log" 2>&1 &
  XPID=$!
  for i in $(seq 1 40); do [ -S /tmp/.X11-unix/X$n ] && break; sleep 0.25; done
fi
mkdir -p "$W/board" "$W/tmp"
cp -r "$R/share/demo-stickhub/." "$W/board/"
export KICAD_CONFIG_HOME=$W/cfg TMPDIR=$W/tmp
export KPNS_SOCKET=ipc://$W/tmp/kicad/api.sock PYAPI=$R/ai-pns/pyapi
(cd "$W/board" && exec "$R/bin/kicad-pns-pcbnew" StickHub.kicad_pcb > "$W/pcbnew.log" 2>&1) &
KPID=$!
ok=
for i in $(seq 1 90); do
  sleep 2
  kill -0 $KPID 2>/dev/null || { echo "pcbnew exited:"; tail -20 "$W/pcbnew.log"; exit 1; }
  "$PY" -c "
import sys; sys.path.insert(0, '$PYAPI'); import pns
pns.board_doc(pns.KiCadClient('$KPNS_SOCKET', 'smoke', '', 10000))" > /dev/null 2>&1 && { ok=1; break; }
done
[ -n "$ok" ] || { echo "API not ready after 180 s"; tail -20 "$W/pcbnew.log"; command -v xwd > /dev/null && xwd -root -display "$DSP" -out "$W/screen.xwd"; exit 1; }
echo "API ready after $((i*2)) s"
"$PY" "$H/smoke.py" "$W/saved.kicad_pcb"
