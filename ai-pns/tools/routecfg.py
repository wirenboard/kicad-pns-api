"""routecfg.py : shared config and helpers of the board-editing routing tools (mincut.py, pocket.py,
polyfix.py, chains.py, gate.py, pnsfix.py). Not a command.

The tools keep no board knowledge in their code. Everything specific to one board lives in one JSON
(or YAML, with PyYAML installed) file passed with --config; run knobs are command-line options.
Relative paths in the file are relative to the file. Keys (all optional):

  fr                  grid-router config: a dict, or a path to a JSON file, given to fr.configure()
                      (see gridrouter/fr.py). Missing: $FR_CONFIG, else fr's defaults.
  plane_nets          ["GND"]  nets carried by a plane/pour: never ripped, not counted as open
  protected_nets      []       nets the tools never rip, strip or re-route (RF, matched pairs, sense lines)
  frozen_nets         []       never ripped or re-routed (mincut, pocket); gate.py: their copper must stay identical
  high_cost_nets      []       mincut.py: crossing their copper costs pen_high per cell (power trunks)
  reservations        null     a .kicad_pcb whose tracks/vias are "reserved" (a via plan): matching copper
                               (same net, geometry to 1 um) is kept unless the tool is told to rip it
  window              null     [x0, x1, y0, y1] default working window (default: board outline bounds)
  pad_exits           []       forced pad exit directions for lib2: {"ref": "J1", "pads": "odd"|"even"|"all"|
                               ["1", "2"], "dir": "N"|"S"|"E"|"W"} (pads "all"/"odd"/"even" = numeric pads)
  via_forbid_rects    []       [x0, x1, y0, y1]: no vias planned/placed there (in addition to fr's own)
  rule_area_via_forbid true    rule areas of the board that forbid vias are added to via_forbid_rects
  width_rules         see WIDTH_RULES: first matching rule gives the widths tried, widest first:
                      {"nets": [...]} | {"prefix": "USB_"} | {"power": true} | {"default": true},
                      plus "widths": [...] and optionally "plan": "first"|"last" (mincut's planning width)
  pairs               []       [["P", "N"], ...] routed back to back (pocket.py)
  mincut, pocket, gate, pnsfix   per-tool sections; a key given there overrides the top-level one.
                      Keys only known in a section (each documented in that tool's --help):
                        pocket  move_hole_clearance
                        gate    drc_project, drc_expect, drc_ignore, max_unconnected, frcheck_ignore, margin,
                                hole_extra, axis_min_pads, forbid_new_copper, halo_pads, gap_zones,
                                no_track_layers, fancheck_not_worse, rule5, extra_cmd
                        pnsfix  keep_width_nets, skip_nets, delete_only_nets, nodelete_points
                      Unknown keys, at the top level or in a section, are errors.

Coordinates are mm, y up (y = -KiCad y), as in fr.py. Layer letters are fr's (fr config "layers").
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GRID = os.path.normpath(os.path.join(HERE, '..', 'gridrouter'))
PYAPI = os.path.normpath(os.path.join(HERE, '..', 'pyapi'))

WIDTH_RULES = [{'power': True, 'widths': [0.4064]}, {'default': True, 'widths': [0.254, 0.2032]}]
DEFAULTS = dict(fr=None, plane_nets=['GND'], protected_nets=[], frozen_nets=[], high_cost_nets=[], reservations=None,
                window=None, pad_exits=[], via_forbid_rects=[], rule_area_via_forbid=True, width_rules=WIDTH_RULES,
                pairs=[], mincut={}, pocket={}, gate={}, pnsfix={})
SECTIONS = ('mincut', 'pocket', 'gate', 'pnsfix')
SECTION_KEYS = dict(mincut=set(), pocket={'move_hole_clearance'},
                    gate={'drc_project', 'drc_expect', 'drc_ignore', 'max_unconnected', 'frcheck_ignore', 'margin',
                          'hole_extra', 'axis_min_pads', 'forbid_new_copper', 'halo_pads', 'gap_zones',
                          'no_track_layers', 'fancheck_not_worse', 'rule5', 'extra_cmd'},
                    pnsfix={'keep_width_nets', 'skip_nets', 'delete_only_nets', 'nodelete_points'})


def astar_lib():
    """path of libastar.so: next to astar.c, or (read-only install) in the user cache; built once with cc"""
    so = os.environ.get('FR_ASTAR_LIB') or os.path.join(GRID, 'libastar.so')
    if os.path.exists(so):
        return so
    if not os.access(os.path.dirname(so), os.W_OK):
        cache = os.path.join(os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'), 'kicad-pns')
        os.makedirs(cache, exist_ok=True)
        so = os.path.join(cache, 'libastar.so')
        if os.path.exists(so) and os.path.getmtime(so) >= os.path.getmtime(os.path.join(GRID, 'astar.c')):
            os.environ['FR_ASTAR_LIB'] = so
            return so
    try:
        subprocess.check_call(['cc', '-O2', '-shared', '-fPIC', '-o', so, os.path.join(GRID, 'astar.c'), '-lm'])
    except (OSError, subprocess.CalledProcessError) as e:
        raise SystemExit(f'cannot build {so} from gridrouter/astar.c ({e}); build it by hand: '
                         'cc -O2 -shared -fPIC -o libastar.so astar.c -lm, and point FR_ASTAR_LIB at it')
    os.environ['FR_ASTAR_LIB'] = so
    return so


def gridrouter():
    """import and return (fr, lib2) from ../gridrouter (libastar.so via astar_lib())"""
    astar_lib()
    if GRID not in sys.path:
        sys.path.insert(0, GRID)
    import fr
    import lib2
    return fr, lib2


def _read(path):
    with open(path) as f:
        if path.endswith(('.yaml', '.yml')):
            import yaml
            return yaml.safe_load(f) or {}
        return json.load(f)


class Config:
    """board config; cfg.get(key) reads the tool section first, then the top level, then DEFAULTS"""

    def __init__(self, path=None, section=None, data=None):
        self.path = path
        self.section = section
        raw = data if data is not None else (_read(path) if path else {})
        bad = [k for k in raw if not k.startswith('_') and k not in DEFAULTS]
        for sec in SECTIONS:
            bad += [f'{sec}.{k}' for k in raw.get(sec, {}) if not k.startswith('_') and k not in DEFAULTS
                    and k not in SECTION_KEYS[sec]]
        if bad:
            raise SystemExit(f'unknown config keys: {bad}')
        self.raw = raw
        self.base = os.path.dirname(os.path.abspath(path)) if path else os.getcwd()

    def get(self, key, default=None):
        sec = self.raw.get(self.section, {}) if self.section else {}
        if key in sec:
            return sec[key]
        if key in self.raw:
            return self.raw[key]
        return DEFAULTS.get(key, default) if key in DEFAULTS else default

    def file(self, key):
        p = self.get(key)
        return None if p is None else (p if os.path.isabs(p) else os.path.join(self.base, p))

    def apply_fr(self, fr):
        """configure the grid router (fr) from the "fr" key; nothing given -> leave fr as imported"""
        f = self.raw.get('fr')
        if f is None:
            return
        if isinstance(f, str):
            f = f if os.path.isabs(f) else os.path.join(self.base, f)
        fr.configure(f)

    def nets(self, key):
        return set(self.get(key) or [])


def add_config_arg(ap):
    ap.add_argument('--config', '-c', help='board config (JSON or YAML), see routecfg.py')


def csv(s):
    return [x for x in (s or '').split(',') if x]


def floats(s, n=None):
    v = tuple(float(x) for x in s.split(','))
    if n and len(v) != n:
        raise SystemExit(f'expected {n} comma-separated numbers: {s!r}')
    return v


def tmpdir():
    """private scratch directory, removed when the process exits"""
    import atexit
    import shutil
    d = tempfile.mkdtemp(prefix='kpns_tool_')
    atexit.register(shutil.rmtree, d, ignore_errors=True)
    return d


# ---- geometry keys -------------------------------------------------------------------------------
def key(t):
    """net + geometry of a track/via rounded to 1 um (identity across saves: UUIDs change, geometry does not)"""
    if t.GetClass() == 'PCB_VIA':
        return ('v', t.GetNetname(), round(t.GetPosition().x / 1e3), round(t.GetPosition().y / 1e3))
    return ('t', t.GetNetname(), t.GetLayer(), tuple(sorted([(round(t.GetStart().x / 1e3), round(t.GetStart().y / 1e3)),
                                                            (round(t.GetEnd().x / 1e3), round(t.GetEnd().y / 1e3))])))


def reservations(cfg):
    """set of key() of the reserved copper (config "reservations" board), empty if none"""
    p = cfg.file('reservations')
    if not p:
        return set()
    import pcbnew as K
    return set(key(t) for t in K.LoadBoard(p).GetTracks())


# ---- board helpers on fr.Brd ----------------------------------------------------------------------
def bounds(B):
    x0, y0, x1, y1 = B.outline.bounds
    return (x0, x1, y0, y1)


def window(cfg, B, override=None):
    if override:
        return override
    w = cfg.get('window')
    return tuple(w) if w else bounds(B)


def clamp(win, B):
    x0, x1, y0, y1 = bounds(B)
    return (max(x0, win[0]), min(x1, win[1]), max(y0, win[2]), min(y1, win[3]))


def apply_pad_exits(cfg, B, lib2):
    for e in cfg.get('pad_exits') or []:
        f = B.b.FindFootprintByReference(e['ref'])
        if f is None:
            raise SystemExit(f"pad_exits: no footprint {e['ref']}")
        nums = [p.GetNumber() for p in f.Pads()]
        sel = e.get('pads', 'all')
        if isinstance(sel, list):
            chosen = [str(x) for x in sel]
        else:
            num = sorted(set(int(n) for n in nums if n.isdigit()))
            chosen = [str(n) for n in num if sel == 'all' or (sel == 'odd' and n % 2) or (sel == 'even' and not n % 2)]
        for n in chosen:
            lib2.EXITS[(e['ref'], n)] = e['dir']


def via_forbid(cfg, B, fr):
    """extra_forbid dict for lib2.connect / fr.maps: config via_forbid_rects + the board's no-via rule areas"""
    import pcbnew as K
    from shapely.geometry import Polygon, box
    ra = [box(r[0], r[2], r[1], r[3]) for r in cfg.get('via_forbid_rects') or []]
    if cfg.get('rule_area_via_forbid'):
        for z in B.b.Zones():
            if z.GetIsRuleArea() and z.GetDoNotAllowVias():
                o = z.Outline().Outline(0)
                ra.append(Polygon([(K.ToMM(o.CPoint(i).x), -K.ToMM(o.CPoint(i).y)) for i in range(o.PointCount())]))
    return {'via': ra} if ra else None


