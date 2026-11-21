#!/usr/bin/env python3
"""widths.py : the width numbers of ROUTING_RECIPE.md (plain python3, no dependencies).

1. Current -> width with the IPC-2221 curve fit  I = k * dT^0.44 * A^0.725
   (I in A, dT in K, A = cross-section in mil^2; k = 0.048 outer, 0.024 inner layers).
   IPC-2221 is the conservative classic. IPC-2152 replaced it with charts that give narrower
   inner tracks (inner ~ outer in many cases); use its charts or a calculator built on them when
   you need the last 30 %.
2. Impedance -> width for a surface microstrip: Hammerstad-Jensen with thickness correction,
   and an edge-coupled pair via Zdiff = 2*Z0*(1 - 0.48*exp(-0.96*s/h)) (IPC-2141A).
   Solder mask lowers Z by ~1-3 ohm (not included). No coplanar (CPWG) model here: when the
   ground pour comes closer than ~2-3 h to the track, use a field solver or the fab's calculator.
"""
import math

MIL = 0.0254   # mm


def ipc2221_width(i_a, dt_k=10.0, copper_um=35.0, inner=False):
    k = 0.024 if inner else 0.048
    area_mil2 = (i_a / (k * dt_k ** 0.44)) ** (1 / 0.725)
    return area_mil2 / (copper_um / 1000 / MIL) * MIL      # mm


def microstrip_z0(w, h, t, er):
    u = w / h; T = t / h
    du1 = T / math.pi * math.log(1 + 4 * math.e / (T * (1 / math.tanh(math.sqrt(6.517 * u))) ** 2))
    dur = 0.5 * (1 + 1 / math.cosh(math.sqrt(er - 1))) * du1
    u1, ur = u + du1, u + dur

    def z01(x):
        f = 6 + (2 * math.pi - 6) * math.exp(-(30.666 / x) ** 0.7528)
        return 60 * math.log(f / x + math.sqrt(1 + 4 / x ** 2))

    def eeff(x):
        a = 1 + math.log((x ** 4 + (x / 52) ** 2) / (x ** 4 + 0.432)) / 49 + math.log(1 + (x / 18.1) ** 3) / 18.7
        b = 0.564 * ((er - 0.9) / (er + 3)) ** 0.053
        return (er + 1) / 2 + (er - 1) / 2 * (1 + 10 / x) ** (-a * b)

    e = eeff(ur) * (z01(u1) / z01(ur)) ** 2
    return z01(u1) / math.sqrt(e), e


def zdiff(w, s, h, t, er):
    z, _ = microstrip_z0(w, h, t, er)
    return 2 * z * (1 - 0.48 * math.exp(-0.96 * s / h))


if __name__ == '__main__':
    print('IPC-2221, dT = 10 K: minimum width in mm')
    print('  current | outer 1 oz (35 um) | inner 1 oz (35 um) | inner 0.5 oz (17.5 um)')
    for i in (0.5, 1.0, 2.0, 3.0):
        print(f'  {i:4.1f} A  | {ipc2221_width(i):18.2f} | {ipc2221_width(i, inner=True):18.2f} | '
              f'{ipc2221_width(i, copper_um=17.5, inner=True):18.2f}')
    # outer layer of a 6-layer 1.6 mm stack-up: F.Cu over a 3313 prepreg to the In1 GND plane
    h, t, er = 0.0994, 0.035, 4.1
    print(f'\nSurface microstrip, h = {h} mm, t = {t} mm, er = {er}')
    for w in (0.10, 0.12, 0.15, 0.17, 0.18, 0.20, 0.254):
        z, e = microstrip_z0(w, h, t, er)
        print(f'  w = {w:.3f}  Z0 = {z:5.1f} ohm  eeff = {e:.2f}')
    print('Edge-coupled pair (w, s) -> Zdiff')
    for w in (0.12, 0.15, 0.18, 0.2032):
        for s in (0.10, 0.127, 0.15, 0.2032, 0.254):
            print(f'  w = {w:.3f} s = {s:.4f}  Zdiff = {zdiff(w, s, h, t, er):5.1f} ohm')
