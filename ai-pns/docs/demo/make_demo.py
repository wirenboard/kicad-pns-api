"""make_demo.py OUT.kicad_pcb : build the small synthetic 2-layer demo board of the docs
(python3 with stock KiCad 10 pcbnew; footprints from the standard KiCad library, $KICAD_FP or
/usr/share/kicad/footprints). Nets: SIG1..8 (U1 -> J1), USB_D+/- (J2 -> U1), CTRL, GND, LED1..3."""
import pcbnew as K, sys, os
FP = os.environ.get('KICAD_FP', '/usr/share/kicad/footprints') + '/'
b = K.BOARD()
def mm(v): return K.FromMM(v)
def P(x, y): return K.VECTOR2I(mm(x), mm(y))
X0, Y0, X1, Y1 = 100, 100, 145, 128
for a, c in (((X0, Y0), (X1, Y0)), ((X1, Y0), (X1, Y1)), ((X1, Y1), (X0, Y1)), ((X0, Y1), (X0, Y0))):
    s = K.PCB_SHAPE(b); s.SetShape(K.SHAPE_T_SEGMENT); s.SetStart(P(*a)); s.SetEnd(P(*c)); s.SetLayer(K.Edge_Cuts); s.SetWidth(mm(0.1)); b.Add(s)
nets = {}
def net(n):
    if n not in nets:
        ni = K.NETINFO_ITEM(b, n); b.Add(ni); nets[n] = ni
    return nets[n]
def place(lib, name, ref, x, y, rot=0, padnets=None, back=False):
    f = K.FootprintLoad(FP + lib + '.pretty', name)
    f.SetReference(ref); f.SetPosition(P(x, y)); f.SetOrientationDegrees(rot)
    f.Value().SetVisible(False)
    for g in list(f.GraphicalItems()):
        if g.GetLayer() in (K.F_Fab, K.B_Fab, K.Cmts_User, K.Dwgs_User) and g.GetClass() == 'PCB_TEXT': g.SetVisible(False)
    b.Add(f)
    if back: f.Flip(f.GetPosition(), K.FLIP_DIRECTION_TOP_BOTTOM)
    for p in f.Pads():
        n = (padnets or {}).get(p.GetNumber())
        if n: p.SetNet(net(n))
    return f
# U1: SOIC-16; right column (9..16) = bus to J1, left column = USB pair + CTRL + GND
u1 = {'1': 'CTRL', '2': 'USB_D-', '3': 'USB_D+', '8': 'GND'}
for k in range(8): u1[str(16 - k)] = f'SIG{k + 1}'
place('Package_SO', 'SOIC-16_3.9x9.9mm_P1.27mm', 'U1', 117, 114, 0, u1)
place('Connector_PinHeader_2.54mm', 'PinHeader_1x08_P2.54mm_Vertical', 'J1', 140, 105.1, 0, {str(k + 1): f'SIG{k + 1}' for k in range(8)})
place('Connector_USB', 'USB_Micro-B_Molex_47346-0001', 'J2', 102.6, 114, -90, {'2': 'USB_D-', '3': 'USB_D+', '5': 'GND', '6': 'GND'})
place('Resistor_SMD', 'R_0603_1608Metric', 'R1', 128, 108, 90, {'1': 'LED1', '2': 'SIG2'})
place('Resistor_SMD', 'R_0603_1608Metric', 'R2', 129, 124, 0, {'1': 'CTRL', '2': 'LED2'})
place('Resistor_SMD', 'R_0603_1608Metric', 'R3', 124, 120, 90, {'1': 'LED3', '2': 'GND'})
place('Capacitor_SMD', 'C_0603_1608Metric', 'C1', 112, 121.5, 0, {'1': 'GND', '2': 'CTRL'})
b.SetCopperLayerCount(2)
z = K.ZONE(b); z.SetLayer(K.B_Cu); z.SetNet(net('GND')); z.SetLocalClearance(mm(0.3)); z.SetMinThickness(mm(0.254))
o = z.Outline(); o.NewOutline()
for x, y in ((X0 + 0.3, Y0 + 0.3), (X1 - 0.3, Y0 + 0.3), (X1 - 0.3, Y1 - 0.3), (X0 + 0.3, Y1 - 0.3)): o.Append(mm(x), mm(y))
z.SetPadConnection(K.ZONE_CONNECTION_THERMAL); b.Add(z)
b.Save(sys.argv[1])
