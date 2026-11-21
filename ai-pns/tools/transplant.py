"""transplant.py BASE.kicad_pcb TRACKS.json OUT.kicad_pcb
Stock KiCad 10.0 board = BASE (footprints, zones, rules) with its tracks/vias replaced by the ones the
PNS fork holds (dumped by drive.py --save); the fork itself saves only 10.99 files.
Run with a python that has stock KiCad's pcbnew SWIG module (e.g. /usr/bin/python3 with KiCad 10 installed).
Vias are written as through vias (F.Cu-B.Cu)."""
import sys, json
import pcbnew as K
import subprocess, os
base = sys.argv[3] + '.notracks.kicad_pcb'      # strip in a separate process (SWIG Remove() breaks later Adds)
subprocess.run([sys.executable, '-c', 'import pcbnew as K,sys;b=K.LoadBoard(sys.argv[1]);[b.Remove(t) for t in list(b.GetTracks())];K.SaveBoard(sys.argv[2],b)',
                sys.argv[1], base], check=True, stderr=subprocess.DEVNULL)
b = K.LoadBoard(base); os.remove(base)
LM = {'BL_F_Cu': K.F_Cu, 'BL_B_Cu': K.B_Cu}
LM.update({f'BL_In{i}_Cu': getattr(K, f'In{i}_Cu') for i in range(1, 31) if hasattr(K, f'In{i}_Cu')})
n = 0
for it in json.load(open(sys.argv[2])):
    m = it['msg']; net = b.FindNet(m.get('net', {}).get('name', ''))
    if it['kind'] == 'Track':
        t = K.PCB_TRACK(b)
        t.SetStart(K.VECTOR2I(int(m['start'].get('xNm', 0)), int(m['start'].get('yNm', 0))))
        t.SetEnd(K.VECTOR2I(int(m['end'].get('xNm', 0)), int(m['end'].get('yNm', 0))))
        t.SetWidth(int(m['width']['valueNm'])); t.SetLayer(LM[m['layer']])
    elif it['kind'] == 'Via':
        t = K.PCB_VIA(b)
        t.SetPosition(K.VECTOR2I(int(m['position'].get('xNm', 0)), int(m['position'].get('yNm', 0))))
        ps = m['padStack']
        t.SetDrill(int(ps['drill']['diameter']['xNm']))
        d = int(ps['copperLayers'][0]['size']['xNm'])
        try:
            t.SetWidth(d)
        except TypeError:
            t.SetWidth(K.F_Cu, d)
        t.SetLayerPair(K.F_Cu, K.B_Cu)
    else:
        continue
    if net:
        t.SetNet(net)
    b.Add(t); n += 1
K.SaveBoard(sys.argv[3], b)
print('transplant:', n, 'items ->', sys.argv[3])
