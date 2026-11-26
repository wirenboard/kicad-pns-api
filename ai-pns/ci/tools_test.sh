#!/bin/bash
# tools_test.sh [WORKDIR] : headless test of the board-editing tools (mincut, pocket, polyfix, chains, gate,
# fancheck, lockcopy) on the StickHub demo board (demos/stickhub) with stock KiCad 10 (pcbnew python
# module + kicad-cli), numpy, scipy, shapely and pillow. pnsfix.py needs a running fork instance and is
# only checked for --help here. Exit 0 when every check passes.
set -u
H=$(cd "$(dirname "$0")" && pwd)
T=$H/../tools
SRC=${KPNS_DEMO:-$H/../../demos/stickhub}
W=${1:-$(mktemp -d /tmp/kpns-tools.XXXXXX)}
PY=${KPNS_STOCK_PY:-python3}
CFG=$H/tools_demo.json
mkdir -p "$W"
cp "$SRC/StickHub.kicad_pcb" "$SRC/StickHub.kicad_pro" "$W/"
B=$W/StickHub.kicad_pcb
fails=()
check() {   # check NAME COMMAND... : PASS when the command exits 0
  local name=$1; shift
  if "$@" > "$W/$name.log" 2>&1; then echo "PASS $name"; else echo "FAIL $name"; tail -15 "$W/$name.log"; fails+=("$name"); fi
}
has() { grep -q -- "$2" "$W/$1.log"; }
quiet() { grep -v -E 'assert "|Debug:|swig/python detected' "$@"; }

for t in mincut pocket polyfix gate pnsfix; do
  check "help_$t" "$PY" "$T/$t.py" --help
done
check help_chains "$PY" "$T/chains.py" --help
check help_lockcopy "$PY" "$T/lockcopy.py" --help

# pocket: strip the USB data and connector nets in the south of the board and re-route them
check pocket "$PY" "$T/pocket.py" "$B" --box 141,159,-120,-108 --nets '/D+,/D-,Net-(J1-Pin_1)' --orders 2 \
  --config "$CFG" --out "$W/pk"
check pocket_zero has pocket '^ZERO 0'

# pocket with part moves, legality only: D22 0.25 mm south is legal, C14 0.25 mm east hits the mounting hole
check pocket_move "$PY" "$T/pocket.py" "$B" --box 141,159,-120,-104 --nets '/D-' --move D22:0,-0.25 --legal-only --config "$CFG" --out "$W/pkm"
check pocket_move_legal has pocket_move '^LEGAL'
"$PY" "$T/pocket.py" "$B" --box 141,159,-120,-104 --nets '/D+' --move C14:0.25,0 --legal-only --config "$CFG" --out "$W/pki" > "$W/pocket_illegal_out.log" 2>&1
check pocket_illegal_rc test $? = 3   # $? = exit code of the pocket.py line above (3 = illegal move)
check pocket_illegal has pocket_illegal_out '^ILLEGAL'

# rotated move: C28 turned to 90 deg (illegal here); its GND escape must still end on the turned GND pad
"$PY" "$T/pocket.py" "$B" --box 141,159,-120,-104 --nets 'Net-(U2-CAP)' --move C28:0,0,90 --config "$CFG" --out "$W/pkr" > "$W/pocket_rot_out.log" 2>&1
check pocket_rot_rc test $? = 3   # $? = exit code of the pocket.py line above
check pocket_rot_escape "$PY" - "$W/pkr_illegal.kicad_pcb" <<'EOF'
import sys, pcbnew as K
b = K.LoadBoard(sys.argv[1]); f = b.FindFootprintByReference('C28')
q = [p for p in f.Pads() if p.GetNetname() == 'GND'][0].GetPosition()
n = sum(1 for t in b.GetTracks() if t.GetNetname() == 'GND' and t.GetClass() == 'PCB_TRACK' and q in (t.GetStart(), t.GetEnd()))
sys.exit(0 if f.GetOrientationDegrees() == 90 and n == 2 else 1)
EOF

