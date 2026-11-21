"""rt.py - interactive routing helper for a fork instance (python with protobuf + pynng).

    import rt; R = rt.R(1)            # instance 1 of host/hoststart_n.sh (or rt.R('ipc:///path/api.sock'))
    R.go('NET', [(x,y,'F'), (x,y,'F'), (x,y,'B')], w=0.254)   # first point = start anchor
    R.save('ckpt.kicad_pcb')
Coordinates are in mm. With flip_y=True (default) they are y-up ("math"/EAGLE style: y = -KiCad y);
pass R(n, flip_y=False) to use KiCad's own y-down coordinates.
Each go(): route_track (shove, mitered45, finish at last point) -> DRC of the net + global copper counts;
rolled back if copper violations grew or the net's open count did not drop (unless keep=True).
Layer letters: F, B, and 1..30 for In1.Cu..In30.Cu. A layer change between points = via
(vd/vdr, default 0.7/0.3 - the router does not use the netclass via size).
"""
import os, sys, collections, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pyapi"))
import pns
from pns import snapshot, rollback
from nk_base import KiCadClient, board_doc, bdt

L = {'F': bdt.BL_F_Cu, 'B': bdt.BL_B_Cu}
L.update({str(i): getattr(bdt, f'BL_In{i}_Cu') for i in range(1, 31) if hasattr(bdt, f'BL_In{i}_Cu')})
BAD = ("clearance", "shorting_items", "tracks_crossing", "track_width", "hole_clearance", "items_not_allowed",
       "copper_edge_clearance", "hole_to_hole", "via_diameter", "drill_out_of_range", "annular_width")


class R:
    def __init__(self, n, flip_y=True):
        self.n = n
        self.sock = n if str(n).startswith("ipc://") else pns.socket_of(n)
        self.fy = -1 if flip_y else 1
        self.c = KiCadClient(self.sock, f"rt{os.getpid()}", "", 600000)
        self.doc = board_doc(self.c)
        self.refresh()

    def refresh(self):
        v = pns.run_drc(self.c, self.doc, refill=False)
        self.v = v
        self.unc = collections.Counter(x.item_descriptions[0].split('[')[1].split(']')[0] if '[' in x.item_descriptions[0] else '?'
                                       for x in v if x.type == 'unconnected_items')
        self.bad = {self.sig(x) for x in v if x.type in BAD and 'Zone' not in ' '.join(x.item_descriptions)}
        return self

    @staticmethod
    def sig(x):
        return (x.type, round(x.position.x_nm / 1e5), round(x.position.y_nm / 1e5), tuple(sorted(x.item_descriptions)))

    def go(self, net, pts, w=0.254, keep=False, mode='shove', vd=0.7, vdr=0.3, finish=True, quiet=False):
        before = snapshot(self.c, self.doc)
        u0 = self.unc.get(net, 0); b0 = self.bad
        start = (pts[0][0], self.fy * pts[0][1]); lay0 = L[pts[0][2]]
        rest = [(p[0], self.fy * p[1]) for p in pts[1:]]; lays = [L[p[2]] for p in pts[1:]]
        try:
            r = pns.route_track(self.c, self.doc, start, rest, layer=lay0, mode=mode, width=w, finish=finish,
                                corner='mitered45', point_layers=lays, via_diameter=vd, via_drill=vdr)
        except Exception as e:
            rollback(self.c, self.doc, before); print(net, 'ERROR', e); return False
        self.refresh()
        new = self.bad - b0
        ok = r.success and not new and (self.unc.get(net, 0) < u0 or keep)
        if not ok:
            if not quiet:
                print(net, 'REJECT', r.success, r.message, 'end', round(r.end.x_nm / 1e6, 3), round(self.fy * r.end.y_nm / 1e6, 3),
                      'open', u0, '->', self.unc.get(net, 0))
                for s in sorted(new)[:6]:
                    print('   new', s[0], s[1] / 10, self.fy * s[2] / 10, ' | '.join(s[3]))
            rollback(self.c, self.doc, before); self.refresh()
            return False
        if not quiet:
            print(net, 'OK open', u0, '->', self.unc.get(net, 0), '| total open', sum(self.unc.values()))
        return True

    def open(self, net=None):
        if net:
            return [(round(x.position.x_nm / 1e6, 2), round(self.fy * x.position.y_nm / 1e6, 2), ' | '.join(x.item_descriptions))
                    for x in self.v if x.type == 'unconnected_items' and f'[{net}]' in x.item_descriptions[0]]
        return dict(self.unc)

    def viol(self):
        return sorted(self.bad)

    def save(self, path):
        subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'save.py'),
                        self.sock, path], check=True)


def items_of(R, nets, kinds=('track', 'via')):
    from nk_base import ec, bt, en
    out = []
    for kind, cls in ((en.KOT_PCB_TRACE, bdt.Track), (en.KOT_PCB_VIA, bdt.Via), (en.KOT_PCB_ARC, bdt.Arc)):
        r = R.c.send(ec.GetItems(header=bt.ItemHeader(document=R.doc), types=[kind]), ec.GetItemsResponse)
        for a in r.items:
            o = cls()
            if a.Unpack(o) and o.net.name in nets:
                out.append(o)
    return out


def delete_where(R, nets, pred):
    """delete tracks/vias of nets for which pred(kind, (x1,y1,x2,y2) in R's coordinates, layer) is True"""
    from nk_base import delete
    ids = []
    for o in items_of(R, nets):
        if hasattr(o, 'start'):
            f = R.fy; g = (o.start.x_nm / 1e6, f * o.start.y_nm / 1e6, o.end.x_nm / 1e6, f * o.end.y_nm / 1e6); k = 'track'; L = o.layer
        else:
            g = (o.position.x_nm / 1e6, R.fy * o.position.y_nm / 1e6) * 2; k = 'via'; L = None
        if pred(k, g, L):
            ids.append(o.id)
    if ids:
        delete(R.c, R.doc, ids)
    R.refresh()
    return len(ids)


def add_track(R, net, pts, layer='F', w=0.254):
    """create straight segments directly (R's coordinates), no router; for closing short gaps exactly"""
    from nk_base import create, V, D
    netobj = None
    for o in items_of(R, [net]):
        netobj = o.net; break
    its = []
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        t = bdt.Track(); t.start.CopyFrom(V(x1, R.fy * y1)); t.end.CopyFrom(V(x2, R.fy * y2)); t.width.CopyFrom(D(w))
        t.layer = L[layer]
        if netobj is not None:
            t.net.CopyFrom(netobj)
        its.append(t)
    create(R.c, R.doc, its); R.refresh()
