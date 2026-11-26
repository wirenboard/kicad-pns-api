"""mincut.py IN OUT --nets A,B [options] : min-crossing rip-up for open nets (grid router, stock pcbnew).

For each open net of --nets, in order:
  1. plan on a cost grid (0.05 mm) where a cell blocked only by rippable foreign copper costs PEN instead of
     being a wall; hard obstacles (pads, holes, keep-outs, edge, plane/protected/frozen copper) stay walls.
     The planned path is the one that crosses the fewest foreign tracks. Copper of high_cost_nets (power
     trunks) and reserved copper (--rip-reserved) cost --pen-high / --pen-reserved per cell; --pen-prefix
     PREFIX=PEN adds a cost class by net-name prefix.
  2. rip exactly the foreign pieces the path touches, route the net exactly (fr A*, full clearances);
  3. re-route the ripped nets directly (in --rord orders; a ripped net that does not close is itself
     planned again with mincut, --depth levels deep).
  4. accept when the whole-board open total (sum of islands - 1 over all non-plane nets) drops, or with --eq
     when it stays equal, the target closed and that (net, open set) state was not accepted before.
--nperm attempts per net vary PEN over --pen-schedule. Accepted nets are frozen for the following nets
and rounds; --rounds repeats the net list while anything improves (--all-open adds every open net).
Writes OUT (the last accepted board; OUT.cand.kicad_pcb is the latest candidate); prints one line per
attempt and ACCEPT lines. Exit codes: 0 = OUT written (something improved), 1 = nothing improved (OUT
not written), 2 = bad arguments (unknown or frozen net in --nets, bad config).

Never ripped: plane_nets, protected_nets, frozen_nets and --freeze.
Board knowledge comes from --config (see routecfg.py): plane_nets, protected_nets, high_cost_nets,
reservations, pad_exits, via_forbid_rects, width_rules (section "mincut" overrides), window.
"""
import argparse
import ctypes
import os
import random
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import routecfg as rc  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__.split('\n')[0], epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('inp', metavar='IN', help='stock KiCad 10 board')
ap.add_argument('out', metavar='OUT', help='output board')
ap.add_argument('--nets', required=True, help='comma-separated open nets to close, in this order')
rc.add_config_arg(ap)
ap.add_argument('--window', help='x0,x1,y0,y1 working window (default: config window / board outline)')
ap.add_argument('--freeze', default='', help='extra nets never ripped (comma-separated)')
ap.add_argument('--rip-reserved', action='store_true', help='reserved copper (config reservations) may be ripped')
ap.add_argument('--pen-schedule', default='15,8,25,40,5,60', help='per-cell crossing cost of attempt k (cycled)')
ap.add_argument('--pen-reserved', type=float, default=40, help='crossing cost of reserved / high-cost copper')
ap.add_argument('--pen-high', type=float, default=40, help='crossing cost of high_cost_nets copper')
ap.add_argument('--pen-prefix', action='append', default=[], metavar='PREFIX=PEN', help='crossing cost by net-name prefix')
ap.add_argument('--nperm', type=int, default=6, help='attempts per net (default 6)')
ap.add_argument('--rord', type=int, default=1, help='re-route orders of the ripped nets at the top level (default 1)')
ap.add_argument('--depth', type=int, default=1, help='recursion depth for ripped nets that do not re-route')
ap.add_argument('--rounds', type=int, default=2, help='passes over the net list (default 2)')
ap.add_argument('--seed', type=int, default=1)
ap.add_argument('--eq', action='store_true', help='also accept an equal total when the target closes (tabu list)')
ap.add_argument('--all-open', action='store_true', help='after --nets, also try every other open net')
ap.add_argument('--strip-self', action='store_true', help="delete the target net's own partial copper first")
ap.add_argument('--strip-keep', type=float, default=0, help='with --strip-self: keep pieces within R mm of its pads')
A = ap.parse_args()

fr, lib2 = rc.gridrouter()
import pcbnew as K  # noqa: E402
from shapely.geometry import LineString, Point  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402

