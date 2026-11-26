"""fr.py : finisher grid router on a stock-10.0 board (python3 with stock KiCad's pcbnew SWIG module,
numpy, scipy, shapely, pillow). Coordinates: mm, y up (y = -KiCad y).

    import fr; fr.configure('myboard.json')        # optional, see below and fr_config.example.json
    B = fr.Brd('ckpt.kicad_pcb')
    p = B.route('NET', start=(x,y,'F'), targets=[(x,y,'F'),...], w=0.254, win=(x0,x1,y0,y1))
    B.commit('NET', p, w)        # adds tracks/vias
    B.delete('NET', pred)        # pred(kind, (x1,y1,x2,y2), layer) -> bool
    B.save('out.kicad_pcb'); B.check()   # exact shapely clearance of copper

The A* core is astar.c, built once next to this file:
    cc -O2 -shared -fPIC -o libastar.so astar.c -lm

Board-specific settings live in a config (dict or JSON file; also read from $FR_CONFIG on import):
  layers                  [[letter, KiCad layer name], ...] routable layers in stack order, default F.Cu + B.Cu
                          (layers not listed, e.g. inner planes, are never routed)
  clearance_track_track   0.2032   track-track clearance
  clearance_track_pad     0.2286   track-pad / via clearance
  clearance_edge          0.254    copper-board edge
  clearance_hole          0.25     copper-drill hole
  via_diameter, via_drill 0.7, 0.3 vias placed by commit()/via() (through vias)
  via_hole_to_hole        0.55     minimum distance of two via centres of one net in check()
  power_nets, power_width []/0.4064  lib2.task() default width for these nets
  gap_zone_skip_refs      []       footprints whose inter-pad gaps may be crossed (gap zones are not built)
  gap_zone_skip_prefixes  []       same, by reference prefix
  forbid_rects            []       {"layer": L, "rect": [x0, x1, y0, y1], "except_nets": [...]} no track
                                   centreline closer than w/2 to the rectangle (except for the listed nets)
  via_forbid_rects        []       [x0, x1, y0, y1]: no via closer than the via radius (see ALLOW_FORBIDDEN_VIAS)
  keepout_circles         []       {"layer": L, "x":, "y":, "r":} round keep-outs (e.g. tall THT leads)
  keepout_footprint_pads  []       {"ref": REF, "layer": L, "r":} the same circle around every pad of footprint REF
  alt_vias                []       {"rect": [x0, x1, y0, y1], "via_diameter":, "via_drill":} zones where a smaller
                                   via is allowed: maps() offers its sites too, commit()/via() place the default via
                                   wherever it fits exactly (fits()) and the smaller one only where it does not
  hole_margin             0.03     drill holes are modelled as the hole + this margin (copper ring, chord error)
  hole_check_extra        0.0      check(): extra distance required from copper to drill holes
  npth_pad_buffer         0.0      NPTH pad copper grown by this much (polygon chord error of round pads)
  hole_to_hole_edge       null     check(): minimum hole edge-to-edge distance of two vias of one net
                                   (null: via_hole_to_hole centre distance instead, in check() and fits())
  footprint_rule_areas    false    rule areas inside footprints are keep-outs too (board rule areas always are)
  check_keepouts          false    check() also reports vias / tracks inside keep-out rule areas
  via_connect_radius      null     lib2: radius of a via in island connectivity (null: the via's own radius)
"""
import sys, math, ctypes, os, json, numpy as np
import pcbnew as K
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
from scipy.ndimage import distance_transform_edt
from PIL import Image, ImageDraw

D = os.path.dirname(os.path.abspath(__file__))
ASTAR = os.environ.get('FR_ASTAR_LIB') or os.path.join(D, 'libastar.so')   # FR_ASTAR_LIB: a build elsewhere
lib = ctypes.CDLL(ASTAR)
lib.astar.restype = ctypes.c_int
mm = K.ToMM

DEFAULTS = dict(layers=[['F', 'F.Cu'], ['B', 'B.Cu']],
                clearance_track_track=0.2032, clearance_track_pad=0.2286, clearance_edge=0.254, clearance_hole=0.25,
                via_diameter=0.7, via_drill=0.3, via_hole_to_hole=0.55, power_nets=[], power_width=0.4064,
                gap_zone_skip_refs=[], gap_zone_skip_prefixes=[], forbid_rects=[], via_forbid_rects=[],
                keepout_circles=[], keepout_footprint_pads=[], alt_vias=[], hole_margin=0.03, hole_check_extra=0.0, npth_pad_buffer=0.0,
                hole_to_hole_edge=None, footprint_rule_areas=False, check_keepouts=False, via_connect_radius=None)
