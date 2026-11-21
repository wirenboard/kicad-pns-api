"""plan_astar.py BOARD10 OUT_RAW10 GUIDES.json [TURN45 TURN90 VIACOST] : grid A* (gridrouter/fr.py)
   writes OUT_RAW10 (A* copper committed as is) and GUIDES.json for tools/drive.py"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "gridrouter"))
import fr, lib2
fr.configure(layers=[['F', 'F.Cu'], ['B', 'B.Cu']], clearance_track_track=0.2032, clearance_track_pad=0.2286,
             clearance_edge=0.254, via_diameter=0.7, via_drill=0.3)
B = fr.Brd(sys.argv[1])
TURN45, TURN90, VIACOST = (float(v) for v in (sys.argv[4:7] or (1.0, 8.0, 40)))
WIN = (100.5, 144.5, -127.5, -100.5)
TASKS = [('SIG1', ('U1', '16'), ('J1', '1'), 'F'), ('SIG2', ('U1', '15'), ('J1', '2'), 'F'),
         ('SIG7', ('U1', '10'), ('J1', '7'), 'F'), ('SIG8', ('U1', '9'), ('J1', '8'), 'F'),
         ('CTRL', ('U1', '1'), ('R2', '1'), 'FB'), ('CTRL', ('R2', '1'), ('C1', '2'), 'FB')]
LI = {'F': 0, 'B': 1}
guides = []
for net, a, b, lay in TASKS:
    p = lib2.task(B, net, pad=a, to_pad=b, commit=True, win=WIN, layers=lay, turn45=TURN45, turn90=TURN90, viacost=VIACOST)
    if not p:
        continue
    # fr.py: y up, layer letters  ->  drive.py: KiCad y down, layer indices into --layers F.Cu,B.Cu
    guides.append({'net': net, 'w': 0.254, 'a': [p[0][0], -p[0][1]], 'la': LI[p[0][2]],
                   'b': [p[-1][0], -p[-1][1]], 'lb': LI[p[-1][2]],
                   'pts': [[x, -y, LI[L]] for x, y, L in p[1:-1]]})
B.save(sys.argv[2])
print('clearance check', B.check())
json.dump(guides, open(sys.argv[3], 'w'), indent=1)