cfg = rc.Config(A.config, 'mincut')
cfg.apply_fr(fr)
IN, OUT, NETS = A.inp, A.out, rc.csv(A.nets)
PROT = cfg.nets('plane_nets') | cfg.nets('protected_nets') | cfg.nets('frozen_nets') | set(rc.csv(A.freeze))
HIGH = cfg.nets('high_cost_nets')
SCHED = [float(x) for x in A.pen_schedule.split(',')]
PEN = SCHED[0]
PENRES, PENPWR = A.pen_reserved, A.pen_high
PENPFX = [(p.split('=')[0], float(p.split('=')[1])) for p in A.pen_prefix]
random.seed(A.seed)
RES = rc.reservations(cfg)
SCR = rc.tmpdir()
VIACOST = 30


def rippable(t, net, frozen):
    n = t.GetNetname()
    if n == net or n in PROT or n in frozen:
        return False
    if rc.key(t) in RES and not A.rip_reserved:
        return False
    return True


def nbox(B, net, g=6.0):
    xs, ys = [], []
    for c in lib2.islands(B, net):
        for it in c:
            if it[0] == 'via':
                xs.append(it[1][0]); ys.append(it[1][1])
            elif it[0] == 'trk':
                xs += [it[2][0], it[3][0]]; ys += [it[2][1], it[3][1]]
            elif it[0] == 'pad':
                p = fr.P(B.pad(it[1], it[2]).GetPosition()); xs.append(p[0]); ys.append(p[1])
    return (max(WIN[0], min(xs) - g), min(WIN[1], max(xs) + g), max(WIN[2], min(ys) - g), min(WIN[3], max(ys) + g))


def direct(B, net, ef):
    return rc.connect_net(B, lib2, net, rc.widths(cfg, net, fr), lambda: [nbox(B, net), WIN], ef, guard=12,
                           viacost=VIACOST)


LIB = ctypes.CDLL(fr.ASTAR)
LIB.astar2.restype = ctypes.c_int


def penmask(B, S, net, frozen, sel, W_, ef, res):
    """cells blocked only by the rippable copper selected by sel(t)"""
    hi = [t for t in B.b.GetTracks() if rippable(t, net, frozen) and sel(t)]
    if not hi:
        return None
    tmp2 = f'{SCR}/pm_{os.getpid()}.kicad_pcb'; B.save(tmp2); S2 = fr.Brd(tmp2)
    hk = set(t.m_Uuid.AsString() for t in hi)
    for t in list(S2.b.GetTracks()):
        if rippable(t, net, frozen) and t.m_Uuid.AsString() not in hk:
            S2.b.Delete(t)
    S2.load_geom()
    f2, _ = S2.maps(net, W_, WIN, res=res, m=0.015, extra_forbid=ef)
    return ~f2.astype(bool)