def check_nets(B, nets, frozen=()):
    """exit 2 for a net the board does not have or a frozen one"""
    have = set(str(n) for n in B.b.GetNetsByName().keys())
    bad = [n for n in nets if n not in have]
    if bad:
        print('no such net:', ', '.join(bad), file=sys.stderr); sys.exit(2)
    fz = [n for n in nets if n in frozen]
    if fz:
        print('frozen net (config frozen_nets):', ', '.join(fz), file=sys.stderr); sys.exit(2)


def signal_nets(cfg, B):
    """all pad nets except the plane nets"""
    return sorted(set(p.GetNetname() for f in B.b.GetFootprints() for p in f.Pads()) - {''} - cfg.nets('plane_nets'))


def opens(cfg, B, lib2, nets=None):
    """net -> number of missing connections (islands - 1)"""
    return {n: len(lib2.islands(B, n)) - 1 for n in (nets if nets is not None else signal_nets(cfg, B))}


def rule_for(cfg, net, fr):
    for r in cfg.get('width_rules') or WIDTH_RULES:
        if ('nets' in r and net in r['nets']) or ('prefix' in r and net.startswith(r['prefix'])) \
                or (r.get('power') and net in fr.POWER) or r.get('default'):
            return r
    return {'widths': [0.254]}


