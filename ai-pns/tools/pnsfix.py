"""pnsfix.py CUR OUTDIR --socket S|--instance N --config CFG [--nets A,B] [--allow-delete] : straighten rule-5
defects (zigzag jogs, detours; see fancheck.py) with the fork's push-and-shove router, one chain at a time,
each accepted only through gate.py.

Run it with $KPNS_PY (protobuf + pynng). The fork instance must hold CUR (a stock KiCad 10 board) - start it
with host/hoststart_n.sh on CUR, ideally with rules a little stricter than the real ones (e.g. +2 um) so PNS
never hugs a clearance, and lock what must not be shoved (tools/lock.py --frozen ... --vias). Stock pcbnew
tools (chains.py, fancheck.py, gate.py) run with $KPNS_STOCK_PY (default python3).

Loop: targets = chains.py chains of the current board that carry a fancheck jog or detour (nets in
pnsfix.skip_nets are left alone, --nets restricts). For the first untried target the attempts are, in order:
  widths  the chain's widest width, then (not for pnsfix.keep_width_nets, mixed-width chains only) its narrowest;
  ends    "full" chain end to end; "stubs" keeping clean axis-parallel end segments; "axis" with synthetic
          on-axis exits from SMD pad ends (pad half length + 0.15 mm);
  modes   walkaround, then shove;
  delete  (--allow-delete, nets in pnsfix.delete_only_nets, e.g. a pour net) just delete the chain, unless an
          end is in pnsfix.nodelete_points [[x, y], ...].
An attempt = snapshot, delete the chain's segments, RouteTrack (mitered 45, finish on the end node), then:
route complete, the net does not open, no new fork DRC violation of the net near the chain; save, copy the
fork copper into the current stock board (k10.py) and run gate.py CUR NEW NET. Pass: OUTDIR/accNN.kicad_pcb
becomes current. Fail: rollback (verified against the snapshot geometry). Ends when no target is left.
"""
import argparse
import ast
import collections
import json
import os
import re
import subprocess
import sys
import time

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(TOOLS, '..', 'pyapi'))
import routecfg as rc  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__.split('\n')[0], epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('cur', metavar='CUR', help='stock KiCad 10 board the fork instance holds')
ap.add_argument('outdir', metavar='OUTDIR')
g = ap.add_mutually_exclusive_group(required=True)
g.add_argument('--socket', help='API socket, ipc://...')
g.add_argument('--instance', type=int, help='hoststart_n.sh instance number')
rc.add_config_arg(ap)
ap.add_argument('--nets', default='', help='only targets of these nets')
ap.add_argument('--allow-delete', action='store_true', help='try deleting chains of pnsfix.delete_only_nets')
ap.add_argument('--box-margin', type=float, default=1.5, help='new fork violations count within this of the chain')
A = ap.parse_args()

import rt  # noqa: E402
import pns  # noqa: E402

cfg = rc.Config(A.config, 'pnsfix')
CUR, OUT = A.cur, A.outdir
FILT = set(rc.csv(A.nets))
os.makedirs(OUT, exist_ok=True)
STOCK_PY = os.environ.get('KPNS_STOCK_PY', 'python3')
KEEPW = cfg.nets('keep_width_nets')
SKIP = cfg.nets('skip_nets')
DELNETS = cfg.nets('delete_only_nets')
NODEL = [tuple(p) for p in cfg.get('nodelete_points', [])]
R = rt.R(A.socket if A.socket else A.instance)
near = lambda a, b: abs(a[0] - b[0]) < 0.002 and abs(a[1] - b[1]) < 0.002
CFGARGS = ['--config', A.config] if A.config else []