def plan(B, net, ef, frozen):
    """min-crossing plan; returns (rippable tracks touched, in crossing order; path cells) or None"""
    W_ = rc.plan_width(cfg, net, fr)
    tmp = f'{SCR}/mc_{os.getpid()}.kicad_pcb'; B.save(tmp); S = fr.Brd(tmp)
    for t in [t for t in S.b.GetTracks() if rippable(t, net, frozen)]:
        S.b.Delete(t)
    S.load_geom()
    res = 0.05
    fa, va = B.maps(net, W_, WIN, res=res, m=0.015, extra_forbid=ef); fa = fa.astype(bool).copy(); va = va.copy()
    fh, vh = S.maps(net, W_, WIN, res=res, m=0.015, extra_forbid=ef); fh = fh.astype(bool).copy(); vh = vh.copy()
    gx0, gy0, _, Wd, Hd = S.grid
    pen = np.full(fa.shape, PEN, np.float32)
    if A.rip_reserved or PENPWR != PEN:
        m = penmask(B, S, net, frozen, lambda t: rc.key(t) in RES or t.GetNetname() in HIGH, W_, ef, res)
        if m is not None:
            pen[m & fh] = max(PENRES, PENPWR)
    for pfx, pv in PENPFX:
        m = penmask(B, S, net, frozen, lambda t: t.GetNetname().startswith(pfx), W_, ef, res)
        if m is not None:
            pen[m & fh] = pv
    cost = np.where(fa, 1.0, np.where(fh, pen, 1e9)).astype(np.float32)
    vcost = np.where(va, 30.0, np.where(vh, 30.0 + 20 * PEN, 1e9)).astype(np.float32)
    comps = lib2.islands(B, net)

    def cells(c):
        pts, _ = lib2.comp_targets(B, c, net, step=res); out = set()
        for x, y, L in pts:
            i, j = int(round((y - gy0) / res)), int(round((x - gx0) / res))
            if 0 <= i < Hd and 0 <= j < Wd:
                out.add((fr.ORDER.index(L), i, j))
        return sorted(out)
    A_ = cells(comps[0]); T = [c for k in range(1, len(comps)) for c in cells(comps[k])]
    if not A_ or not T:
        return None
    for (l, i, j) in A_ + T:
        cost[l, i, j] = min(cost[l, i, j], PEN)
    tgt = np.zeros(cost.shape, np.uint8)
    for (l, i, j) in T:
        tgt[l, i, j] = 1
    st = np.array([v for s in A_ for v in s], np.int32); out = np.zeros(400000, np.int32)
    n = LIB.astar2(len(fr.ORDER), Hd, Wd, np.ascontiguousarray(cost).ctypes.data_as(ctypes.c_void_p),
                   np.ascontiguousarray(vcost).ctypes.data_as(ctypes.c_void_p), tgt.ctypes.data_as(ctypes.c_void_p),
                   len(A_), st.ctypes.data_as(ctypes.c_void_p), ctypes.c_float(2.0), ctypes.c_float(20.0),
                   T[0][2], T[0][1], 80000000, out.ctypes.data_as(ctypes.c_void_p), 400000)
    if n <= 0:
        return None
    path = []
    for v in out[:n][::-1]:
        j = v % Wd; i = (v // Wd) % Hd; l = v // (Wd * Hd); path.append((gx0 + j * res, gy0 + i * res, fr.ORDER[int(l)]))
    geo = []
    for a, c in zip(path, path[1:]):
        if a[2] != c[2]:
            geo.append((None, Point(a[:2]).buffer(fr.VR + fr.CTP + 0.03)))
        else:
            geo.append((a[2], LineString([a[:2], c[:2]]).buffer(W_ / 2 + fr.CTP + 0.03)))
    gt = STRtree([g for _, g in geo])
    rip = []
    for t in B.b.GetTracks():
        if not rippable(t, net, frozen):
            continue
        if t.GetClass() == 'PCB_VIA':
            g = Point(fr.P(t.GetPosition())).buffer(fr.mm(t.GetWidth(K.F_Cu)) / 2); L = None
        else:
            g = LineString([fr.P(t.GetStart()), fr.P(t.GetEnd())]).buffer(fr.mm(t.GetWidth()) / 2); L = fr.LID.get(t.GetLayer())
        ks = [k for k in gt.query(g) if geo[k][1].intersects(g) and (geo[k][0] is None or L is None or geo[k][0] == L)]
        if ks:
            rip.append((min(ks), t))
    rip.sort(key=lambda a: a[0])
    return [t for _, t in rip], path


def strip_self(B, net):
    pc = [fr.P(p.GetPosition()) for f in B.b.GetFootprints() for p in f.Pads() if p.GetNetname() == net]
    for t in list(B.b.GetTracks()):
        if t.GetNetname() != net:
            continue
        ps = [fr.P(t.GetPosition())] if t.GetClass() == 'PCB_VIA' else [fr.P(t.GetStart()), fr.P(t.GetEnd())]
        if A.strip_keep and all(min(((a[0] - c[0]) ** 2 + (a[1] - c[1]) ** 2) ** 0.5 for c in pc) < A.strip_keep for a in ps):
            continue
        B.b.Delete(t)
    B.load_geom()


def attempt(B, net, ef, frozen, depth, top=False):
    if top and A.strip_self:
        strip_self(B, net)
    pl = plan(B, net, ef, frozen)
    if pl is None:
        return None
    rip, path = pl
    rn = []
    for t in rip:
        if t.GetNetname() not in rn:
            rn.append(t.GetNetname())
    for t in rip:
        B.b.Delete(t)
    B.load_geom()
    if not direct(B, net, ef):
        return rn + ['NOEXACT']
    if not top or A.rord <= 1:
        for n in rn:
            if not direct(B, n, ef) and depth > 0:
                attempt(B, n, ef, frozen | {net}, depth - 1)
        return rn
    # several re-route orders of the ripped nets; keep the best whole-board result in B
    tmp = f'{SCR}/mcr_{os.getpid()}.kicad_pcb'; B.save(tmp); best = None
    for r in range(A.rord):
        C = fr.Brd(tmp); order = list(rn) if r == 0 else random.sample(rn, len(rn))
        for n in order:
            if not direct(C, n, ef) and depth > 0:
                attempt(C, n, ef, frozen | {net}, depth - 1)
        t2 = sum(rc.opens(cfg, C, lib2).values())
        print(f'   order {r} {order} -> {t2}', flush=True)
        if best is None or t2 < best[0]:
            best = (t2, f'{tmp}.{r}.kicad_pcb'); C.save(best[1])
        if t2 <= tot - 1:
            break
    B._keep = fr.Brd(best[1]); B.b = B._keep.b; B.path = best[1]; B.load_geom()   # keep the SWIG board alive
    return rn


cur = IN
B = fr.Brd(cur)
rc.check_nets(B, NETS, cfg.nets('frozen_nets'))
rc.apply_pad_exits(cfg, B, lib2)
WIN = rc.window(cfg, B, rc.floats(A.window, 4) if A.window else None)
ef = rc.via_forbid(cfg, B, fr)
op = rc.opens(cfg, B, lib2); tot = sum(op.values())
print('start total open', tot, {n: v for n, v in op.items() if v}, flush=True)
TABU = set(); CLOSED = set()
for rnd in range(A.rounds):
    improved = False
    for net in ([n for n in NETS if op.get(n, 0) > 0] + [n for n in op if op[n] > 0 and n not in NETS and A.all_open]):
        t0 = time.time(); best = None
        for k in range(A.nperm):
            B = fr.Brd(cur)
            if k:
                random.seed(1000 * rnd + k + 1000000 * (A.seed - 1))   # --seed 1 keeps the historic sequence
            PEN = SCHED[k % len(SCHED)]
            rn = attempt(B, net, ef, {net} | CLOSED, A.depth, top=True)
            o2 = rc.opens(cfg, B, lib2); t2 = sum(o2.values())
            print(f'r{rnd} {net} k{k} PEN{PEN:g} rip {rn} -> total {t2} open {dict((a, b) for a, b in o2.items() if b)} ({time.time()-t0:.0f}s)', flush=True)
            eqok = A.eq and t2 == tot and o2.get(net, 0) == 0 and (net, tuple(sorted(a for a, b in o2.items() if b))) not in TABU
            if (t2 < tot or eqok) and (best is None or t2 < best[0]):
                best = (t2, o2); B.save(OUT + '.cand.kicad_pcb')
            if best and best[0] <= tot - op[net]:
                break
        if best:
            TABU.add((net, tuple(sorted(a for a, b in best[1].items() if b)))); CLOSED.add(net)
            fr.Brd(OUT + '.cand.kicad_pcb').save(OUT); cur = OUT; tot, op = best; improved = True
            print(f'ACCEPT r{rnd} {net} total {tot}', flush=True)
    if not improved:
        break
print('end total open', tot, {n: v for n, v in op.items() if v}, flush=True)
if cur == IN:
    print('no improvement: OUT not written', flush=True)
    sys.exit(1)
