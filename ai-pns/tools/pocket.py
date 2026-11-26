"""pocket.py IN --box x0,x1,y0,y1 --nets A,B [options] : strip a window and re-route its nets in many orders
(grid router, stock pcbnew), optionally with small part moves.

  1. --move REF:dx,dy[,rot] (repeatable): the part is translated by (dx, dy) mm (y up), rot = absolute
     orientation in degrees. Escape chains of its pads (tracks from the pad centre up to and including the
     first via) move with it on plane nets (the via lands at the new place); on other nets they are deleted
     and the net joins the pocket (--keep-via keeps the escape via and re-stitches pad -> via). Copper of
     other nets under a moved pad is ripped and its net joins the pocket (never plane/protected/--freeze
     nets; --no-rip turns this off). Legality: moved pads keep the track-pad clearance to other-net copper
     (holes: config pocket.move_hole_clearance), the edge clearance, the same-side courtyard overlap must not
     grow, and the moved plane copper must add no clearance finding. Illegal -> "ILLEGAL ..." and exit 2.
  2. strip: every non-reserved track/via of the pocket nets whose ends all lie inside --box is deleted
     (--strip-reserved also strips reserved copper).
  3. route: the open pocket nets are connected directly (fr A*, window = --box grown by --grow, widths from
     width_rules, widest first) in --orders orders: the first as given (nets of a config pair are kept back
     to back), then random permutations (--seed). Every order is scored by the total open count of the pocket
     nets; the best board is PREFIX_best.kicad_pcb (PREFIX_strip.kicad_pcb = the stripped start); with
     --save-max N every order with <= N opens is saved as PREFIX_oK.kicad_pcb. Stops at the first zero.
--forbid L:x0,x1,y0,y1 (repeatable) keeps all pocket routes out of a rectangle on layer L, to steer a
hand-guided order (with --orders 1). --legal-only stops after the legality check.

Board knowledge from --config (see routecfg.py): plane_nets, protected_nets, reservations, pad_exits,
pairs, width_rules (section "pocket" overrides), window.
"""
import argparse
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import routecfg as rc  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__.split('\n')[0], epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('inp', metavar='IN', help='stock KiCad 10 board')
ap.add_argument('--box', required=True, help='x0,x1,y0,y1 pocket (mm, y up)')
ap.add_argument('--nets', required=True, help='comma-separated pocket nets (first order = this order)')
rc.add_config_arg(ap)
ap.add_argument('--orders', type=int, default=10, help='number of route orders (default 10)')
ap.add_argument('--seed', type=int, default=1)
ap.add_argument('--out', default='pocket', help='output prefix (default ./pocket)')
ap.add_argument('--grow', type=float, default=3.0, help='routing window = box grown by this (default 3 mm)')
ap.add_argument('--move', action='append', default=[], metavar='REF:dx,dy[,rot]')
ap.add_argument('--keep-via', action='store_true', help='moves: keep the escape via of signal pads')
ap.add_argument('--no-rip', action='store_true', help='moves: do not rip other-net copper under moved pads')
ap.add_argument('--freeze', default='', help='nets never ripped under moved pads (comma-separated)')
ap.add_argument('--strip-reserved', action='store_true', help='strip reserved copper too')
ap.add_argument('--thin', default='', help='nets that may fall back to the default (signal) widths')
ap.add_argument('--forbid', action='append', default=[], metavar='L:x0,x1,y0,y1', help='rectangle kept free of routes')
ap.add_argument('--save-max', type=int, default=-1, help='also save every order with <= N opens')
ap.add_argument('--legal-only', action='store_true')
A = ap.parse_args()

fr, lib2 = rc.gridrouter()
import pcbnew as K  # noqa: E402
from shapely.geometry import Polygon, box  # noqa: E402

mm = K.ToMM
cfg = rc.Config(A.config, 'pocket')
cfg.apply_fr(fr)
BX = rc.floats(A.box, 4); NETS = rc.csv(A.nets); random.seed(A.seed)
MOVES = [(a.split(':')[0], rc.floats(a.split(':')[1])) for a in A.move]
RES = rc.reservations(cfg)
PLANE = cfg.nets('plane_nets')
B = fr.Brd(A.inp)
rc.apply_pad_exits(cfg, B, lib2)
G = A.grow
W0 = rc.window(cfg, B)
WIN = (max(W0[0], BX[0] - G), min(W0[1], BX[1] + G), max(W0[2], BX[2] - G), min(W0[3], BX[3] + G))
EF = {}
for f in A.forbid:
    L, r = f.split(':'); x0, x1, y0, y1 = rc.floats(r, 4); EF.setdefault(L, []).append(box(x0, y0, x1, y1))