def targets(cur):
    subprocess.run([STOCK_PY, os.path.join(TOOLS, 'chains.py'), cur, OUT + '/t.json'], capture_output=True)
    fc = subprocess.run([STOCK_PY, os.path.join(TOOLS, 'fancheck.py'), cur], capture_output=True, text=True).stdout
    lst = {m.group(1): ast.literal_eval(m.group(2)) for m in re.finditer(r'^(zigzag|detours)\S*.*? \d+ (\[.*\])$', fc, re.M)}
    LM = lambda s: 'F' if s == 'F.C' else 'B' if s == 'B.C' else s[2:]   # fancheck prints layer names cut to 3 chars
    out = []
    for c in json.load(open(OUT + '/t.json')):
        hit = False
        for e in lst['zigzag']:
            if e[0] == c['net'] and LM(e[1]) == c['layer'] and any(abs(p[0] - e[2]) < 0.003 and abs(p[1] - e[3]) < 0.003 for p in c['pts']):
                hit = True
        for e in lst['detours']:
            if e[0] == c['net'] and LM(e[1]) == c['layer'] and {(round(c['A'][0], 2), round(c['A'][1], 2)), (round(c['B'][0], 2), round(c['B'][1], 2))} == {(e[2], e[3]), (e[4], e[5])}:
                hit = True
        if hit and c['net'] not in SKIP:
            out.append(c)
    return out


def gate(old, new, net):
    r = subprocess.run([STOCK_PY, os.path.join(TOOLS, 'gate.py'), old, new, net] + CFGARGS, capture_output=True, text=True)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith(('FAIL', 'RULE5', 'CHANGED', 'PASS', 'REJECT'))]
    return r.returncode == 0, lines


def gkey(o):
    if hasattr(o, 'start'):
        return ('t', o.net.name, o.layer, o.width.value_nm, tuple(sorted([(round(o.start.x_nm / 1e3), round(o.start.y_nm / 1e3)), (round(o.end.x_nm / 1e3), round(o.end.y_nm / 1e3))])))
    return ('v', o.net.name, round(o.position.x_nm / 1e3), round(o.position.y_nm / 1e3))


def restore(before):
    """rollback, then verify the copper against the snapshot; extra items left by a failed shove are deleted"""
    from nk_base import delete
    for i in range(3):
        pns.rollback(R.c, R.doc, before)
        now = pns.copper_items(R.c, R.doc)
        a = collections.Counter(gkey(o) for o in before.values()); b = collections.Counter(gkey(o) for o in now.values())
        if a == b:
            R.refresh(); return True
        print('   restore mismatch', i, list((a - b).keys())[:3], list((b - a).keys())[:3], flush=True)
        extra = b - a; ids = []
        for o in now.values():
            k = gkey(o)
            if extra.get(k, 0) > 0:
                ids.append(o.id); extra[k] -= 1
        if ids:
            delete(R.c, R.doc, ids)
    R.refresh(); raise SystemExit('RESTORE FAILED: restart the fork instance from the last accepted board')


def to_stock(cur):
    R.save(OUT + '/fork.kicad_pcb'); new = OUT + '/cand.kicad_pcb'
    subprocess.run([sys.executable, os.path.join(TOOLS, 'k10.py'), cur, OUT + '/fork.kicad_pcb', new], capture_output=True)
    return new


def attempt(c, pts, segs, w, mode, cur, tag):
    before = pns.snapshot(R.c, R.doc)
    S = [((s[0], s[1]), (s[2], s[3])) for s in segs]
    L = rt.L[c['layer']]

    def pred(k, gg, lay):
        if k != 'track' or lay != L:
            return False
        a, b = (gg[0], gg[1]), (gg[2], gg[3])
        return any((near(a, p) and near(b, q)) or (near(a, q) and near(b, p)) for p, q in S)
    u_before = R.unc.get(c['net'], 0); b0 = R.bad
    nd = rt.delete_where(R, [c['net']], pred)
    if nd != len(segs):
        print('   delete mismatch', nd, len(segs)); restore(before); return False
    if pts:
        try:
            r = pns.route_track(R.c, R.doc, (pts[0][0], -pts[0][1]), [(p[0], -p[1]) for p in pts[1:]], layer=L, mode=mode, width=w,
                                finish=True, corner='mitered45', point_layers=[L] * (len(pts) - 1))
        except Exception as e:
            print('   ', tag, 'route ERROR', e); restore(before); return False
        R.refresh()
        xs = [p[0] for p in c['pts']]; ys = [p[1] for p in c['pts']]; M = A.box_margin
        inbox = lambda x: min(xs) - M <= x[1] / 10 <= max(xs) + M and min(ys) - M <= -x[2] / 10 <= max(ys) + M
        newbad = [x for x in (R.bad - b0) if any(('[%s]' % c['net']) in d for d in x[3]) and inbox(x)]
        if not r.success or R.unc.get(c['net'], 0) > u_before or newbad:
            print('   ', tag, 'route REJECT', r.success, r.message[:60], 'open', R.unc.get(c['net'], 0), 'newbad',
                  [(x[0], x[1] / 10, -x[2] / 10) for x in newbad][:3], flush=True)
            restore(before); return False
    new = to_stock(cur)
    ok, lines = gate(cur, new, c['net'])
    print('   ', tag, 'gate', 'PASS' if ok else 'REJECT', ' ; '.join(ln[:200] for ln in lines if not ln.startswith(('PASS', 'REJECT'))), flush=True)
    if not ok:
        restore(before); return False
    return new


