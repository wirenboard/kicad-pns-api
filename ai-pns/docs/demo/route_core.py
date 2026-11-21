"""route_core.py : the pre-routed part of the demo - a 4-track bundle SIG3..SIG6 (U1 -> J1) and the
USB_D+/USB_D- differential pair (J2 -> U1), both with RouteTrack (shove, mitered 45, finish)."""
from common import connect, pns
c, doc = connect()
U = {16: 109.555, 15: 110.825, 14: 112.095, 13: 113.365, 12: 114.635, 11: 115.905, 10: 117.175, 9: 118.445}
J = {k + 1: 105.1 + 2.54 * k for k in range(8)}
# SIG3..SIG6: U1.14..11 -> J1.3..6; leave the pad east along its axis, then 45 degrees into the header
for k, pin in ((3, 14), (4, 13), (5, 12), (6, 11)):
    y0, y1 = U[pin], J[k]
    r = pns.route_track(c, doc, (119.475, y0), [(124.0 + 0.6 * k, y0), (140.0, y1)], width=0.254, mode='shove',
                        corner='mitered45', finish=True)
    print(f'SIG{k}', r.success, r.completed, r.message)
# differential pair: start on the D+ pad of J2, end on the D+ pad of U1; the router finds the partner
# net by name (USB_D+ / USB_D-) and keeps the gap
r = pns.route_track(c, doc, (103.76, 114.0), [(109.0, 112.7), (114.525, 112.095)], width=0.2032, gap=0.2032,
                    diff_pair=True, mode='shove', corner='mitered45', finish=True)
print('USB pair', r.success, r.completed, repr(r.message))
for x in pns.run_drc(c, doc, nets=['USB_D+', 'USB_D-'], refill=True):
    print('  ', x.type, x.description)
