"""drc_list.py : RunDrc (zones refilled) on instance $DEMO_N, one line per violation"""
import collections
from common import connect, pns
c, d = connect()
v = pns.run_drc(c, d, refill=True)
print('>>> pns.run_drc(c, doc, refill=True)')
for x in v:
    print(f'{x.type:22s} ({x.position.x_nm / 1e6:7.3f}, {x.position.y_nm / 1e6:7.3f})  {x.description}')
    for it in x.item_descriptions:
        print(f'{"":26s}- {it}')
print('summary:', dict(collections.Counter(x.type for x in v)))