CFG = {}
ALLOW_FORBIDDEN_VIAS = False   # True: ignore via_forbid_rects (e.g. tented vias allowed there)


def configure(cfg=None, **kw):
    """set the board config from a dict or a JSON file path (+ keyword overrides); unknown keys are errors"""
    global CFG, LAY, LID, ORDER, CTT, CTP, CE, VR, POWER
    if isinstance(cfg, str):
        cfg = json.load(open(cfg))
    new = dict(DEFAULTS)
    for k, v in list((cfg or {}).items()) + list(kw.items()):
        if k.startswith('_'):
            continue                                   # comments
        if k not in DEFAULTS:
            raise KeyError(f'unknown fr config key {k!r}')
        new[k] = v
    CFG = new
    LAY = {l: getattr(K, n.replace('.', '_')) for l, n in CFG['layers']}
    LID = {v: k for k, v in LAY.items()}
    ORDER = [l for l, _ in CFG['layers']]
    CTT, CTP, CE = CFG['clearance_track_track'], CFG['clearance_track_pad'], CFG['clearance_edge']
    VR = CFG['via_diameter'] / 2
    POWER = set(CFG['power_nets'])
    return CFG


configure(os.environ.get('FR_CONFIG'))


def V(x, y): return K.VECTOR2I(K.FromMM(float(x)), K.FromMM(-float(y)))
def P(v): return (mm(v.x), -mm(v.y))


