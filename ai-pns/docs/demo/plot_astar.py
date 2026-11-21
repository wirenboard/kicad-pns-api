"""plot_astar.py BOARD10 OUT.png : the grid router's free-space maps (F, B) for net CTRL with its A* path"""
import sys; import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'gridrouter'))
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
import fr, lib2
fr.configure(layers=[['F', 'F.Cu'], ['B', 'B.Cu']], clearance_track_track=0.2032, clearance_track_pad=0.2286,
             clearance_edge=0.254, via_diameter=0.7, via_drill=0.3)
B = fr.Brd(sys.argv[1])
WIN = (100.5, 144.5, -127.5, -100.5)
p = lib2.task(B, 'CTRL', pad=('U1', '1'), to_pad=('R2', '1'), commit=False, win=WIN, layers='FB')
B.maps('CTRL', 0.254, WIN, res=0.05)
x0, y0, res, W, H = B.grid
ext = (x0, x0 + (W - 1) * res, y0, y0 + (H - 1) * res)
fig, axs = plt.subplots(1, 2, figsize=(10, 3.6), dpi=110)
for ax, li, L in ((axs[0], 0, 'F.Cu'), (axs[1], 1, 'B.Cu')):
    import numpy as np
    img = np.zeros(B.free[li].shape + (3,)); img[:] = (0.20, 0.20, 0.22)
    img[B.free[li] > 0] = (0.96, 0.96, 0.96); img[(B.free[li] > 0) & B.viaok] = (0.74, 0.90, 0.74)
    ax.imshow(img, origin='lower', extent=ext, interpolation='nearest')
    for a, b in zip(p, p[1:]):
        if a[2] == b[2]:
            ax.plot([a[0], b[0]], [a[1], b[1]], '-', lw=2.2, color='#d62728' if a[2] == 'F' else '#1f77b4',
                    alpha=1.0 if a[2] == L[0] else 0.35)
        else:
            ax.plot(a[0], a[1], 'o', ms=7, mfc='none', mec='orange', mew=2)
    ax.set_title(f'{L}: free cells for a 0.254 mm CTRL track (light), also a via site (green)', fontsize=8)
    ax.set_xlim(106, 132); ax.set_ylim(-126, -106); ax.tick_params(labelsize=7)
    ax.set_xlabel('x, mm', fontsize=7); ax.set_ylabel('y, mm (y up)', fontsize=7)
fig.tight_layout(); fig.savefig(sys.argv[2])