EF = EF or None


def at(p, q, e=0.02): return abs(p[0] - q[0]) < e and abs(p[1] - q[1]) < e


def chain(pc, net):
    """tracks from the pad centre up to and incl. the first via (never past it); keys are KIIDs (SWIG wrapper
    ids are not stable)"""
    out = []; pts = [pc]; seen = set(); first = True
    for _ in range(12):
        tr = list(B.b.GetTracks())
        vias = [t for t in tr if t.GetClass() == 'PCB_VIA' and t.GetNetname() == net and t.m_Uuid.AsString() not in seen
                and any(at(fr.P(t.GetPosition()), p) for p in pts)]
        stop = set()
        for v in vias:
            seen.add(v.m_Uuid.AsString()); out.append(v)
            if not first:
                stop.add(tuple(round(c, 3) for c in fr.P(v.GetPosition())))
        pts = [p for p in pts if not any(at(p, q) for q in stop)]
        first = False
        nxt = []
        for t in tr:
            if t.GetClass() == 'PCB_VIA' or t.GetNetname() != net or t.m_Uuid.AsString() in seen:
                continue
            s, e = fr.P(t.GetStart()), fr.P(t.GetEnd())
            if any(at(s, p) for p in pts) or any(at(e, p) for p in pts):
                o = e if any(at(s, p) for p in pts) else s
                seen.add(t.m_Uuid.AsString()); out.append(t); nxt.append(o)
        if not nxt:
            break
        pts = nxt
    return out


def crt(fp):
    c = fp.GetCourtyard(K.B_CrtYd if fp.IsFlipped() else K.F_CrtYd)
    if c.OutlineCount() == 0:
        return None
    o = c.Outline(0)
    return Polygon([(mm(o.CPoint(i).x), -mm(o.CPoint(i).y)) for i in range(o.PointCount())]).buffer(0)


def ovl(ref):
    f = B.b.FindFootprintByReference(ref); me = crt(f); tot = 0
    if me is None:
        return 0
    for g in B.b.GetFootprints():
        if g.GetReference() == ref or g.IsFlipped() != f.IsFlipped():
            continue
        e = crt(g)
        if e is not None:
            tot += me.intersection(e).area
    return tot


base_ovl = {r: ovl(r) for r, _ in MOVES}
moved_nets = set()
for ref, mvv in MOVES:
    dx, dy = mvv[:2]
    f = B.b.FindFootprintByReference(ref)
    if f is None:
        raise SystemExit(f'--move: no footprint {ref}')
    for p in f.Pads():
        net = p.GetNetname()
        if not net:
            continue
        ch = chain(fr.P(p.GetPosition()), net)
        if net in PLANE:
            for t in ch:
                if t.GetClass() == 'PCB_VIA':
                    t.SetPosition(fr.V(fr.P(t.GetPosition())[0] + dx, fr.P(t.GetPosition())[1] + dy))
                else:
                    s, e = fr.P(t.GetStart()), fr.P(t.GetEnd())
                    t.SetStart(fr.V(s[0] + dx, s[1] + dy)); t.SetEnd(fr.V(e[0] + dx, e[1] + dy))
        else:
            for t in ch:
                if A.keep_via and t.GetClass() == 'PCB_VIA':
                    continue
                B.b.Delete(t)
            moved_nets.add(net)
    x, y = fr.P(f.GetPosition()); f.SetPosition(fr.V(x + dx, y + dy))
    if len(mvv) > 2:
        f.SetOrientationDegrees(mvv[2])