def widths(cfg, net, fr):
    return list(rule_for(cfg, net, fr)['widths'])


def plan_width(cfg, net, fr):
    r = rule_for(cfg, net, fr)
    return r['widths'][-1] if r.get('plan') == 'last' else r['widths'][0]


def connect_net(B, lib2, net, ws, wins, ef=None, guard=8, margins=(0.015, 0.03), maxexp=40000000, viacost=30):
    """connect all islands of net with the grid router, smallest island first; per island tries every window
    in wins (a list, or a function of nothing returning one, evaluated per connection), every width in ws
    (widest first) and every margin; a result that adds a clearance finding of the net is undone.
    Returns True when the net is one island."""
    for _ in range(guard):
        comps = lib2.islands(B, net)
        if len(comps) < 2:
            return True
        ok = False
        for ci in sorted(range(len(comps)), key=lambda k: len(comps[k])):
            for win in (wins() if callable(wins) else wins):
                for w in ws:
                    for m in margins:
                        r = lib2.connect(B, net, ci=ci, w=w, res=0.025, m=m, win=win, layers=''.join(lib2.fr.ORDER),
                                         viacost=viacost, turn45=2, turn90=20, commit=False, verbose=False,
                                         maxexp=maxexp, extra_forbid=ef)
                        if not r:
                            continue
                        base = set(B.check([net]))
                        new = B.commit(net, r, w)
                        if set(B.check([net])) - base:
                            for t in new:
                                B.b.Delete(t)
                            B.load_geom()
                            continue
                        ok = True
                        break
                    if ok:
                        break
                if ok:
                    break
            if ok:
                break
        if not ok:
            return False
    return len(lib2.islands(B, net)) < 2

