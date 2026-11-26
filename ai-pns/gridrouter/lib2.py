"""lib2.py : helpers on top of fr.py - pad stubs along the pad axis, net islands, auto-connect of
the islands of a net with the grid router (connect / task). Same coordinates and layer letters as fr.py."""
import math, fr
from shapely.geometry import Point, LineString, box

def padinfo(B, ref, num):
    p = B.pad(ref, num); f = B.b.FindFootprintByReference(ref)
    bb = p.GetBoundingBox()
    x0, x1 = fr.mm(bb.GetLeft()), fr.mm(bb.GetRight()); y0, y1 = -fr.mm(bb.GetBottom()), -fr.mm(bb.GetTop())
    c = fr.P(p.GetPosition()); L = 'B' if f.IsFlipped() else 'F'
    if p.GetDrillSizeX() > 0: L = '*'
    return c, (x0, x1, y0, y1), L, p.GetNetname()

DIRS = {'E': (1, 0), 'W': (-1, 0), 'N': (0, 1), 'S': (0, -1), 'NE': (1, 1), 'NW': (-1, 1), 'SE': (1, -1), 'SW': (-1, -1)}

def stub_pts(B, ref, num, d, extra=0.1):
    """points of an on-axis stub from pad centre to just past the pad end, plus layer"""
    c, (x0, x1, y0, y1), L, net = padinfo(B, ref, num)
    dx, dy = DIRS[d]
    if dx and not dy: e = ((x1 if dx > 0 else x0) + dx * extra, c[1])
    elif dy and not dx: e = (c[0], (y1 if dy > 0 else y0) + dy * extra)
    else: raise ValueError
    return [(c[0], c[1], L), (round(e[0], 4), round(e[1], 4), L)], net

def stub(B, ref, num, d, extra=0.1, w=0.254):
    pts, net = stub_pts(B, ref, num, d, extra)
    B.commit(net, pts, w)
    return pts[-1]

def targets(B, net, step=0.025, layers=None, exclude=None, region=None):
    """exact points on the net's tracks (centrelines) and vias; exclude: predicate(x,y,L)"""
    layers = fr.ORDER if layers is None else layers
    out = []
    for t in B.tracks(net):
        if t[0] == 'via':
            for L in layers: out.append((t[1][0], t[1][1], L))
            continue
        L, s, e, w = t
        if L not in layers: continue
        n = max(1, int(math.hypot(e[0]-s[0], e[1]-s[1]) / step))
        for k in range(n + 1):
            out.append((round(s[0] + (e[0]-s[0]) * k / n, 4), round(s[1] + (e[1]-s[1]) * k / n, 4), L))
    if exclude: out = [p for p in out if not exclude(*p)]
    if region: out = [p for p in out if region[0] <= p[0] <= region[1] and region[2] <= p[1] <= region[3]]
    return out

def show(poly):
    return ' '.join(f'({x:.3f},{y:.3f},{L})' for x, y, L in poly)

# ------------------------------------------------------------------ islands / auto connect
from shapely.ops import unary_union

def islands(B, net):
    """connected components of the net: list of dicts {trk:[(L,s,e)], via:[(x,y)], pads:[(ref,num,L)]}"""
    items = []   # (layers set, geom, desc)
    for t in B.b.GetTracks():
        if t.GetNetname() != net: continue
        if t.GetClass() == 'PCB_VIA':
            p = fr.P(t.GetPosition()); vr = fr.CFG['via_connect_radius'] if fr.CFG['via_connect_radius'] is not None else fr.mm(t.GetWidth(fr.K.F_Cu)) / 2
            items.append((set(fr.ORDER), Point(p).buffer(vr), ('via', p)))
        else:
            L = fr.LID.get(t.GetLayer())
            if not L: continue
            s, e = fr.P(t.GetStart()), fr.P(t.GetEnd())
            items.append(({L}, LineString([s, e]).buffer(fr.mm(t.GetWidth()) / 2) if s != e else Point(s).buffer(0.1), ('trk', L, s, e)))
    for f in B.b.GetFootprints():
        for p in f.Pads():
            if p.GetNetname() != net: continue
            Ls = set(L for lid, L in fr.LID.items() if p.IsOnLayer(lid))
            o = p.GetEffectivePolygon(fr.LAY[sorted(Ls)[0]]).Outline(0)
            from shapely.geometry import Polygon
            g = Polygon([(fr.mm(o.CPoint(i).x), -fr.mm(o.CPoint(i).y)) for i in range(o.PointCount())]).buffer(0)
            items.append((Ls, g, ('pad', f.GetReference(), p.GetNumber(), ''.join(sorted(Ls)))))
    n = len(items); par = list(range(n))
    def fd(a):
        while par[a] != a: par[a] = par[par[a]]; a = par[a]
        return a
    for i in range(n):
        for j in range(i + 1, n):
            if items[i][0] & items[j][0] and items[i][1].distance(items[j][1]) < 1e-4:
                par[fd(i)] = fd(j)
    comps = {}
    for i in range(n): comps.setdefault(fd(i), []).append(items[i][2])
    return list(comps.values())

