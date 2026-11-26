"""gate.py OLD NEW [TARGETNETS] [--allow-vias] --config CFG : acceptance gate for one local copper edit
(stock pcbnew + kicad-cli). OLD and NEW are stock KiCad 10 boards; TARGETNETS (comma-separated) are the nets
the edit was meant to change. Prints CHANGED, RULE5, one FAIL line per finding and PASS or REJECT; exit 0 =
pass, 1 = reject, 2 = the gate itself failed (one "GATE ERROR ..." line: bad config, kicad-cli error, ...).

 1. kicad-cli DRC of NEW (zones refilled; rules = gate.drc_project + its .kicad_dru, default: the .kicad_pro
    next to NEW, else next to OLD - a warning on stderr if there is none): unconnected <=
    gate.max_unconnected (default 0); copper violation counts per type equal gate.drc_expect when given,
    else not above OLD's (non-copper types in gate.drc_ignore are ignored);
 2. fr.check of NEW (whole board): no finding that OLD does not have (gate.frcheck_ignore: prefixes ignored);
 3. margin: every new or moved track/via keeps the fr clearances + gate.margin (default 0.002 mm) to foreign
    copper (holes: + gate.hole_extra) and the edge clearance + margin;
 4. pad exits: a new segment crossing a same-net SMD pad edge is orthogonal, and for parts with more than
    gate.axis_min_pads pads (default 3) runs along the pad's long axis;
 5. free track ends (not on a same-net track end, via or pad centre) do not grow on any changed net;
 6. zones of rules DRC does not know, on new copper: gate.forbid_new_copper [{"layer", "rect", "allow_pads_of":
    [refs]}], gate.halo_pads [{"ref", "layer", "r"}], fr inter-pad gap zones (gate.gap_zones, default true),
    gate.no_track_layers (KiCad names); fancheck categories in gate.fancheck_not_worse do not grow;
 7. rule 5 (gate.rule5, default true; --no-rule5 turns it off): no new hairpin, jog or detour entry, jogs + detours strictly down;
 8. frozen_nets identical to 1 um (minus TARGETNETS); vias unchanged (position, size) unless --allow-vias; every
    changed net keeps its width set (no new width); fr power nets never get narrower.
gate.extra_cmd: a command (list) run with OLD NEW appended; non-zero exit = FAIL.
"""
import argparse
import ast
import collections
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import routecfg as rc  # noqa: E402


def die(msg):
    print('GATE ERROR', msg, flush=True)
    sys.exit(2)


def _hook(t, v, tb):   # any unexpected exception is a gate error (2), never a REJECT (1)
    import traceback
    traceback.print_exception(t, v, tb, limit=3, file=sys.stderr)
    print('GATE ERROR', t.__name__, v, flush=True)
    sys.stdout.flush(); os._exit(2)


sys.excepthook = _hook

