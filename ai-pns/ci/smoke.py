"""smoke.py SAVE_PATH : quick check of a running fork pcbnew on the StickHub demo through ai-pns/pyapi
($KPNS_SOCKET, $PYAPI). Synthetic tracks go right of the board outline (x >= 175 mm), where there is
free space."""
import os, sys, math
sys.path.insert(0, os.environ['PYAPI'])
import pns
from pns import bdt, bc, ec, V, D

c = pns.KiCadClient(os.environ['KPNS_SOCKET'], 'smoke', '', 120000)
d = pns.board_doc(c)
fails = []
def check(name, ok, info=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f'  [{info}]' if info else ''), flush=True)
    ok or fails.append(name)
def mk(net, a, b, w=.15):
    t = bdt.Track(start=V(*a), end=V(*b), width=D(w), layer=bdt.BL_F_Cu)
    t.net.name = net
    pns.create(c, d, [t])
def syn(net): return [t for t in pns.tracks_of(c, d, net) if min(t[0][0], t[1][0]) > 170]

ver = c.send(bc.GetVersion(), bc.GetVersionResponse).version.full_version
check('GetVersion', bool(ver), ver)
n = len(pns.copper_items(c, d))
check('board has copper', n > 0, f'{n} items')

for i, net in enumerate(('/LED1', '/LED2', '/LED3')):
    mk(net, (175, 90 + .35 * i), (201, 90 + .35 * i))
mk('/LED4', (176, 87.5), (178, 87.5))
old = {net: syn(net) for net in ('/LED1', '/LED2', '/LED3')}
r = pns.route_track(c, d, (178, 87.5), [(185, 89.9), (192, 89.9), (198, 87.5)], mode='shove', width=.15, finish=True)
check('RouteTrack shove', r.success and len(r.created_items) > 0, r.message)
check('route reaches the end', any(math.dist(q, (198, 87.5)) < .002 for a, b, _ in syn('/LED4') for q in (a, b)))
check('neighbours were shoved', any(syn(net) != old[net] for net in old))

mk('/LED6', (175, 114), (201, 114))
r = pns.drag_track(c, d, (188, 114), (188, 115.5))
check('DragTrack', r.success, r.message)

v = pns.run_drc(c, d, nets=['/LED1', '/LED2', '/LED3', '/LED4'])
bad = [x.type for x in v if x.type in ('clearance', 'shorting_items', 'tracks_crossing')]
check('RunDrc, no clearance errors on the routed nets', not bad, bad)

txt = c.send(ec.SaveDocumentToString(document=d), ec.SavedDocumentResponse).contents
open(sys.argv[1], 'w').write(txt)
check('SaveDocumentToString', '(kicad_pcb' in txt[:50], len(txt))

print('FAILED: ' + ', '.join(fails) if fails else 'ALL PASS')
sys.exit(1 if fails else 0)
