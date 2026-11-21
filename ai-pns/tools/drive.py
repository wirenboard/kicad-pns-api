#!/usr/bin/env python3
"""drive.py GUIDES.json [--socket ipc://...] [--layers F.Cu,In2.Cu,B.Cu] [--via 0.7/0.3]
                [--rip] [--no-rip NET,NET,...] [--save OUT.tracks.json]

Route guide paths (made by any planner, e.g. a grid router) with KiCad's push & shove router in a
running fork instance. Each guide: RouteTrack(start anchor, corner points with per-point layer, end
anchor, finish, mitered 45), first in shove mode, then walkaround -> kept only if the net's open
connection count dropped and the board's copper violations did not grow; otherwise rolled back
(shoved neighbours included).

GUIDES.json: a list of objects
  {"net": "NET", "w": 0.254,                      track width, mm
   "a": [x, y], "la": 0,                          start anchor (pad/via/track of the net) + layer index
   "b": [x, y], "lb": 2,                          end anchor + layer index
   "pts": [[x, y, layer_index], ...],             corner points (a layer change between points = via)
   "blk": [[x0, y0, x1, y1, "OTHER_NET"], ...]}   optional: segments of other nets blocking the path
Layer indices refer to --layers (default F.Cu,In2.Cu,B.Cu). Coordinates in KiCad mm (y down).

--rip      if both modes fail and the guide lists blockers, delete the blocking segments and retry
           once in shove mode (nets in --no-rip and nets already routed by this run are never ripped).
--socket   API socket (default: $KPNS_SOCKET, else instance 1 of host/hoststart_n.sh).
--save     dump all tracks/vias at the end for transplant.py (the fork saves only 10.99 files).
"""
import argparse, collections, json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pyapi"))
from pns import *          # noqa
from google.protobuf import json_format

COPPER = {'clearance', 'tracks_crossing', 'shorting_items', 'hole_clearance', 'copper_edge_clearance',
          'items_not_allowed', 'via_dangling', 'track_dangling', 'hole_to_hole', 'diff_pair_gap_out_of_range'}
c = doc = None


def connect(sock=None):
    global c, doc
    c = KiCadClient(sock or os.environ.get('KPNS_SOCKET') or socket_of(1), f'drive{os.getpid()}', '', 300000)
    doc = board_doc(c)
    return c, doc


def layer_ids(names):
    """'F.Cu,In2.Cu,B.Cu' -> [bdt.BL_F_Cu, bdt.BL_In2_Cu, bdt.BL_B_Cu]"""
    return [getattr(bdt, 'BL_' + n.strip().replace('.', '_')) for n in names.split(',') if n.strip()]


def state():
    """(unconnected count per net, list of copper violations) after a zone refill"""
    v = run_drc(c, doc, refill=True)
    unc = collections.Counter(x.item_descriptions[0].split('[')[1].split(']')[0] if '[' in x.item_descriptions[0] else '?'
                              for x in v if x.type == 'unconnected_items')
    cop = [x for x in v if x.type in COPPER]
    return unc, cop


def sig(x):
    return (x.type, round(x.position.x_nm / 1e5), round(x.position.y_nm / 1e5))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('guides')
    ap.add_argument('--socket')
    ap.add_argument('--layers', default='F.Cu,In2.Cu,B.Cu')
    ap.add_argument('--via', default='0.7/0.3', help='via diameter/drill, mm')
    ap.add_argument('--rip', action='store_true')
    ap.add_argument('--no-rip', default='', help='comma-separated nets that are never ripped')
    ap.add_argument('--save')
    a = ap.parse_args()
    connect(a.socket)
    LAY = layer_ids(a.layers)
    vd, vdr = (float(x) for x in a.via.split('/'))
    NO_RIP = {n.strip() for n in a.no_rip.split(',') if n.strip()}

    guides = json.load(open(a.guides))
    unc, cop = state()
    print('start: unconnected', sum(unc.values()), 'copper viol', len(cop), flush=True)
    ok_n = 0
    protected = set()
    for g in guides:
        net = g['net']
        if unc.get(net, 0) == 0:
            continue
        before = snapshot(c, doc); t0 = time.time()
        pts = [(p[0], p[1]) for p in g['pts']] + [tuple(g['b'][:2])]
        lays = [LAY[p[2]] for p in g['pts']] + [LAY[g['lb']]]
        if pts and abs(pts[0][0] - g['a'][0]) + abs(pts[0][1] - g['a'][1]) < 1e-6:
            pts, lays = pts[1:], lays[1:]
        res = None
        for mode in ('shove', 'walkaround'):
            try:
                r = route_track(c, doc, tuple(g['a'][:2]), pts, layer=LAY[g['la']], mode=mode, width=g['w'],
                                finish=True, corner='mitered45', point_layers=lays, via_diameter=vd, via_drill=vdr)
            except Exception as e:
                print(f'  {net}: error {e}'); rollback(c, doc, before); continue
            u2, cop2 = state()
            new = {sig(x) for x in cop2} - {sig(x) for x in cop}
            if r.success and u2.get(net, 0) < unc.get(net, 0) and not new:
                res = (mode, u2, cop2); break
            rollback(c, doc, before)
            why = r.message or ('still open' if u2.get(net, 0) >= unc.get(net, 0) else f'{len(new)} new violations {sorted(new)[:3]}')
            print(f'  {net}: {mode} rejected: {why}')
        victims = sorted({b[4] for b in g.get('blk', [])})
        if not res and victims and not (set(victims) & (protected | NO_RIP)) and a.rip:
            snap = snapshot(c, doc); kill = []
            for b4 in g['blk']:
                for it in snap.values():
                    if isinstance(it, bdt.Track) and it.net.name == b4[4]:
                        s0 = (it.start.x_nm / 1e6, it.start.y_nm / 1e6); e0 = (it.end.x_nm / 1e6, it.end.y_nm / 1e6)
                        if any(abs(s0[0] - p[0]) + abs(s0[1] - p[1]) + abs(e0[0] - q[0]) + abs(e0[1] - q[1]) < 0.005
                               for p, q in (((b4[0], b4[1]), (b4[2], b4[3])), ((b4[2], b4[3]), (b4[0], b4[1])))):
                            kill.append(it.id)
            if kill:
                delete(c, doc, kill)
                r = route_track(c, doc, tuple(g['a'][:2]), pts, layer=LAY[g['la']], mode='shove', width=g['w'],
                                finish=True, corner='mitered45', point_layers=lays, via_diameter=vd, via_drill=vdr)
                u2, cop2 = state()
                new = {sig(x) for x in cop2} - {sig(x) for x in cop}
                if r.success and u2.get(net, 0) < unc.get(net, 0) and not new:
                    res = ('rip ' + ','.join(victims), u2, cop2); protected.add(net)
                else:
                    rollback(c, doc, before); print(f'  {net}: rip of {victims} did not help: {r.message or len(new)}')
        if res:
            ok_n += 1; unc, cop = res[1], res[2]
            print(f'{net:16s} OK ({res[0]}, {time.time() - t0:.1f}s) -> unconnected {sum(unc.values())}', flush=True)
        else:
            print(f'{net:16s} FAILED', flush=True)
    print('routed', ok_n, 'of', len(guides), '| unconnected', sum(unc.values()), dict(unc))
    if a.save:
        snap = snapshot(c, doc)
        json.dump([{'kind': type(it).__name__, 'msg': json_format.MessageToDict(it)} for it in snap.values()], open(a.save, 'w'))
        print('saved', len(snap), 'items to', a.save)


if __name__ == '__main__':
    main()