# unknown and frozen nets are refused with exit 2
"$PY" "$T/pocket.py" "$B" --box 141,159,-120,-104 --nets 'NOSUCH' --config "$CFG" --out "$W/pkn" > "$W/nosuch_out.log" 2>&1
check pocket_nosuch_rc test $? = 2   # $? = exit code of the pocket.py line above
"$PY" "$T/mincut.py" "$B" "$W/x.kicad_pcb" --nets 'NOSUCH' --config "$CFG" > "$W/nosuch2_out.log" 2>&1
check mincut_nosuch_rc test $? = 2   # $? = exit code of the mincut.py line above
"$PY" "$T/pocket.py" "$B" --box 141,159,-120,-104 --nets 'VIN' --config "$CFG" --out "$W/pkf" > "$W/frozen_out.log" 2>&1
check pocket_frozen_rc test $? = 2   # $? = exit code of the pocket.py line above

# mincut: open /D- (delete its copper south of the connector cap) and close it again
"$PY" - "$B" "$W/open.kicad_pcb" <<'EOF' 2>&1 | quiet
import sys, pcbnew as K
b = K.LoadBoard(sys.argv[1]); n = 0
for t in list(b.GetTracks()):
    if t.GetNetname() == '/D-' and t.GetClass() == 'PCB_TRACK' and -K.ToMM(max(t.GetStart().y, t.GetEnd().y)) > -116 \
            and -K.ToMM(min(t.GetStart().y, t.GetEnd().y)) < -108:
        b.Remove(t); n += 1
K.SaveBoard(sys.argv[2], b); print('removed', n)
EOF
check mincut "$PY" "$T/mincut.py" "$W/open.kicad_pcb" "$W/mc.kicad_pcb" --nets /D- --config "$CFG" --nperm 2 --rounds 1
check mincut_better has mincut "^ACCEPT r0 /D-"

# chains + polyfix: re-write the first jog chain with its own vertices (connectivity and widths kept)
check chains "$PY" "$T/chains.py" "$B" "$W/chains.json"
read -r NET LAY PTS < <("$PY" -c "
import json; c = [c for c in json.load(open('$W/chains.json')) if c['net'] != 'GND'][0]
print(c['net'], c['layer'], ';'.join('%.6f,%.6f' % tuple(p) for p in c['pts']))")
check polyfix "$PY" "$T/polyfix.py" "$B" "$W/pf.kicad_pcb" --net "$NET" --layer "$LAY" --old "$PTS" --new "$PTS"
check polyfix_same "$PY" - "$B" "$W/pf.kicad_pcb" <<'EOF'
import sys, collections, pcbnew as K
def k(t):
    if t.GetClass() == 'PCB_VIA': return ('v', t.GetNetname(), t.GetPosition().x, t.GetPosition().y)
    return ('t', t.GetNetname(), t.GetLayer(), t.GetWidth(), tuple(sorted([(t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y)])))
a, b = (collections.Counter(k(t) for t in K.LoadBoard(p).GetTracks()) for p in sys.argv[1:3])
sys.exit(0 if a == b else 1)
EOF

# gate: the unchanged board passes (rule 5 needs a jog fewer, so it is off here) ...
check gate_pass "$PY" "$T/gate.py" "$B" "$W/pf.kicad_pcb" "$NET" --config "$CFG" --no-rule5
# ... a width change of a frozen net is rejected
read -r A0 < <("$PY" -c "
import pcbnew as K
t = [t for t in K.LoadBoard('$B').GetTracks() if t.GetNetname() == 'VIN' and t.GetClass() == 'PCB_TRACK' and t.GetLayer() == K.B_Cu][0]
s, e = t.GetStart(), t.GetEnd(); print('%.6f,%.6f;%.6f,%.6f' % (K.ToMM(s.x), -K.ToMM(s.y), K.ToMM(e.x), -K.ToMM(e.y)))" 2>/dev/null)
"$PY" "$T/polyfix.py" "$B" "$W/frozen.kicad_pcb" --net VIN --layer B --old "$A0" --new "$A0" --width 0.25 > "$W/frozen_edit.log" 2>&1
"$PY" "$T/gate.py" "$B" "$W/frozen.kicad_pcb" --config "$CFG" > "$W/gate_reject_out.log" 2>&1
rc=$?   # exit code of gate.py (1 = reject)
check gate_reject_rc test $rc = 1
check gate_reject_reason has gate_reject_out 'frozen net changed'

# lockcopy: lock flags follow the reference board
check lockcopy "$PY" "$T/lockcopy.py" "$B" "$W/pf.kicad_pcb" "$W/lc.kicad_pcb"

echo
if [ ${#fails[@]} = 0 ]; then echo "ALL PASS"; [ -z "${1:-}" ] && rm -rf "$W"; exit 0; fi
echo "FAILED: ${fails[*]} (logs in $W)"; exit 1
