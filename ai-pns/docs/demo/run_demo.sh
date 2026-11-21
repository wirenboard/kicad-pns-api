#!/bin/bash
# run_demo.sh [OUTDIR] : the whole demo of docs/ROUTING_RECIPE.md on the synthetic board, end to end.
#   needs: a fork build ($KPNS_BUILD), $KPNS_PY (protobuf 5.29 + pynng), stock KiCad 10 (python3 -c 'import pcbnew',
#   kicad-cli), numpy/scipy/shapely/pillow for the grid router, and gridrouter/libastar.so built:
#     cc -O2 -shared -fPIC -o ../../gridrouter/libastar.so ../../gridrouter/astar.c -lm
#   DEMO_N   instance number for host/hoststart_n.sh (default 1). The demo restarts ITS OWN instance
#            with --force between steps, so pick an N nobody else uses.
set -e
H=$(cd "$(dirname "$0")" && pwd); AI=$H/../..
source "$AI/host/paths.sh"
export DEMO_N=${DEMO_N:-1}
START=${HOSTSTART:-$AI/host/hoststart_n.sh}; STOP=${HOSTSTOP:-$AI/host/hoststop_n.sh}
O=$(mkdir -p "${1:-demo_out}" && cd "${1:-demo_out}" && pwd)
S=ipc://$KPNS_SOCK_PREFIX$DEMO_N/kicad/api.sock
cp "$H/demo.kicad_pro" "$H/demo.kicad_dru" "$O/"
cd "$H"

echo "== 1. board + project rules"
python3 make_demo.py "$O/demo.kicad_pcb"

echo "== 2. pre-route: bundle + differential pair (RouteTrack)"
"$START" $DEMO_N "$O/demo.kicad_pcb" "$O/demo.kicad_pro"
"$KPNS_PY" route_core.py
"$KPNS_PY" "$AI/tools/save.py" $S "$O/core.kicad_pcb"
python3 "$AI/tools/k10.py" "$O/demo.kicad_pcb" "$O/core.kicad_pcb" "$O/core10.kicad_pcb"

echo "== 3. A* guides (low turn cost, to show the grid artefacts)"
python3 plan_astar.py "$O/core10.kicad_pcb" "$O/astar10.kicad_pcb" "$O/guides.json" 0 0 8
python3 decimate.py "$O/guides.json" "$O/guides_dec.json"
python3 plot_astar.py "$O/core10.kicad_pcb" "$O/astar_map.png"

echo "== 4. the raw A* copper, as committed"
"$START" $DEMO_N "$O/astar10.kicad_pcb" "$O/demo.kicad_pro" --force
"$KPNS_PY" stats.py SIG1,SIG2,SIG7,SIG8,CTRL
"$KPNS_PY" drc_list.py > "$O/drc_astar.txt"; tail -1 "$O/drc_astar.txt"

echo "== 5. PNS from the decimated guides, then the full guides for whatever is still open"
"$START" $DEMO_N "$O/core10.kicad_pcb" "$O/demo.kicad_pro" --force
"$KPNS_PY" "$AI/tools/drive.py" "$O/guides_dec.json" --socket $S --layers F.Cu,B.Cu
"$KPNS_PY" "$AI/tools/drive.py" "$O/guides.json" --socket $S --layers F.Cu,B.Cu
"$KPNS_PY" -c "
from common import connect, pns
c, d = connect()
print('cleanup changes', len(pns.cleanup_tracks(c, d, nets=['SIG1', 'SIG2', 'SIG7', 'SIG8', 'CTRL'], merge=True,
      dangling=True, redundant_vias=True, dangling_vias=True)))"
"$KPNS_PY" stats.py SIG1,SIG2,SIG7,SIG8,CTRL
"$KPNS_PY" drc_list.py > "$O/drc_pns.txt"; tail -1 "$O/drc_pns.txt"
"$KPNS_PY" "$AI/tools/save.py" $S "$O/routed.kicad_pcb"

echo "== 6. gates on a stock 10.0 copy"
(cd "$O" && bash "$AI/tools/cdrc.sh" routed.kicad_pcb routed_check demo.kicad_pcb)
python3 "$AI/tools/fancheck.py" "$O/routed_check.kicad_pcb"

echo "== 7. shove demo on the pre-routed board"
"$START" $DEMO_N "$O/core10.kicad_pcb" "$O/demo.kicad_pro" --force
"$KPNS_PY" shove_demo.py --undo
"$STOP" $DEMO_N --xvfb
