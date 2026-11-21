"""stats.py : segments / vias / length per routed net + copper DRC of the open board ($DEMO_N)"""
import sys, math, collections; from common import connect, pns
from nk_base import bdt
c, d = connect()
items = pns.copper_items(c, d)
NETS = sys.argv[1].split(',')
for n in NETS:
    segs = [o for o in items.values() if isinstance(o, bdt.Track) and o.net.name == n]
    vias = [o for o in items.values() if isinstance(o, bdt.Via) and o.net.name == n]
    L = sum(math.hypot(o.end.x_nm - o.start.x_nm, o.end.y_nm - o.start.y_nm) for o in segs) / 1e6
    short = sum(1 for o in segs if math.hypot(o.end.x_nm - o.start.x_nm, o.end.y_nm - o.start.y_nm) < 0.1e6)
    print(f'{n:5s} segments {len(segs):2d} (<0.1 mm: {short}) vias {len(vias)} length {L:6.2f} mm')
v = pns.run_drc(c, d, refill=True)
print('DRC', dict(collections.Counter(x.type for x in v if x.type not in ('silk_edge_clearance',))))
