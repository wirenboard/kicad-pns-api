"""shove_demo.py : route SIG2 (U1.15 -> J1.2) through a corner point inside the SIG3..SIG6 bundle;
in shove mode the router pushes the bundle aside instead of failing. Run after route_core.py."""
from common import connect, pns
c, doc = connect()
import collections
SKIP = ('unconnected_items', 'silk_edge_clearance')
count = lambda: collections.Counter(x.type for x in pns.run_drc(c, doc, refill=True) if x.type not in SKIP)
before = pns.snapshot(c, doc); v0 = count()
r = pns.route_track(c, doc, (119.475, 110.825), [(127.0, 110.825), (131.0, 114.0), (136.0, 114.0), (140.0, 107.64)],
                    width=0.254, mode='shove', corner='mitered45', finish=True)
print('route', r.success, r.completed, r.message, len(r.created_items), 'created', len(r.removed_items), 'removed')
print('new violations', dict(count() - v0))
if '--undo' in __import__('sys').argv:
    print('rolled back', pns.rollback(c, doc, before))
