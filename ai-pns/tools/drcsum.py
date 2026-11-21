#!/usr/bin/env python3
"""drcsum.py N|SOCKET [--list TYPE,...] : run_drc(refill) on fork instance N (or an ipc:// socket),
print counts per type and unconnected per net."""
import os, sys, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pyapi"))
import pns
from nk_base import KiCadClient, board_doc
n = sys.argv[1]
c = KiCadClient(n if n.startswith("ipc://") else pns.socket_of(n), f"drcsum{os.getpid()}", "", 600000)
doc = board_doc(c)
v = pns.run_drc(c, doc, refill=True)
print(dict(collections.Counter(x.type for x in v)))
un = collections.Counter(x.item_descriptions[0].split('[')[1].split(']')[0] if '[' in x.item_descriptions[0] else '?'
                         for x in v if x.type == 'unconnected_items')
print('unconnected', sum(un.values()), dict(un))
if '--list' in sys.argv:
    ts = sys.argv[sys.argv.index('--list') + 1].split(',')
    for x in v:
        if x.type in ts:
            print(x.type, round(x.position.x_nm / 1e6, 3), round(x.position.y_nm / 1e6, 3), '|', ' | '.join(x.item_descriptions))
