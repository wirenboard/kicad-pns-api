#!/bin/bash
# start.sh BOARD.kicad_pcb [DISPLAY_NUM] : minimal variant - run the fork's pcbnew on a private Xvfb
# (default :97) with a copy of BOARD (and BOARD's .kicad_pro if present) in $KPNS_STATE/work; prints
# "ready <socket>" once the IPC API socket exists. No dialog handling: use it with a config dir that
# has already been through the first run (e.g. one created by hoststart_n.sh). Never touches the
# user's display (WAYLAND_DISPLAY unset, GDK_BACKEND=x11).
source "$(cd "$(dirname "$0")" && pwd)/paths.sh"
[ -f "$1" ] || { echo "usage: $0 BOARD.kicad_pcb [DISPLAY_NUM]"; exit 2; }
DN=${2:-97}; WD=$KPNS_STATE/work; T=${KPNS_SOCK_PREFIX}s; C=$KPNS_STATE/hostcfg
mkdir -p "$WD" $T; kpns_config "$C"
cp "$1" "$WD/board.kicad_pcb"; P="${1%.kicad_pcb}.kicad_pro"; [ -f "$P" ] && cp "$P" "$WD/board.kicad_pro"
rm -f "$WD"/*.lck
pgrep -f "Xvfb :$DN" >/dev/null || { Xvfb :$DN -screen 0 1920x1080x24 -nolisten tcp > "$WD/xvfb.log" 2>&1 & sleep 1; }
cd "$WD"
env -u WAYLAND_DISPLAY DISPLAY=:$DN GDK_BACKEND=x11 QT_QPA_PLATFORM=xcb TMPDIR=$T \
  KICAD_CONFIG_HOME=$C KICAD_RUN_FROM_BUILD_DIR=1 LD_LIBRARY_PATH=$KPNS_HOSTLIB \
  "$KPNS_BUILD/pcbnew/pcbnew" board.kicad_pcb > "$WD/pcbnew.log" 2>&1 &
echo $! > "$WD/pcbnew.pid"
for i in $(seq 1 60); do S=$(find $T -maxdepth 3 -name "api.sock" 2>/dev/null | head -1); [ -n "$S" ] && break; sleep 2; done
[ -n "$S" ] && echo "ready ipc://$S" || { echo NO SOCKET; tail -20 "$WD/pcbnew.log"; }
