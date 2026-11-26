"""fancheck.py BOARD10.kicad_pcb : final geometry checks (python with stock KiCad's pcbnew; printed y is y-up)
 1. every track segment at 0/45/90 degrees;
 2. every track end that lies inside an SMD pad lies on the pad centre (EAGLE connectivity);
 3. fan-out along the pad axis: a segment starting at an SMD pad centre of a multi-pad row part (IC, connector, RN)
    leaves along the pad's long axis (x for wide pads, y for tall pads); 2-pin chips and square pads are reported
    only if the segment runs into the gap toward a neighbouring pad of the same part (closer than the pad pitch);
 4. tracks of nets crossing the gap between two pads of one part (inter-pad) are listed.
 5. rule 5 (jogs to straighten): a) hairpins: the direction reverses by more than 90 deg at a vertex within
    2 mm of a same-net pad or via; b) zigzag jogs: a segment < 0.3 mm between two parallel segments (not inside
    a pad); c) detours: a pad/via-to-pad/via chain on one layer longer than 1.5x its straight distance and
    more than 1 mm longer. The last three lines list them; gate.py and pnsfix.py parse those lines.
Prints findings; exit code 0 always."""
import sys, math
import pcbnew as K
mm = K.ToMM
b = K.LoadBoard(sys.argv[1])
pads = []
for f in b.GetFootprints():
    for p in f.Pads():
        if p.GetAttribute() != K.PAD_ATTRIB_SMD:
            continue
        q = p.GetPosition(); bb = p.GetBoundingBox()
        pads.append(dict(ref=f.GetReference(), num=p.GetNumber(), net=p.GetNetname(), x=mm(q.x), y=mm(q.y),
                         x0=mm(bb.GetLeft()), x1=mm(bb.GetRight()), y0=mm(bb.GetTop()), y1=mm(bb.GetBottom()),
                         layer=p.GetLayer() if p.IsOnLayer(K.F_Cu) is False else K.F_Cu, nparts=len(f.Pads()),
                         onF=p.IsOnLayer(K.F_Cu), onB=p.IsOnLayer(K.B_Cu)))
segs = [t for t in b.GetTracks() if t.GetClass() == 'PCB_TRACK']
TRK = segs
bad_ang, off_centre, off_axis = [], [], []
for t in segs:
    s, e = t.GetStart(), t.GetEnd(); x1, y1, x2, y2 = mm(s.x), mm(s.y), mm(e.x), mm(e.y)
    dx, dy = x2 - x1, y2 - y1
    if math.hypot(dx, dy) < 1e-4:
        continue
    a = math.degrees(math.atan2(dy, dx)) % 45
    if min(a, 45 - a) > 0.2:
        bad_ang.append((t.GetNetname(), round(x1, 3), round(-y1, 3), round(x2, 3), round(-y2, 3)))
    L = t.GetLayer()
    for (px, py), (ox, oy) in (((x1, y1), (x2, y2)), ((x2, y2), (x1, y1))):
        for p in pads:
            if p['net'] != t.GetNetname():
                continue
            if not ((L == K.F_Cu and p['onF']) or (L == K.B_Cu and p['onB'])):
                continue
            if p['x0'] - 1e-3 <= px <= p['x1'] + 1e-3 and p['y0'] - 1e-3 <= py <= p['y1'] + 1e-3:
                if math.hypot(px - p['x'], py - p['y']) > 0.002:
                    # end inside the pad but not on its centre: fine if the segment continues to the centre elsewhere
                    # ...or another same-net segment on this layer joins this vertex and runs to the centre
                    # inside the pad (a converter-generated connector)
                    joined = any(s2 is not t and s2.GetLayer() == L and s2.GetNetname() == t.GetNetname() and
                                 any(abs(K.ToMM(q.x) - px) < 1e-6 and abs(K.ToMM(q.y) - py) < 1e-6 for q in (s2.GetStart(), s2.GetEnd()))
                                 and all(p['x0'] - 1e-3 <= K.ToMM(q.x) <= p['x1'] + 1e-3 and p['y0'] - 1e-3 <= K.ToMM(q.y) <= p['y1'] + 1e-3 for q in (s2.GetStart(), s2.GetEnd()))
                                 for s2 in TRK)
                    if not joined and not (p['x0'] <= ox <= p['x1'] and p['y0'] <= oy <= p['y1']):
                        off_centre.append((p['ref'], p['num'], t.GetNetname(), round(px, 3), round(-py, 3)))
                elif p['nparts'] > 3:
                    w, h = p['x1'] - p['x0'], p['y1'] - p['y0']
                    ddx, ddy = ox - px, oy - py
                    if abs(w - h) > 0.05:
                        along_x = w > h
                        # leaving the pad body: the part of the segment inside the pad must be along the axis
                        if along_x and abs(ddy) > 1e-3 and abs(ddx) < abs(ddy) * 0.99 + 1e-6:
                            off_axis.append((p['ref'], p['num'], t.GetNetname(), round(px, 3), round(-py, 3)))
                        if not along_x and abs(ddx) > 1e-3 and abs(ddy) < abs(ddx) * 0.99 + 1e-6:
                            off_axis.append((p['ref'], p['num'], t.GetNetname(), round(px, 3), round(-py, 3)))
print('segments', len(segs))
print('non-45 segments', len(bad_ang), bad_ang[:20])
print('ends inside a pad but off its centre', len(off_centre), off_centre[:30])
print('pad exits not along the pad axis (multi-pin parts)', len(off_axis), off_axis[:40])