class Brd:
    def __init__(self, path):
        self.path = path
        self.b = K.LoadBoard(path)
        self.added = []   # (net, kind, geom-desc)
        self.load_geom()

    # ---------------------------------------------------------------- geometry
    def load_geom(self):
        b = self.b
        self.items = []   # (layer, net, kind['trk','via','pad','hole'], geom, ref, smd)
        for t in b.GetTracks():
            n = t.GetNetname()
            if t.GetClass() == 'PCB_VIA':
                p = P(t.GetPosition()); g = Point(p).buffer(mm(t.GetWidth(K.F_Cu)) / 2, 24)
                for L in ORDER: self.items.append((L, n, 'via', g, t, False))
            else:
                L = LID.get(t.GetLayer())
                if not L: continue
                s, e = P(t.GetStart()), P(t.GetEnd())
                ls = LineString([s, e]) if s != e else Point(s)
                self.items.append((L, n, 'trk', ls.buffer(mm(t.GetWidth()) / 2, 12), t, False))
        for f in b.GetFootprints():
            for p in f.Pads():
                smd = p.GetDrillSizeX() == 0
                for lid, L in LID.items():
                    if not p.IsOnLayer(lid): continue
                    poly = p.GetEffectivePolygon(lid)
                    if poly.OutlineCount() == 0: continue
                    o = poly.Outline(0); pts = [(mm(o.CPoint(i).x), -mm(o.CPoint(i).y)) for i in range(o.PointCount())]
                    if len(pts) < 3: continue
                    pg_ = Polygon(pts).buffer(0)
                    if CFG['npth_pad_buffer'] and p.GetAttribute() == K.PAD_ATTRIB_NPTH: pg_ = pg_.buffer(CFG['npth_pad_buffer'], 16)
                    self.items.append((L, p.GetNetname(), 'pad', pg_, (f.GetReference(), p.GetNumber()), smd))
                if not smd:
                    c = P(p.GetPosition()); r = mm(max(p.GetDrillSizeX(), p.GetDrillSizeY())) / 2
                    for L in ORDER: self.items.append((L, p.GetNetname(), 'hole', Point(c).buffer(r + CFG['hole_margin'], 24), (f.GetReference(), p.GetNumber()), False))
        # inter-pad gap zones of 2-to-6-pin parts (fan-out rule: no track into the gap between two pads of one part)
        self.gapz = {L: [] for L in ORDER}
        for f in b.GetFootprints():
            ref = f.GetReference()
            if ref in CFG['gap_zone_skip_refs'] or any(ref.startswith(p) for p in CFG['gap_zone_skip_prefixes']): continue
            side = 'B' if f.IsFlipped() else 'F'
            bbs = []
            for p in f.Pads():
                if p.GetDrillSizeX() > 0: continue
                bb = p.GetBoundingBox(); bbs.append((mm(bb.GetLeft()), -mm(bb.GetBottom()), mm(bb.GetRight()), -mm(bb.GetTop())))
            for i in range(len(bbs)):
                for j in range(i + 1, len(bbs)):
                    a, c = bbs[i], bbs[j]
                    ox = min(a[2], c[2]) - max(a[0], c[0]); oy = min(a[3], c[3]) - max(a[1], c[1])
                    if ox > 0.05 and 0 < -oy < 2.2: gb = box(max(a[0], c[0]), min(a[3], c[3]), min(a[2], c[2]), max(a[1], c[1]))
                    elif oy > 0.05 and 0 < -ox < 2.2: gb = box(min(a[2], c[2]), max(a[1], c[1]), max(a[0], c[0]), min(a[3], c[3]))
                    else: continue
                    if any(box(*bbs[q]).intersects(gb.buffer(-0.01)) for q in range(len(bbs)) if q not in (i, j)): continue   # not adjacent
                    self.gapz[side].append(gb)
        # edge (true outline incl. arcs)
        ps = K.SHAPE_POLY_SET(); b.GetBoardPolygonOutlines(ps, True)
        o = ps.Outline(0)
        self.outline = Polygon([(mm(o.CPoint(i).x), -mm(o.CPoint(i).y)) for i in range(o.PointCount())]).buffer(0)
        self.holes_np = []
        # rule areas
        self.keep = {L: [] for L in ORDER}; self.keepvia = []
        self.kcircles = list(CFG['keepout_circles'])
        for kp in CFG['keepout_footprint_pads']:
            f = b.FindFootprintByReference(kp['ref'])
            if f is None: raise KeyError(f"keepout_footprint_pads: no footprint {kp['ref']}")
            for p in f.Pads(): self.kcircles.append(dict(layer=kp['layer'], x=P(p.GetPosition())[0], y=P(p.GetPosition())[1], r=kp['r']))
        zs = list(b.Zones()) + ([z for f in b.GetFootprints() for z in f.Zones()] if CFG['footprint_rule_areas'] else [])
        for z in zs:
            if not z.GetIsRuleArea(): continue
            o = z.Outline().Outline(0); pg = Polygon([(mm(o.CPoint(i).x), -mm(o.CPoint(i).y)) for i in range(o.PointCount())])
            for l in z.GetLayerSet().Seq():
                if l in LID and z.GetDoNotAllowTracks(): self.keep[LID[l]].append(pg)
            if z.GetDoNotAllowVias(): self.keepvia.append(pg)

    def pad(self, ref, num):
        f = self.b.FindFootprintByReference(ref)
        for p in f.Pads():
            if p.GetNumber() == str(num): return p
    def padxy(self, ref, num): return P(self.pad(ref, num).GetPosition())

    # ---------------------------------------------------------------- rasterize
    def maps(self, net, w, win, res=0.025, m=0.012, layers=None, avoid_nets=(), extra_forbid=None):
        layers = ORDER if layers is None else layers
        x0, x1, y0, y1 = win
        W = int(round((x1 - x0) / res)) + 1; H = int(round((y1 - y0) / res)) + 1
        self.grid = (x0, y0, res, W, H)
        def raster(geoms):
            im = Image.new('L', (W, H), 0); dr = ImageDraw.Draw(im)
            for g in geoms:
                for pg in (g.geoms if hasattr(g, 'geoms') else [g]):
                    if pg.is_empty: continue
                    if pg.geom_type == 'Polygon':
                        pts = [((x - x0) / res, (y - y0) / res) for x, y in pg.exterior.coords]
                        if len(pts) > 2: dr.polygon(pts, fill=1, outline=1)
                        for ring in pg.interiors:   # holes (allowed corridors inside a forbidden area)
                            hp = [((x - x0) / res, (y - y0) / res) for x, y in ring.coords]
                            if len(hp) > 2: dr.polygon(hp, fill=0, outline=0)
            return np.array(im, dtype=bool)
        winbox = box(x0 - 1, y0 - 1, x1 + 1, y1 + 1)
        def dist(mask):
            if not mask.any(): return np.full(mask.shape, 1e9)
            return distance_transform_edt(~mask) * res
        free = np.zeros((len(layers), H, W), np.uint8)
        viaok = np.ones((H, W), bool)
        alts = sorted(set((a['via_diameter'], a['via_drill']) for a in CFG['alt_vias']))
        aok = {a: np.ones((H, W), bool) for a in alts}
        ys, xs = np.mgrid[0:H, 0:W]; X = x0 + xs * res; Y = y0 + ys * res
        # edge distance
        # edge distance on a grid padded by 1.5 mm of real board (a plain border padding would make the
        # window border look like a board edge and reject every via site in small windows)
        M = int(round(1.5 / res))
        im = Image.new('L', (W + 2 * M, H + 2 * M), 0); dr = ImageDraw.Draw(im)
        ob = self.outline.intersection(box(x0 - 1.5 - res, y0 - 1.5 - res, x1 + 1.5 + res, y1 + 1.5 + res))
        for pg in (ob.geoms if hasattr(ob, 'geoms') else [ob]):
            if pg.geom_type == 'Polygon' and not pg.is_empty:
                dr.polygon([((x - x0) / res + M, (y - y0) / res + M) for x, y in pg.exterior.coords], fill=1, outline=1)
        big = np.pad(np.array(im, dtype=bool), 1, constant_values=False)
        dedge = distance_transform_edt(big)[1 + M:1 + M + H, 1 + M:1 + M + W] * res - 0.75 * res
        inside = None
        smd_all = []
        self.dt = {}
        for li, L in enumerate(layers):
            trk = [g for (l, n, k, g, *_r) in self.items if l == L and n != net and k == 'trk' and g.intersects(winbox)]
            pv = [g for (l, n, k, g, *_r) in self.items if l == L and n != net and k in ('via', 'pad', 'hole') and g.intersects(winbox)]
            same_hole = []
            dtt = dist(raster(trk)); dtp = dist(raster(pv))
            self.dt[L] = (dtt, dtp)
            f = (dtt >= CTT + w / 2 + m) & (dtp >= CTP + w / 2 + m) & (dedge >= CE + w / 2 + m)
            own = [g for (l, n, k, g, ref, smd) in self.items if l == L and n == net and k == 'pad' and smd and g.intersects(winbox)]
            if own: f &= dist(raster(own)) >= 0.12
            gz = [g for g in self.gapz.get(L, []) if g.intersects(winbox)]
            if gz: f &= dist(raster(gz)) >= w / 2 + 0.01
            kp = [g for g in self.keep[L] if g.intersects(winbox)]
            if kp: f &= dist(raster(kp)) >= w / 2 + m
            for fz in CFG['forbid_rects']:
                if fz['layer'] != L or net in fz.get('except_nets', ()): continue
                rx0, rx1, ry0, ry1 = fz['rect']
                f &= ~((X > rx0 - w / 2) & (X < rx1 + w / 2) & (Y > ry0 - w / 2) & (Y < ry1 + w / 2))
            for kc in self.kcircles:
                if kc['layer'] == L: f &= np.hypot(X - kc['x'], Y - kc['y']) >= kc['r'] + w / 2
            if extra_forbid is not None and L in extra_forbid:
                ef = [g for g in extra_forbid[L]]
                if ef: f &= dist(raster(ef)) >= w / 2 + m
            for an in avoid_nets:   # treat these nets' copper as off-limits (for planning)
                pass
            free[li] = f
            viaok &= (dtt >= CTP + VR + m + 0.012) & (dtp >= CTP + VR + m + 0.012)
            for (ad, ah), a in aok.items(): a &= (dtt >= CTP + ad / 2 + m + 0.012) & (dtp >= CTP + ad / 2 + m + 0.012)
        smd = [g for (l, n, k, g, ref, s) in self.items if k == 'pad' and s and g.intersects(winbox)]
        dsmd = dist(raster(smd))
        viaok &= dsmd >= CTP + VR + m
        holes = [Point(P(t.GetPosition())).buffer(mm(t.GetDrillValue()) / 2) for t in self.b.GetTracks() if t.GetClass() == 'PCB_VIA']
        holes += [g for (l, n, k, g, *_r) in self.items if k == 'hole' and l == 'F']
        dh = dist(raster([h for h in holes if h.intersects(winbox)]))
        viaok &= dh >= CFG['clearance_hole'] + CFG['via_drill'] / 2 + m
        viaok &= dedge >= CE + VR + m
        kv = [g for g in self.keepvia if g.intersects(winbox)]
        dkv = dist(raster(kv)) if kv else None
        if kv: viaok &= dkv >= VR + m
        def vforbid(ok, r):
            if not ALLOW_FORBIDDEN_VIAS:
                for rx0, rx1, ry0, ry1 in CFG['via_forbid_rects']:
                    ok &= ~((X > rx0 - r) & (X < rx1 + r) & (Y > ry0 - r) & (Y < ry1 + r))
            if extra_forbid is not None and 'via' in extra_forbid:
                ok &= dist(raster(extra_forbid['via'])) >= r + m
        vforbid(viaok, VR)
        self.viaok_default = viaok.copy()
        for (ad, ah), a in aok.items():   # smaller vias where alt_vias allow them
            a &= (dsmd >= CTP + ad / 2 + m) & (dh >= CFG['clearance_hole'] + ah / 2 + m) & (dedge >= CE + ad / 2 + m)
            if kv: a &= dkv >= ad / 2 + m
            vforbid(a, ad / 2)
            Z = np.zeros_like(viaok)
            for z in CFG['alt_vias']:
                if (z['via_diameter'], z['via_drill']) == (ad, ah):
                    rx0, rx1, ry0, ry1 = z['rect']; Z |= (X >= rx0) & (X <= rx1) & (Y >= ry0) & (Y <= ry1)
            viaok |= Z & a
        self.free = free; self.viaok = viaok; self.layers = list(layers)
        return free, viaok

    def cell(self, x, y):
        x0, y0, res, W, H = self.grid
        return int(round((y - y0) / res)), int(round((x - x0) / res))
    def xy(self, i, j):
        x0, y0, res, W, H = self.grid
        return x0 + j * res, y0 + i * res

    # ---------------------------------------------------------------- route
    def route(self, net, start, targets, w=0.254, win=None, res=0.025, viacost=40, turn45=1.0, turn90=8.0,
              layercost=None, layers=None, maxexp=30000000, extra_forbid=None, novia=False, m=0.012,
              free_start=0.0, free_target=0.0):
        """start: (x,y,L) or list of them (exact points); targets: list of (x,y,L) exact points.
        grid is aligned to the first start point. Returns list of (x,y,L) vertices, or None."""
        layers = ORDER if layers is None else layers
        starts = start if isinstance(start, list) else [start]
        sx, sy = starts[0][0], starts[0][1]
        if win is None:
            xs = [p[0] for p in starts + targets]; ys = [p[1] for p in starts + targets]
            win = (min(xs) - 4, max(xs) + 4, min(ys) - 4, max(ys) + 4)
        x0, x1, y0, y1 = win
        x0 = sx - math.ceil((sx - x0) / res) * res; y0 = sy - math.ceil((sy - y0) / res) * res
        self.maps(net, w, (x0, x1, y0, y1), res, m=m, layers=ORDER, extra_forbid=extra_forbid)
        x0, y0, res, W, H = self.grid
        free = self.free[[ORDER.index(L) for L in layers]].copy(); viaok = self.viaok.copy()
        if novia: viaok[:] = False
        tgt = np.zeros_like(free)
        tpts = {}
        if isinstance(targets, dict):   # {'via': (x0,x1,y0,y1)}: end on any legal via site in region (on layer L0)
            rx0, rx1, ry0, ry1 = targets['via']
            ys_, xs_ = np.mgrid[0:H, 0:W]; X_ = x0 + xs_ * res; Y_ = y0 + ys_ * res
            reg = (X_ >= rx0) & (X_ <= rx1) & (Y_ >= ry0) & (Y_ <= ry1) & viaok
            for li in range(len(layers)): tgt[li] |= (reg & (free[li] > 0)).astype(np.uint8)
            targets = [((rx0 + rx1) / 2, (ry0 + ry1) / 2, layers[0])]
        for (x, y, L) in targets:
            i, j = self.cell(x, y)
            if 0 <= i < H and 0 <= j < W and L in layers:
                li = layers.index(L); tgt[li, i, j] = 1; free[li, i, j] = 1; tpts[(li, i, j)] = (x, y, L)
                if free_target > 0:   # clear a disc around the target too (own pad halo)
                    rr = int(free_target / res)
                    for di in range(-rr, rr + 1):
                        for dj in range(-rr, rr + 1):
                            if di * di + dj * dj <= rr * rr and 0 <= i + di < H and 0 <= j + dj < W: free[li, i + di, j + dj] = 1
        st = []
        for (x, y, L) in starts:
            i, j = self.cell(x, y); li = layers.index(L)
            st += [li, i, j]
            # clear a small disc around start (own pad/stub end may sit in a forbidden halo)
            if free_start > 0:
                rr = int(free_start / res)
                for di in range(-rr, rr + 1):
                    for dj in range(-rr, rr + 1):
                        if di * di + dj * dj <= rr * rr and 0 <= i + di < H and 0 <= j + dj < W: free[li, i + di, j + dj] = 1
            free[li, i, j] = 1
        lc = np.array(layercost or [1.0] * len(layers), np.float32)
        tx, ty = self.cell(targets[0][0], targets[0][1])[::-1]
        outmax = 200000; out = np.zeros(outmax, np.int32)
        fr_ = np.ascontiguousarray(free, np.uint8); vo = np.ascontiguousarray(viaok, np.uint8); tg = np.ascontiguousarray(tgt, np.uint8)
        sa = np.array(st, np.int32)
        n = lib.astar(len(layers), H, W, fr_.ctypes.data_as(ctypes.c_void_p), vo.ctypes.data_as(ctypes.c_void_p),
                      tg.ctypes.data_as(ctypes.c_void_p), len(starts), sa.ctypes.data_as(ctypes.c_void_p),
                      ctypes.c_float(viacost), ctypes.c_float(turn45), ctypes.c_float(turn90),
                      lc.ctypes.data_as(ctypes.c_void_p), tx, ty, maxexp, out.ctypes.data_as(ctypes.c_void_p), outmax)
        if n <= 0:
            self.last_fail = -n
            return None
        cells = []
        for c in out[:n][::-1]:
            j = c % W; i = (c // W) % H; li = c // (W * H); cells.append((li, i, j))
        # vertices
        pts = []
        for k, (li, i, j) in enumerate(cells):
            x, y = self.xy(i, j); pts.append((round(float(x), 4), round(float(y), 4), layers[li]))
        st0 = None
        for (x, y, L) in starts:
            i, j = self.cell(x, y)
            if (layers.index(L), i, j) == cells[0]: st0 = (x, y, L); break
        end = tpts.get(cells[-1])
        poly = simplify(pts)
        if end is not None: poly = snap_end(poly, end)
        if st0 is not None: poly = list(reversed(snap_end(list(reversed(poly)), st0)))
        return poly

    # ---------------------------------------------------------------- edit
    def commit(self, net, poly, w=0.254, layer_w=None):
        b = self.b; ni = b.FindNet(net); new = []
        for (a, c) in zip(poly, poly[1:]):
            if a[2] != c[2]:
                if abs(a[0] - c[0]) > 1e-6 or abs(a[1] - c[1]) > 1e-6: raise ValueError(('via move', a, c))
                vd, vh = self.viasize(net, a[0], a[1])
                v = K.PCB_VIA(b); v.SetPosition(V(a[0], a[1])); v.SetWidth(K.FromMM(vd)); v.SetDrill(K.FromMM(vh))
                v.SetLayerPair(K.F_Cu, K.B_Cu); v.SetNet(ni); b.Add(v); new.append(v)
            else:
                if abs(a[0] - c[0]) < 1e-6 and abs(a[1] - c[1]) < 1e-6: continue
                t = K.PCB_TRACK(b); t.SetStart(V(a[0], a[1])); t.SetEnd(V(c[0], c[1]))
                t.SetWidth(K.FromMM((layer_w or {}).get(a[2], w))); t.SetLayer(LAY[a[2]]); t.SetNet(ni); b.Add(t); new.append(t)
        self.added += new
        self.load_geom()
        return new

    def via(self, net, x, y):
        vd, vh = self.viasize(net, x, y)
        b = self.b; v = K.PCB_VIA(b); v.SetPosition(V(x, y)); v.SetWidth(K.FromMM(vd)); v.SetDrill(K.FromMM(vh))
        v.SetLayerPair(K.F_Cu, K.B_Cu); v.SetNet(b.FindNet(net)); b.Add(v); self.added.append(v); self.load_geom(); return v

    def fits(self, net, x, y, vd, vh):
        """exact check of a through via (diameter vd, drill vh) at (x,y) for net against present copper, holes, edge"""
        c = Point(x, y); r = vd / 2; hm = CFG['hole_margin']; hh = CFG['hole_to_hole_edge']
        for (L, n, k, g, ref, smd) in self.items:
            if k == 'hole':   # g = hole + hole_margin
                if g.distance(c) + hm < CFG['clearance_hole'] + vh / 2 - 1e-4: return False
                continue
            if k == 'via':
                dd = Point(P(ref.GetPosition())).distance(c)
                if dd < 1e-6: continue
                if hh is None:
                    if dd < CFG['via_hole_to_hole'] - 1e-4: return False
                elif dd - mm(ref.GetDrillValue()) / 2 - vh / 2 < hh - 1e-4: return False
                if n == net: continue
            if n == net and not (k == 'pad' and smd): continue
            if g.distance(c) < r + CTP - 1e-4: return False
        if self.outline.exterior.distance(c) < CE + r - 1e-4: return False
        for pg in self.keepvia:
            if pg.distance(c) < r - 1e-4: return False
        return True

    def viasize(self, net, x, y):
        """(diameter, drill) for a new via: the default one, or an alt_vias size where the default does not fit"""
        d = (CFG['via_diameter'], CFG['via_drill'])
        for z in CFG['alt_vias']:
            rx0, rx1, ry0, ry1 = z['rect']
            if rx0 <= x <= rx1 and ry0 <= y <= ry1:
                return d if self.fits(net, x, y, *d) else (z['via_diameter'], z['via_drill'])
        return d

    def delete(self, net, pred=lambda k, g, L: True):
        rm = []
        for t in list(self.b.GetTracks()):
            if net is not None and t.GetNetname() != net and not (isinstance(net, (set, list, tuple)) and t.GetNetname() in net): continue
            if t.GetClass() == 'PCB_VIA':
                p = P(t.GetPosition()); g = (p[0], p[1], p[0], p[1]); k = 'via'; L = None
            else:
                s, e = P(t.GetStart()), P(t.GetEnd()); g = (s[0], s[1], e[0], e[1]); k = 'track'; L = LID.get(t.GetLayer(), '1')
            if pred(k, g, L): rm.append(t)
        for t in rm: self.b.Delete(t)
        self.load_geom()
        return len(rm)

    def tracks(self, net):
        out = []
        for t in self.b.GetTracks():
            if t.GetNetname() != net: continue
            if t.GetClass() == 'PCB_VIA': out.append(('via', P(t.GetPosition())))
            else: out.append((LID.get(t.GetLayer(), '1'), P(t.GetStart()), P(t.GetEnd()), round(mm(t.GetWidth()), 4)))
        return out

    def move(self, ref, x, y, rot=None):
        f = self.b.FindFootprintByReference(ref)
        old = (P(f.GetPosition()), f.GetOrientationDegrees(), 'B' if f.IsFlipped() else 'F')
        f.SetPosition(V(x, y))
        if rot is not None: f.SetOrientationDegrees(rot)
        self.load_geom()
        return old

    def save(self, path):
        K.SaveBoard(path, self.b)

    # ---------------------------------------------------------------- exact check of copper of given nets
    def check(self, nets=None, items=None):
        bad = []; self.offend = []
        from shapely.strtree import STRtree
        geoms = [it[3] for it in self.items]; tree = STRtree(geoms)
        for idx, (L, n, k, g, ref, smd) in enumerate(self.items):
            if k not in ('trk', 'via'): continue
            if nets is not None and n not in nets: continue
            if L == '1': continue
            for j in tree.query(g.buffer(0.3)):
                L2, n2, k2, g2, ref2, smd2 = self.items[j]
                if L2 != L or j == idx: continue
                if n2 == n and not (k == 'via' and ((k2 == 'pad' and smd2) or k2 == 'via')): continue
                if n2 == n and k2 == 'via':
                    if L != 'F': continue
                    d = Point(P(ref.GetPosition())).distance(Point(P(ref2.GetPosition())))
                    if CFG['hole_to_hole_edge'] is None: lim = CFG['via_hole_to_hole']
                    else: lim = CFG['hole_to_hole_edge'] + (mm(ref.GetDrillValue()) + mm(ref2.GetDrillValue())) / 2
                    if d < lim - 1e-3 and d > 1e-6: bad.append(f'via-via hole {n} {d:.3f} at {P(ref.GetPosition())}')
                    continue
                need = CTT if (k == 'trk' and k2 == 'trk') else (CFG['clearance_hole'] if k2 == 'hole' else CTP)
                if n2 == n and k2 == 'pad': need = CTP
                if k2 == 'hole' and n2 == n: continue
                dd = g.distance(g2) + (CFG['hole_margin'] - CFG['hole_check_extra'] if k2 == 'hole' else 0)   # hole items carry hole_margin
                if dd < need - 2e-5:
                    bad.append(f'{L} {dd:.3f}<{need} {n} {k} {desc(ref)} | {n2} {k2} {desc(ref2)}')
                    self.offend.append((n, ref, n2, ref2))
            if CFG['check_keepouts'] and k == 'via' and L == ORDER[0] and any(g.intersection(pg).area > 1e-6 for pg in self.keepvia):
                bad.append(f'keepout via {n} {desc(ref)}'); self.offend.append((n, ref, None, None))
            if CFG['check_keepouts'] and k == 'trk' and any(g.intersection(pg).area > 1e-6 for pg in self.keep.get(L, [])):
                bad.append(f'keepout trk {L} {n} {desc(ref)}'); self.offend.append((n, ref, None, None))
            if k == 'trk' and g.distance(self.outline.exterior) < CE - 1e-3 and L in ORDER:
                bad.append(f'edge {n} {desc(ref)}'); self.offend.append((n, ref, None, None))
        return sorted(set(bad))


def desc(r):
    if isinstance(r, tuple): return f'{r[0]}.{r[1]}'
    if r.GetClass() == 'PCB_VIA': p = P(r.GetPosition()); return f'via({p[0]:.2f},{p[1]:.2f})'
    s, e = P(r.GetStart()), P(r.GetEnd()); return f'({s[0]:.2f},{s[1]:.2f})-({e[0]:.2f},{e[1]:.2f})'


def simplify(pts):
    out = [pts[0]]
    for k in range(1, len(pts)):
        p = pts[k]
        if len(out) >= 2 and out[-1][2] == p[2] and out[-2][2] == p[2]:
            a, b = out[-2], out[-1]
            d1 = (b[0] - a[0], b[1] - a[1]); d2 = (p[0] - b[0], p[1] - b[1])
            if abs(d1[0] * d2[1] - d1[1] * d2[0]) < 1e-9 and d1[0] * d2[0] + d1[1] * d2[1] > 0:
                out[-1] = p; continue
        if (p[0], p[1], p[2]) != out[-1]: out.append(p)
    return out


def snap_end(poly, end):
    """make the polyline end exactly at end=(x,y,L) keeping 45-degree directions where possible"""
    c = poly[-1]
    if abs(c[0] - end[0]) < 1e-6 and abs(c[1] - end[1]) < 1e-6: return poly[:-1] + [end]
    if len(poly) >= 3 and poly[-2][2] == c[2] and poly[-3][2] == c[2]:
        a, b = poly[-3], poly[-2]
        d1 = (b[0] - a[0], b[1] - a[1]); d2 = (c[0] - b[0], c[1] - b[1])
        den = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(den) > 1e-9:
            # a + t*d1 = end - s*d2
            t = ((end[0] - a[0]) * d2[1] - (end[1] - a[1]) * d2[0]) / den
            nb = (round(a[0] + t * d1[0], 4), round(a[1] + t * d1[1], 4), c[2])
            return poly[:-2] + [nb, end]
    return poly[:-1] + [(c[0], c[1], c[2]), end]   # micro jog (reported by angle check)


def angles_ok(poly):
    bad = []
    for a, c in zip(poly, poly[1:]):
        if a[2] != c[2]: continue
        dx, dy = c[0] - a[0], c[1] - a[1]
        if math.hypot(dx, dy) < 1e-6: continue
        an = math.degrees(math.atan2(dy, dx)) % 45
        if min(an, 45 - an) > 0.3: bad.append((a, c))
    return bad