def variants(c):
    """(route points, segments to delete, tag) in the order they are tried"""
    pts = [tuple(p) for p in c['pts']]; segs = c['segs']
    v = [([pts[0], pts[-1]], segs, 'full')]

    def axis(a, b): return abs(a[0] - b[0]) < 1e-4 or abs(a[1] - b[1]) < 1e-4
    a0 = 1 if len(pts) > 2 and axis(pts[0], pts[1]) else 0
    b0 = 1 if len(pts) > 2 + a0 and axis(pts[-2], pts[-1]) else 0
    if a0 or b0:
        v.append(([pts[a0], pts[len(pts) - 1 - b0]], segs[a0:len(segs) - b0], 'stubs'))

    def ext(p, q, info):
        if not info or info['sq']:
            return None
        d = info['h'] + 0.15
        if info['ax'] == 'x':
            return (p[0] + (d if q[0] > p[0] else -d), p[1])
        return (p[0], p[1] + (d if q[1] > p[1] else -d))
    ea = ext(pts[0], pts[-1], c.get('padA')); eb = ext(pts[-1], pts[0], c.get('padB'))
    if ea or eb:
        v.append(([pts[0]] + ([ea] if ea else []) + ([eb] if eb else []) + [pts[-1]], segs, 'axis'))
    if c['net'] in DELNETS and A.allow_delete and not any(abs(q[0] - p[0]) < 0.02 and abs(q[1] - p[1]) < 0.02 for p in NODEL for q in (pts[0], pts[-1])):
        v.append(([], segs, 'delete'))
    return v


nacc = 0; tried = set(); cur = CUR
while True:
    T = [c for c in targets(cur) if (not FILT or c['net'] in FILT)]
    T = [c for c in T if (c['net'], c['layer'], tuple(round(v, 2) for v in c['A']), tuple(round(v, 2) for v in c['B'])) not in tried]
    print(time.strftime('%H:%M:%S'), 'targets left', len(T), flush=True)
    if not T:
        break
    c = T[0]; tried.add((c['net'], c['layer'], tuple(round(v, 2) for v in c['A']), tuple(round(v, 2) for v in c['B'])))
    print('TARGET', c.get('kind', ''), c['net'], c['layer'], [round(v, 2) for v in c['A']], [round(v, 2) for v in c['B']],
          'ln', round(c['ln'], 2), 'st', round(c['st'], 2), 'w', sorted(set(c['ws'])), flush=True)
    ws = [max(c['ws'])]
    if min(c['ws']) < max(c['ws']) and c['net'] not in KEEPW:
        ws.append(min(c['ws']))
    done = False
    for w in ws:
        for pts, segs, sv in variants(c):
            for mode in (('walkaround', 'shove') if pts else ('none',)):
                tag = f'{sv} w{w:.4f} {mode}'
                r = attempt(c, pts, segs, w, mode, cur, tag)
                if r:
                    nacc += 1; acc = f'{OUT}/acc{nacc:02d}.kicad_pcb'; os.replace(r, acc); cur = acc
                    print('ACCEPT', nacc, c['net'], c['layer'], tag, '->', acc, flush=True); done = True
                    break
            if done:
                break
        if done:
            break
print('DONE accepted', nacc, 'final', cur)