ap = argparse.ArgumentParser(description=__doc__.split('\n')[0], epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('old', metavar='OLD')
ap.add_argument('new', metavar='NEW')
ap.add_argument('targets', metavar='TARGETNETS', nargs='?', default='')
ap.add_argument('--allow-vias', action='store_true', help='vias may move / change')
ap.add_argument('--no-rule5', action='store_true', help='skip the rule-5 (jog/detour) check')
rc.add_config_arg(ap)
A = ap.parse_args()

fr, lib2 = rc.gridrouter()
import pcbnew as K  # noqa: E402
from shapely.geometry import LineString, Point, box  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402

cfg = rc.Config(A.config, 'gate')
cfg.apply_fr(fr)
OLD, NEW = A.old, A.new
TN = set(rc.csv(A.targets))
FROZEN = cfg.nets('frozen_nets') - TN
MARGIN = cfg.get('margin', 0.002)
HOLE_EXTRA = cfg.get('hole_extra', 0.0)
TOOLS = rc.HERE
STOCK_PY = os.environ.get('KPNS_STOCK_PY', sys.executable)
DRC_IGNORE = cfg.get('drc_ignore', ['silk_over_copper', 'silk_overlap', 'silk_edge_clearance', 'text_height',
                                    'pth_inside_courtyard', 'npth_inside_courtyard', 'courtyards_overlap',
                                    'text_thickness'])
bad = []
mm = K.ToMM


def gkey(t):
    if t.GetClass() == 'PCB_VIA':
        return ('v', t.GetNetname(), round(t.GetPosition().x / 1e3), round(t.GetPosition().y / 1e3), t.GetWidth(K.F_Cu), t.GetDrillValue())
    return ('t', t.GetNetname(), t.GetLayer(), t.GetWidth(), tuple(sorted([(round(t.GetStart().x / 1e3), round(t.GetStart().y / 1e3)),
                                                                          (round(t.GetEnd().x / 1e3), round(t.GetEnd().y / 1e3))])))


bo, bn = K.LoadBoard(OLD), K.LoadBoard(NEW)
ko = collections.Counter(gkey(t) for t in bo.GetTracks()); kn = collections.Counter(gkey(t) for t in bn.GetTracks())
changed = collections.defaultdict(lambda: [0, 0])
for k in (ko - kn):
    changed[k[1]][0] += 1
for k in (kn - ko):
    changed[k[1]][1] += 1
for n in changed:
    if n in FROZEN:
        bad.append(('frozen net changed', n, changed[n]))
vo = {k for k in ko if k[0] == 'v'}; vn = {k for k in kn if k[0] == 'v'}
if vo != vn and not A.allow_vias:
    bad.append(('vias changed', sorted(vo - vn)[:4], sorted(vn - vo)[:4]))
wo = collections.defaultdict(set); wn = collections.defaultdict(set)
for k in ko:
    if k[0] == 't':
        wo[k[1]].add(k[3])
for k in kn:
    if k[0] == 't':
        wn[k[1]].add(k[3])
for n in changed:
    if not wn[n] <= wo[n]:
        bad.append(('new width', n, sorted(mm(w) for w in wn[n] - wo[n])))
    if n in fr.POWER and wn[n] and wo[n] and min(wn[n]) < min(wo[n]):
        bad.append(('power narrower', n))


# 1. stock DRC
def sibling_pro(path):
    p = os.path.splitext(path)[0] + '.kicad_pro'
    return p if os.path.exists(p) else None


PRO = cfg.file('drc_project') or sibling_pro(NEW) or sibling_pro(OLD)
if not PRO:
    print('warning: no .kicad_pro (gate.drc_project, or next to NEW/OLD): kicad-cli DRC runs with default rules',
          file=sys.stderr)
elif not os.path.exists(PRO):
    die(f'gate.drc_project not found: {PRO}')


def drc(path):
    import json
    pro = PRO
    d = tempfile.mkdtemp(prefix='kpns_gate_')
    try:
        t = os.path.join(d, 'b.kicad_pcb'); shutil.copy(path, t)
        if pro:
            shutil.copy(pro, os.path.join(d, 'b.kicad_pro'))
            dru = pro[:-len('.kicad_pro')] + '.kicad_dru'
            if os.path.exists(dru):
                shutil.copy(dru, os.path.join(d, 'b.kicad_dru'))
        j = os.path.join(d, 'drc.json')
        try:
            cp = subprocess.run(['kicad-cli', 'pcb', 'drc', '--refill-zones', '-o', j, '--format', 'json', t],
                                capture_output=True, text=True, timeout=900)
        except (OSError, subprocess.TimeoutExpired) as e:
            die(f'kicad-cli drc: {e}')
        if cp.returncode != 0 or not os.path.exists(j):
            die(f'kicad-cli drc failed (rc {cp.returncode}): {(cp.stderr or cp.stdout).strip()[-300:]}')
        r = json.load(open(j))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    v = collections.Counter(x['type'] for x in r['violations'] if x['type'] not in DRC_IGNORE)
    return len(r['unconnected_items']), dict(v)


un, vd = drc(NEW)
if un > cfg.get('max_unconnected', 0):
    bad.append(('unconnected', un))
exp = cfg.get('drc_expect')
if exp is not None:
    if vd != exp:
        bad.append(('drc', vd))
else:
    _, v0 = drc(OLD)
    worse = {k: (v0.get(k, 0), c) for k, c in vd.items() if c > v0.get(k, 0)}
    if worse:
        bad.append(('drc worse', worse))
# 2. fr.check
B = fr.Brd(NEW)
IGN = tuple(cfg.get('frcheck_ignore', []))
old_fc = set(fr.Brd(OLD).check())
fc = [x for x in B.check() if x not in old_fc and not (IGN and x.startswith(IGN))]
if fc:
    bad.append(('fr.check', fc[:5]))
# 3. margin on new / moved copper
newk = set(kn - ko)
geo = collections.defaultdict(list)
for (L, n, k, g, ref, smd) in B.items:
    geo[L].append((n, k, g, ref))
trees = {L: STRtree([x[2] for x in v]) for L, v in geo.items()}
for t in bn.GetTracks():
    if gkey(t) not in newk:
        continue
    n = t.GetNetname()
    if t.GetClass() == 'PCB_VIA':
        p = fr.P(t.GetPosition()); lays = list(fr.ORDER); gs = Point(p).buffer(mm(t.GetWidth(K.F_Cu)) / 2, 24); kind = 'via'
    else:
        s, e = fr.P(t.GetStart()), fr.P(t.GetEnd()); lays = [fr.LID.get(t.GetLayer())]
        gs = (LineString([s, e]) if s != e else Point(s)).buffer(mm(t.GetWidth()) / 2, 24); kind = 'trk'
    for L in lays:
        if L not in trees:
            continue
        for j in trees[L].query(gs.buffer(0.3)):
            n2, k2, g2, ref2 = geo[L][j]
            if n2 == n:
                continue
            need = fr.CTT if (kind == 'trk' and k2 == 'trk') else (fr.CFG['clearance_hole'] if k2 == 'hole' else fr.CTP)
            d = gs.distance(g2) + (fr.CFG['hole_margin'] - HOLE_EXTRA if k2 == 'hole' else 0)
            if d < need + MARGIN - 1e-6:
                bad.append(('margin', L, n, kind, n2, k2, round(d, 4), fr.desc(ref2)))
        if kind == 'trk' and gs.distance(B.outline.exterior) < fr.CE + MARGIN:
            bad.append(('edge margin', n))
# 4. pad exits of new segments
AXMIN = cfg.get('axis_min_pads', 3)
padc = []
for f in bn.GetFootprints():
    for p in f.Pads():
        if p.GetAttribute() != K.PAD_ATTRIB_SMD:
            continue
        bb = p.GetBoundingBox()
        padc.append((p.GetNetname(), bb.GetLeft(), bb.GetRight(), bb.GetTop(), bb.GetBottom(), len(f.Pads()), f.GetReference() + '.' + p.GetNumber(), p))
for t in bn.GetTracks():
    if t.GetClass() != 'PCB_TRACK' or gkey(t) not in newk:
        continue
    s_, e_ = t.GetStart(), t.GetEnd()
    for n, x0, x1, y0, y1, np_, nm, p in padc:
        if n != t.GetNetname() or not p.IsOnLayer(t.GetLayer()):
            continue
        ins = lambda q: x0 - 1000 <= q.x <= x1 + 1000 and y0 - 1000 <= q.y <= y1 + 1000
        if ins(s_) == ins(e_):
            continue
        dx, dy = abs(e_.x - s_.x), abs(e_.y - s_.y); w, h = x1 - x0, y1 - y0
        if dx > 1000 and dy > 1000:
            bad.append(('diagonal pad exit', nm, n))
        elif abs(w - h) > 50000 and np_ > AXMIN and ((w > h and dy > 1000) or (h > w and dx > 1000)):
            bad.append(('off-axis pad exit', nm, n))


# 5. free track ends
def freeends(bd, nets):
    out = collections.Counter(); ends = collections.Counter(); anc = set()
    for t in bd.GetTracks():
        if t.GetNetname() not in nets:
            continue
        if t.GetClass() == 'PCB_VIA':
            anc.add((t.GetNetname(), None, t.GetPosition().x, t.GetPosition().y)); continue
        for q in (t.GetStart(), t.GetEnd()):
            ends[(t.GetNetname(), t.GetLayer(), q.x, q.y)] += 1
    for f in bd.GetFootprints():
        for p in f.Pads():
            if p.GetNetname() in nets:
                anc.add((p.GetNetname(), None, p.GetPosition().x, p.GetPosition().y))
    for k, n in ends.items():
        if n == 1 and (k[0], None, k[2], k[3]) not in anc:
            out[k[0]] += 1
    return out


fe0, fe1 = freeends(bo, set(changed)), freeends(bn, set(changed))
for n in changed:
    if fe1[n] > fe0[n]:
        bad.append(('free track ends', n, fe0[n], '->', fe1[n]))
# 6. zones DRC does not know (new copper only)
oldk = set(rc.key(t) for t in bo.GetTracks())
FZ = cfg.get('forbid_new_copper', [])
HALO = []
for h in cfg.get('halo_pads', []):
    f = bn.FindFootprintByReference(h['ref'])
    if f is None:
        die(f"gate.halo_pads: no footprint {h['ref']}")
    HALO += [(h['layer'], fr.P(p.GetPosition()), h['r']) for p in f.Pads()]
NOTRK = set(bn.GetLayerID(x) for x in cfg.get('no_track_layers', []))
GAPZ = cfg.get('gap_zones', True)
for t in B.b.GetTracks():
    if rc.key(t) in oldk or t.GetClass() == 'PCB_VIA':
        continue
    if t.GetLayer() in NOTRK:
        bad.append(('track on ' + bn.GetLayerName(t.GetLayer()), t.GetNetname())); continue
    L = fr.LID.get(t.GetLayer())
    s, e = fr.P(t.GetStart()), fr.P(t.GetEnd()); w = fr.mm(t.GetWidth())
    cl = LineString([s, e]) if s != e else Point(s)
    g = cl.buffer(w / 2 - 0.005)
    for z in FZ:
        r = z['rect']
        if z['layer'] == L and g.intersects(box(r[0], r[2], r[1], r[3])) and not any(
                g.intersects(pg) for (l, n, k, pg, ref, smd) in B.items
                if l == L and k == 'pad' and n == t.GetNetname() and ref[0] in z.get('allow_pads_of', [])):
            bad.append(('forbidden zone', L, tuple(r), t.GetNetname(), s, e))
    for (hl, c, r) in HALO:
        if hl == L and Point(c).distance(cl) < r + w / 2 - 0.01:
            bad.append(('pad halo', t.GetNetname(), s, e))
    for gz in (B.gapz.get(L, []) if GAPZ else []):
        if g.intersects(gz.buffer(-0.01)):
            own = [pg for (l, n, k, pg, ref, smd) in B.items if l == L and k == 'pad' and n == t.GetNetname() and pg.distance(gz) < 1e-3]
            if not own:
                bad.append(('inter-pad gap', t.GetNetname(), s, e))


def fan(p):
    o = subprocess.run([STOCK_PY, os.path.join(TOOLS, 'fancheck.py'), p], capture_output=True, text=True).stdout
    cnt = {m.group(1): int(m.group(2)) for m in re.finditer(r'^(non-45|ends inside|pad exits|hairpins|zigzag|detours)\S*.*? (\d+) [\[(]', o, re.M)}
    lst = {}
    for m in re.finditer(r'^(non-45|ends inside|pad exits|hairpins|zigzag|detours)\S*.*? \d+ (\[.*\])$', o, re.M):
        try:
            lst[m.group(1)] = ast.literal_eval(m.group(2))
        except Exception:
            lst[m.group(1)] = []
    return cnt, lst


(c0, f0), (c1, f1) = fan(OLD), fan(NEW)
for k in cfg.get('fancheck_not_worse', ['non-45', 'ends inside', 'pad exits']):
    if c1.get(k, 0) > c0.get(k, 0):
        bad.append(('fancheck ' + k, c0.get(k, 0), '->', c1[k], [x for x in f1.get(k, []) if x not in f0.get(k, [])][:3]))
# 7. rule 5
if cfg.get('rule5', True) and not A.no_rule5:
    def norm(e):
        e = tuple(round(v, 1) if isinstance(v, float) else v for v in e)
        if len(e) == 8:
            e = e[:2] + tuple(sorted([e[2:4], e[4:6]])) + e[6:7]   # detour: unordered ends; length to 0.1
        return e
    for k in ('hairpins', 'zigzag', 'detours'):
        old = {norm(e) for e in f0.get(k, [])}
        for e in f1.get(k, []):
            if norm(e) not in old:
                bad.append(('new ' + k, e))
    t0 = len(f0.get('zigzag', [])) + len(f0.get('detours', [])); t1 = len(f1.get('zigzag', [])) + len(f1.get('detours', []))
    if t1 >= t0:
        bad.append(('rule5 not down', t0, t1))
xc = cfg.get('extra_cmd')
if xc:
    r = subprocess.run(list(xc) + [OLD, NEW], capture_output=True, text=True)
    if r.returncode:
        bad.append(('extra_cmd', r.stdout.strip().splitlines()[-4:]))
print('CHANGED', dict(changed))
print('RULE5', len(f0.get('zigzag', [])), len(f0.get('detours', [])), '->', len(f1.get('zigzag', [])), len(f1.get('detours', [])))
for x in bad:
    print('FAIL', x)
print('PASS' if not bad else 'REJECT')
sys.exit(1 if bad else 0)
