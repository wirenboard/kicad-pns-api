"""k10.py BASE10.kicad_pcb FORK.kicad_pcb OUT.kicad_pcb : stock-10.0 board = BASE10 with its top-level
segment/arc/via blocks replaced by those of the fork (10.99) board (same block syntax). Use it to get
the fork's routing into a file stock KiCad 10.0 / kicad-cli can open (BASE10 = same board saved by 10.0)."""
import sys, re
def blocks(t):
    out = []; i = 0
    for m in re.finditer(r'^\t\((segment|arc|via)\n', t, re.M):
        s = m.start(); e = t.index('\n\t)\n', s) + 4; out.append((s, e))
    return out
base = open(sys.argv[1]).read(); fork = open(sys.argv[2]).read()
fb = ''.join(fork[s:e] for s, e in blocks(fork))
bb = blocks(base)
if bb:
    s0 = bb[0][0]; rest = base[:s0]; tail = base[s0:]
    for s, e in reversed(bb):
        base = base[:s] + base[e:]
    s0 = bb[0][0]
else:
    s0 = base.index('\n\t(zone') + 1
out = base[:s0] + fb + base[s0:]
open(sys.argv[3], 'w').write(out)
print('k10:', len(blocks(fork)), 'track/via blocks ->', sys.argv[3])
