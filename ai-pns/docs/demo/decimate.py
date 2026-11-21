"""decimate.py IN_GUIDES.json OUT_GUIDES.json : keep only the anchors, the pad stub ends and the via points of each guide.
The PNS router then chooses its own 45-degree posture between them (smoothing); an A* polyline fed
vertex by vertex is reproduced as is, grid jogs included."""
import json, sys
out = []
for g in json.load(open(sys.argv[1])):
    seq = [[*g['a'], g['la']]] + g['pts'] + [[*g['b'], g['lb']]]
    keep = [i for i in range(1, len(seq) - 1)
            if i in (1, len(seq) - 2)                                       # pad stub ends (on-axis exits)
            or seq[i][2] != seq[i - 1][2] or seq[i][2] != seq[i + 1][2]]   # both ends of each layer change
    out.append(dict(g, pts=[seq[i] for i in keep]))
json.dump(out, open(sys.argv[2], 'w'), indent=1)
for g in out:
    print(g['net'], len(g['pts']), 'points kept')