B.load_geom()
PROTN = PLANE | cfg.nets('protected_nets') | set(rc.csv(A.freeze))
ripped = 0
if not A.no_rip:
    for ref, _ in MOVES:
        myp = [it for it in B.items if it[2] == 'pad' and isinstance(it[4], tuple) and it[4][0] == ref]
        kill = {}
        for (L, nn, k, g, r, smd) in myp:
            for (L2, n2, k2, g2, r2, smd2) in B.items:
                if L2 != L or n2 == nn or k2 not in ('trk', 'via') or n2 in PROTN:
                    continue
                if g.distance(g2) < fr.CTP - 1e-4:
                    kill[r2.m_Uuid.AsString()] = (r2, n2)
        for u, (t, n2) in kill.items():
            B.b.Delete(t); ripped += 1; moved_nets.add(n2)
        if kill:
            B.load_geom()
for n in sorted(moved_nets):
    if n not in NETS:
        NETS.append(n)


def inb(p): return BX[0] <= p[0] <= BX[1] and BX[2] <= p[1] <= BX[3]


n = 0
for t in list(B.b.GetTracks()):
    if t.GetNetname() not in NETS or (rc.key(t) in RES and not A.strip_reserved):
        continue
    ps = [fr.P(t.GetPosition())] if t.GetClass() == 'PCB_VIA' else [fr.P(t.GetStart()), fr.P(t.GetEnd())]
    if all(inb(p) for p in ps):
        B.b.Delete(t); n += 1
B.load_geom()
if MOVES:
    HOLE = cfg.get('move_hole_clearance', fr.CFG['clearance_hole'])
    bad = []
    for ref, _ in MOVES:
        o = ovl(ref)
        if o > base_ovl[ref] + 1e-3:
            bad.append(f'{ref} courtyard overlap {base_ovl[ref]:.3f}->{o:.3f}')
        myp = [it for it in B.items if it[2] == 'pad' and isinstance(it[4], tuple) and it[4][0] == ref]
        for (L, nn, k, g, r, smd) in myp:
            for (L2, n2, k2, g2, r2, smd2) in B.items:
                if L2 != L or n2 == nn or (isinstance(r2, tuple) and r2[0] == ref):
                    continue
                need = fr.CTP if k2 != 'hole' else HOLE
                if g.distance(g2) < need - 1e-4:
                    bad.append(f'{ref} pad {L}:{n2}:{k2}:{fr.desc(r2)}:{g.distance(g2):.3f}')
            if g.distance(B.outline.exterior) < fr.CE:
                bad.append(f'{ref} edge')
    B0 = fr.Brd(A.inp)
    for pn in sorted(PLANE):
        gb0 = set(b for b in B0.check([pn]) if 'edge' not in b)
        bad += [pn + ' ' + b for b in B.check([pn]) if 'edge' not in b and b not in gb0]
    if bad:
        print('ILLEGAL', A.move, bad[:8], flush=True); sys.exit(2)
    if A.legal_only:
        print('LEGAL', A.move, flush=True); sys.exit(0)
op0 = rc.opens(cfg, B, lib2, NETS)
todo = [x for x in NETS if op0[x]]
print('moves', A.move or '-', 'ripped', ripped, 'stripped', n, 'to route', todo, flush=True)
T = A.out + '_strip.kicad_pcb'; B.save(T)
THIN = set(rc.csv(A.thin))
DEFW = next((r['widths'] for r in cfg.get('width_rules') if r.get('default')), [])


def widths(x):
    w = rc.widths(cfg, x, fr)
    return w + [v for v in DEFW if v not in w] if x in THIN else w


PAIRS = cfg.get('pairs') or []
best = None
for k in range(A.orders):
    order = list(todo) if k == 0 else random.sample(todo, len(todo))
    for a, b_ in PAIRS:   # pair members routed back to back
        if a in order and b_ in order:
            order.remove(b_); order.insert(order.index(a) + 1, b_)
    C = fr.Brd(T)
    for net in order:
        rc.connect_net(C, lib2, net, widths(net), [WIN], EF)
    op = rc.opens(cfg, C, lib2, NETS); tot = sum(op.values())
    print(f'order {k} open {tot} {dict((a, b) for a, b in op.items() if b)} :: {",".join(order)}', flush=True)
    if best is None or tot < best[0]:
        best = (tot, k); C.save(A.out + '_best.kicad_pcb')
    if tot <= A.save_max:
        C.save(A.out + f'_o{k}.kicad_pcb')
    if tot == 0:
        print('ZERO', k); break
print('best', A.move or '-', best, flush=True)
