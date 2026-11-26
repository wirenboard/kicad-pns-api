"""polyfix.py IN OUT --net NET --layer L --old "x,y;x,y;..." --new "x,y;x,y;..." [options] : replace one track
polyline of a net by a computed one (stock pcbnew; mm, y up).

--old lists the vertices of the chain to remove; every consecutive pair must exist as a segment of NET on
layer L (F, B, 1..30 = In1..In30, or a KiCad layer name). --new is the replacement; its ends should be the
old ends or vertices shared with the rest of the net. New vertices within 2 um of an existing vertex (old
chain ends, --split points) are snapped onto it exactly, so the result stays connected nm-exactly.
Width of each new segment = width of the old segment it overlaps most (--width overrides).
  --via-move "x,y>x2,y2"  (repeatable) move a via of NET and every NET track end on it (any layer) first
  --split x,y             (repeatable) split the NET segment on layer L passing through x,y there (a T junction
                          for the new chain to start from)
The tool does not judge the result: run gate.py OLD NEW NET (or kicad-cli DRC) on OUT.
"""
import argparse

ap = argparse.ArgumentParser(description=__doc__.split('\n')[0], epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('inp', metavar='IN')
ap.add_argument('out', metavar='OUT')
ap.add_argument('--net', required=True)
ap.add_argument('--layer', required=True)
ap.add_argument('--old', required=True)
ap.add_argument('--new', required=True)
ap.add_argument('--width', type=float)
ap.add_argument('--via-move', action='append', default=[])
ap.add_argument('--split', action='append', default=[])
A = ap.parse_args()

import pcbnew as K  # noqa: E402
from shapely.geometry import LineString  # noqa: E402

mm = K.ToMM; F = K.FromMM
NET = A.net
b = K.LoadBoard(A.inp)
lname = {'F': 'F.Cu', 'B': 'B.Cu'}.get(A.layer, f'In{A.layer}.Cu' if A.layer.isdigit() else A.layer)
LAYER = b.GetLayerID(lname)
if LAYER < 0:
    raise SystemExit(f'unknown layer {A.layer}')
parse = lambda s: [tuple(float(v) for v in p.split(',')) for p in s.split(';') if p]
OLD, NEW = parse(A.old), parse(A.new); W = A.width
P = lambda q: (mm(q.x), -mm(q.y))
V = lambda x, y: K.VECTOR2I(F(x), F(-y))
near = lambda a, c: abs(a[0] - c[0]) < 2e-3 and abs(a[1] - c[1]) < 2e-3
old = []
for i in range(len(OLD) - 1):
    p, q = OLD[i], OLD[i + 1]; hit = None
    for t in b.GetTracks():
        if t.GetClass() == 'PCB_TRACK' and t.GetNetname() == NET and t.GetLayer() == LAYER:
            s, e = P(t.GetStart()), P(t.GetEnd())
            if (near(s, p) and near(e, q)) or (near(s, q) and near(e, p)):
                hit = t; break
    if hit is None:
        raise SystemExit(f'segment not found: {p} - {q}')
    old.append(hit)
for mv in A.via_move:
    a, c = mv.split('>'); a = tuple(map(float, a.split(','))); c = tuple(map(float, c.split(',')))
    nv = 0
    for t in b.GetTracks():
        if t.GetNetname() != NET:
            continue
        if t.GetClass() == 'PCB_VIA':
            if near(P(t.GetPosition()), a):
                t.SetPosition(V(*c)); nv += 1
        else:
            if near(P(t.GetStart()), a):
                t.SetStart(V(*c))
            if near(P(t.GetEnd()), a):
                t.SetEnd(V(*c))
    if nv != 1:
        raise SystemExit(f'via not found: {a}')
SPL = []
for sp in A.split:
    x, y = map(float, sp.split(',')); done = 0
    for t in list(b.GetTracks()):
        if t.GetClass() != 'PCB_TRACK' or t.GetNetname() != NET or t.GetLayer() != LAYER:
            continue
        g = LineString([P(t.GetStart()), P(t.GetEnd())])
        if g.distance(LineString([(x, y), (x, y + 1e-9)])) < 2e-3 and not near(P(t.GetStart()), (x, y)) and not near(P(t.GetEnd()), (x, y)):
            sx = t.GetStart()
            if abs(sx.x - t.GetEnd().x) < 2:   # vertical / horizontal segment: keep the split on its axis exactly
                x = mm(sx.x)
            if abs(sx.y - t.GetEnd().y) < 2:
                y = -mm(sx.y)
            e = K.VECTOR2I(t.GetEnd()); t.SetEnd(V(x, y)); SPL.append(K.VECTOR2I(t.GetEnd()))
            nt = K.PCB_TRACK(b); nt.SetStart(V(x, y)); nt.SetEnd(e); nt.SetWidth(t.GetWidth()); nt.SetLayer(LAYER)
            nt.SetNet(t.GetNet()); b.Add(nt); done += 1
            break
    if done != 1:
        raise SystemExit(f'split failed: {sp}')
ex = list(SPL)
for t in old:
    ex += [t.GetStart(), t.GetEnd()]


def snap(p):
    for q in ex:
        if near(P(q), p):
            return P(q)
    return p


NEW = [snap(p) for p in NEW]
oldg = [(LineString([P(t.GetStart()), P(t.GetEnd())]), t.GetWidth()) for t in old]
for t in old:
    b.Remove(t)
net = b.FindNet(NET)
for i in range(len(NEW) - 1):
    p, q = NEW[i], NEW[i + 1]
    g = LineString([p, q])
    w = F(W) if W else max(oldg, key=lambda o: o[0].buffer(0.05).intersection(g).length)[1]
    nt = K.PCB_TRACK(b); nt.SetStart(K.VECTOR2I(F(p[0]), -F(p[1]))); nt.SetEnd(K.VECTOR2I(F(q[0]), -F(q[1])))
    nt.SetWidth(w); nt.SetLayer(LAYER); nt.SetNet(net); b.Add(nt)
K.SaveBoard(A.out, b)
print('replaced', len(old), 'by', len(NEW) - 1)
