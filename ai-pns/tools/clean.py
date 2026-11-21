#!/usr/bin/env python3
"""clean.py [SOCKET] : repeated CleanupTracks on the whole board of a fork instance (merge collinear
segments, delete dangling tracks/vias and redundant vias) until nothing changes, then print the
unconnected / copper-violation counts. Note: cleans ALL nets; pass nets to pns.cleanup_tracks
yourself if other agents own parts of the board."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import drive
from pns import cleanup_tracks

c, doc = drive.connect(sys.argv[1] if len(sys.argv) > 1 else None)
for k in range(3):
    ch = cleanup_tracks(c, doc, merge=True, dangling=True, dangling_vias=True, redundant_vias=True)
    print('cleanup', len(ch))
    if not ch:
        break
unc, cop = drive.state(); print('after cleanup unconnected', sum(unc.values()), 'copper', len(cop))