EXITS = {}
def pad_exits(B, ref, num, extra=0.18):
    """candidate on-axis stubs for an SMD pad: list of (dir, pts)"""
    c, (x0, x1, y0, y1), L, net = padinfo(B, ref, num)
    if L == '*': return [('*', [(c[0], c[1], Lx)]) for Lx in fr.ORDER]
    w, h = x1 - x0, y1 - y0
    ds = ['E', 'W'] if w > h + 1e-3 else (['N', 'S'] if h > w + 1e-3 else ['E', 'W', 'N', 'S'])
    ex = EXITS.get((ref, str(num)))
    if ex: ds = [d for d in ds if d in ex]
    return [(d, stub_pts(B, ref, num, d, extra)[0]) for d in ds]

def comp_targets(B, comp, net, step=0.025):
    """targets for a component: points on tracks/vias, + stub ends for bare SMD pads. returns (pts, stubmap)"""
    pts = []; stubs = {}
    has_cu = any(it[0] in ('trk', 'via') for it in comp)
    for it in comp:
        if it[0] == 'via':
            for L in fr.ORDER: pts.append((it[1][0], it[1][1], L))
        elif it[0] == 'trk':
            _, L, s, e = it; n = max(1, int(math.hypot(e[0]-s[0], e[1]-s[1]) / step))
            for k in range(n + 1): pts.append((round(s[0] + (e[0]-s[0]) * k / n, 4), round(s[1] + (e[1]-s[1]) * k / n, 4), L))
        elif it[0] == 'pad':
            _, ref, num, Ls = it
            for d, sp in pad_exits(B, ref, num):
                if d == '*':
                    pts.append(sp[0])
                else:
                    pts.append(sp[-1]); stubs[sp[-1]] = sp
    return pts, stubs

def connect(B, net, ci=0, cj=None, w=0.254, res=0.025, m=0.012, win=None, extra_forbid=None, layers=None, viacost=40,
            turn45=1.0, turn90=8.0, commit=True, maxexp=60000000, starts=None, verbose=True):
    """route from component ci to any other component (or cj) of the net"""
    layers = ''.join(fr.ORDER) if layers is None else layers
    comps = islands(B, net)
    if len(comps) < 2: return 'connected'
    A = comps[ci]
    others = [c for k, c in enumerate(comps) if k != ci and (cj is None or k == cj)]
    spts, sstubs = comp_targets(B, A, net)
    if starts is not None: spts = starts
    tpts, tstubs = [], {}
    for c in others:
        p, s = comp_targets(B, c, net); tpts += p; tstubs.update(s)
    # A*: starts are multiple (any point of A); the grid aligns to the first start. Prefer stub ends / pad points first.
    pref = [p for p in spts if p in sstubs] or spts
    spl = pref + [p for p in spts if p not in pref]
    spl = [p for p in spl if p[2] in layers]
    tpl = [p for p in tpts if p[2] in layers]
    if win is None:
        xs = [p[0] for p in spl + tpl]; ys = [p[1] for p in spl + tpl]
        bx0, by0, bx1, by1 = B.outline.bounds   # clamp the window to the board
        win = (max(bx0, min(xs) - 3), min(bx1, max(xs) + 3), max(by0, min(ys) - 3), min(by1, max(ys) + 3))
    inw = lambda p: win[0] + 0.05 <= p[0] <= win[1] - 0.05 and win[2] + 0.05 <= p[1] <= win[3] - 0.05
    spl = [p for p in spl if inw(p)]; tpl = [p for p in tpl if inw(p)]
    if not spl or not tpl:
        if verbose: print(net, 'no terminals in window'); 
        return None
    poly = B.route(net, spl[:4000], tpl, w=w, win=win, res=res, m=m, extra_forbid=extra_forbid, layers=list(layers),
                   viacost=viacost, turn45=turn45, turn90=turn90, maxexp=maxexp)
    if poly is None:
        if verbose: print(net, 'FAIL', B.last_fail)
        return None
    # attach stubs
    s0 = poly[0]; e0 = poly[-1]
    full = poly
    if s0 in sstubs: full = sstubs[s0] + poly[1:]
    if e0 in tstubs: full = full + list(reversed(tstubs[e0]))[1:]
    if verbose: print(net, 'OK', show(full))
    if commit: B.commit(net, full, w)
    return full

def comp_index(B, net, pt=None, pad=None):
    comps = islands(B, net)
    for k, c in enumerate(comps):
        for it in c:
            if pt and it[0] == 'via' and abs(it[1][0]-pt[0]) < 1e-3 and abs(it[1][1]-pt[1]) < 1e-3: return k
            if pt and it[0] == 'trk' and any(abs(q[0]-pt[0]) < 1e-3 and abs(q[1]-pt[1]) < 1e-3 for q in (it[2], it[3])): return k
            if pad and it[0] == 'pad' and it[1] == pad[0] and str(it[2]) == str(pad[1]): return k
    return None

def task(B, net, frm=None, pad=None, to_pt=None, to_pad=None, **kw):
    ci = comp_index(B, net, pt=frm, pad=pad)
    cj = None
    if to_pt or to_pad: cj = comp_index(B, net, pt=to_pt, pad=to_pad)
    if ci is None: print(net, 'no start comp'); return None
    w = kw.pop('w', fr.CFG['power_width'] if net in fr.POWER else 0.254)
    return connect(B, net, ci=ci, cj=cj, w=w, **kw)