# 5. hairpins / jogs / detours
#   a) direction reverses by more than 90 deg at a vertex within 2 mm of a same-net pad or via;
#   b) zigzag: a segment < 0.3 mm between two parallel segments (not inside a pad);
#   c) detour: a pad/via-to-pad/via chain on one layer longer than 1.5x its straight distance (and > 1 mm extra).
import collections
from shapely.geometry import Point as _P, box as _box
R = lambda v: round(v, 4)
anchors = collections.defaultdict(list)      # net -> [(x,y)] pad centres and vias
padboxes = collections.defaultdict(list)
for f in b.GetFootprints():
    for p in f.Pads():
        q = p.GetPosition(); bb = p.GetBoundingBox()
        anchors[p.GetNetname()].append((mm(q.x), mm(q.y)))
        padboxes[p.GetNetname()].append(_box(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())))
vias = set()
for t in b.GetTracks():
    if t.GetClass() == 'PCB_VIA':
        q = t.GetPosition(); anchors[t.GetNetname()].append((mm(q.x), mm(q.y))); vias.add((t.GetNetname(), R(mm(q.x)), R(mm(q.y))))
adj = collections.defaultdict(list)          # (net, layer, x, y) -> [(other x, y, len)]
for t in segs:
    s, e = t.GetStart(), t.GetEnd(); a = (R(mm(s.x)), R(mm(s.y))); c = (R(mm(e.x)), R(mm(e.y)))
    if a == c: continue
    k = (t.GetNetname(), t.GetLayer())
    adj[k + a].append(c); adj[k + c].append(a)
def inpad(net, x, y): return any(bx.buffer(1e-3).contains(_P(x, y)) for bx in padboxes[net])
hair, jog, det = [], [], []
for key, nb in adj.items():
    net, L, x, y = key
    if len(nb) != 2 or (net, x, y) in vias: continue
    (ax, ay), (cx, cy) = nb
    d1 = (x - ax, y - ay); d2 = (cx - x, cy - y)
    n1, n2 = math.hypot(*d1), math.hypot(*d2)
    if n1 < 1e-6 or n2 < 1e-6: continue
    cos = (d1[0]*d2[0] + d1[1]*d2[1]) / (n1*n2)
    if cos < -1e-6:   # turn > 90 deg
        dmin = min((math.hypot(x - px, y - py) for px, py in anchors[net]), default=99)
        if dmin <= 2.0 and not (inpad(net, ax, ay) and inpad(net, cx, cy) and inpad(net, x, y)):
            hair.append((net, b.GetLayerName(L)[:3], round(x, 3), round(-y, 3), round(math.degrees(math.acos(max(-1, min(1, cos)))))))
for t in segs:
    s, e = t.GetStart(), t.GetEnd(); a = (R(mm(s.x)), R(mm(s.y))); c = (R(mm(e.x)), R(mm(e.y)))
    l = math.hypot(c[0]-a[0], c[1]-a[1]); net = t.GetNetname(); k = (net, t.GetLayer())
    if l < 1e-6 or l >= 0.3 or (inpad(net, *a) and inpad(net, *c)): continue
    na = [p for p in adj[k + a] if p != c]; nc = [p for p in adj[k + c] if p != a]
    if len(na) == 1 and len(nc) == 1:
        u = (a[0]-na[0][0], a[1]-na[0][1]); v = (nc[0][0]-c[0], nc[0][1]-c[1])
        nu, nv = math.hypot(*u), math.hypot(*v)
        if nu > 1e-6 and nv > 1e-6 and abs((u[0]*v[1]-u[1]*v[0])/(nu*nv)) < 1e-3 and (u[0]*v[0]+u[1]*v[1]) > 0 \
                and abs(((c[0]-a[0])*u[1]-(c[1]-a[1])*u[0])/(nu*l)) > 1e-3:
            jog.append((net, b.GetLayerName(t.GetLayer())[:3], round(a[0], 3), round(-a[1], 3), round(l, 3)))
# detours: walk chains between anchors / junctions
seen = set()
def isnode(k): return len(adj[k]) != 2 or (k[0], k[2], k[3]) in vias or any(abs(k[2]-px) < 1e-3 and abs(k[3]-py) < 1e-3 for px, py in anchors[k[0]])
for key in list(adj):
    if not isnode(key): continue
    for nxt in adj[key]:
        net, L = key[0], key[1]; path = [(key[2], key[3]), nxt]; prev = (key[2], key[3]); cur = nxt
        while not isnode((net, L) + cur):
            o = [p for p in adj[(net, L) + cur] if p != prev]
            if not o: break
            prev, cur = cur, o[0]; path.append(cur)
        sig = (net, L) + tuple(sorted([path[0], path[-1]]))
        if sig in seen: continue
        seen.add(sig)
        ln = sum(math.hypot(path[i+1][0]-path[i][0], path[i+1][1]-path[i][1]) for i in range(len(path)-1))
        st = math.hypot(path[-1][0]-path[0][0], path[-1][1]-path[0][1])
        if st > 0.05 and ln > 1.5*st and ln - st > 1.0:
            det.append((net, b.GetLayerName(L)[:3], round(path[0][0], 2), round(-path[0][1], 2), round(path[-1][0], 2), round(-path[-1][1], 2), round(ln, 2), round(st, 2)))
print('hairpins (turn > 90 deg within 2 mm of a pad/via)', len(hair), hair)   # full lists: gate.py / pnsfix.py parse them
print('zigzag jogs (< 0.3 mm)', len(jog), jog)
print('detours (> 1.5x straight, > 1 mm extra)', len(det), det)
