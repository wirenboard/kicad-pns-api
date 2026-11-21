// astar.c : multi-layer grid A* with 8 directions, direction-aware turn cost, via cost (used by fr.py).
// build: cc -O2 -shared -fPIC -o libastar.so astar.c -lm
// grid: free[l*H*W + y*W + x] (1 = centreline allowed), viaok[y*W+x], target[l*H*W+y*W+x]
// state = ((l*H + y)*W + x)*8 + d
#include <stdlib.h>
#include <string.h>
#include <math.h>
typedef struct { float f; int s; } HN;
static HN *heap; static int hn, hcap;
static void hpush(float f, int s) {
  if (hn >= hcap) { hcap = hcap ? hcap * 2 : 1 << 20; heap = realloc(heap, hcap * sizeof(HN)); }
  int i = hn++; while (i > 0) { int p = (i - 1) / 2; if (heap[p].f <= f) break; heap[i] = heap[p]; i = p; }
  heap[i].f = f; heap[i].s = s;
}
static HN hpop(void) {
  HN r = heap[0]; HN last = heap[--hn]; int i = 0;
  for (;;) { int c = 2 * i + 1; if (c >= hn) break; if (c + 1 < hn && heap[c + 1].f < heap[c].f) c++;
    if (heap[c].f >= last.f) break; heap[i] = heap[c]; i = c; }
  heap[i] = last; return r;
}
static const int DX[8] = {1, 1, 0, -1, -1, -1, 0, 1};
static const int DY[8] = {0, 1, 1, 1, 0, -1, -1, -1};
// layercost[l] multiplies step cost on layer l (prefer some layers)
int astar(int L, int H, int W, const unsigned char *freem, const unsigned char *viaok, const unsigned char *target,
          int ns, const int *starts /* l,y,x triples */, float viacost, float turn45, float turn90,
          const float *layercost, int tx, int ty /* heuristic target */, int maxexp, int *out, int outmax) {
  long N = (long)L * H * W * 8;
  float *g = malloc(N * sizeof(float)); int *par = malloc(N * sizeof(int));
  for (long i = 0; i < N; i++) g[i] = 1e30f;
  hn = 0;
  for (int k = 0; k < ns; k++) {
    int l = starts[3 * k], y = starts[3 * k + 1], x = starts[3 * k + 2];
    for (int d = 0; d < 8; d++) { int s = ((l * H + y) * W + x) * 8 + d; g[s] = 0; par[s] = -1; hpush(0, s); }
  }
  int found = -1, nexp = 0;
  while (hn > 0) {
    HN h = hpop(); int s = h.s; int d = s & 7; int c = s >> 3; int x = c % W; int y = (c / W) % H; int l = c / (W * H);
    float gs = g[s];
    float hh = 0.f; { float ddx = fabsf((float)(x - tx)), ddy = fabsf((float)(y - ty)); hh = (ddx > ddy ? ddx - ddy + 1.41421f * ddy : ddy - ddx + 1.41421f * ddx); }
    if (h.f > gs + hh + 1e-3f) continue;
    if (target[c]) { found = s; break; }
    if (++nexp > maxexp) break;
    for (int nd = 0; nd < 8; nd++) {
      int dd = (nd - d + 8) % 8; if (dd > 4) dd = 8 - dd;
      if (dd >= 3) continue;   // no turns sharper than 90
      int nx = x + DX[nd], ny = y + DY[nd]; if (nx < 0 || ny < 0 || nx >= W || ny >= H) continue;
      int nc = (l * H + ny) * W + nx; if (!freem[nc]) continue;
      if (nd & 1) { // diagonal: also require the two orthogonal neighbours free (no corner cutting)
        if (!freem[(l * H + y) * W + nx] || !freem[(l * H + ny) * W + x]) continue; }
      float step = ((nd & 1) ? 1.41421f : 1.f) * layercost[l];
      float tc = dd == 0 ? 0 : (dd == 1 ? turn45 : turn90);
      int ns2 = nc * 8 + nd; float ng = gs + step + tc;
      if (ng < g[ns2]) { g[ns2] = ng; par[ns2] = s;
        float ddx = fabsf((float)(nx - tx)), ddy = fabsf((float)(ny - ty));
        hpush(ng + (ddx > ddy ? ddx - ddy + 1.41421f * ddy : ddy - ddx + 1.41421f * ddx), ns2); }
    }
    if (viaok[y * W + x]) {
      for (int nl = 0; nl < L; nl++) { if (nl == l) continue; int nc = (nl * H + y) * W + x; if (!freem[nc]) continue;
        int ns2 = nc * 8 + d; float ng = gs + viacost;
        if (ng < g[ns2]) { g[ns2] = ng; par[ns2] = s; hpush(ng + hh, ns2); } }
    }
  }
  int n = 0;
  if (found >= 0) { int s = found; while (s >= 0 && n < outmax) { out[n++] = s >> 3; s = par[s]; } }
  free(g); free(par);
  return found >= 0 ? n : -nexp;
}

int astar2(int L, int H, int W, const float *cost, const float *vcost, const unsigned char *target,
          int ns, const int *starts, float turn45, float turn90,
          int tx, int ty, int maxexp, int *out, int outmax) {
  long N = (long)L * H * W * 8;
  float *g = malloc(N * sizeof(float)); int *par = malloc(N * sizeof(int));
  for (long i = 0; i < N; i++) g[i] = 1e30f;
  hn = 0;
  for (int k = 0; k < ns; k++) {
    int l = starts[3 * k], y = starts[3 * k + 1], x = starts[3 * k + 2];
    for (int d = 0; d < 8; d++) { int s = ((l * H + y) * W + x) * 8 + d; g[s] = 0; par[s] = -1; hpush(0, s); }
  }
  int found = -1, nexp = 0;
  while (hn > 0) {
    HN h = hpop(); int s = h.s; int d = s & 7; int c = s >> 3; int x = c % W; int y = (c / W) % H; int l = c / (W * H);
    float gs = g[s];
    float ddx0 = fabsf((float)(x - tx)), ddy0 = fabsf((float)(y - ty));
    float hh = (ddx0 > ddy0 ? ddx0 - ddy0 + 1.41421f * ddy0 : ddy0 - ddx0 + 1.41421f * ddx0);
    if (h.f > gs + hh + 1e-3f) continue;
    if (target[c]) { found = s; break; }
    if (++nexp > maxexp) break;
    for (int nd = 0; nd < 8; nd++) {
      int dd = (nd - d + 8) % 8; if (dd > 4) dd = 8 - dd;
      if (dd >= 3) continue;
      int nx = x + DX[nd], ny = y + DY[nd]; if (nx < 0 || ny < 0 || nx >= W || ny >= H) continue;
      int nc = (l * H + ny) * W + nx; float cc = cost[nc]; if (cc >= 1e8f) continue;
      if (nd & 1) { if (cost[(l * H + y) * W + nx] >= 1e8f || cost[(l * H + ny) * W + x] >= 1e8f) continue; }
      float step = ((nd & 1) ? 1.41421f : 1.f) * cc;
      float tc = dd == 0 ? 0 : (dd == 1 ? turn45 : turn90);
      int ns2 = nc * 8 + nd; float ng = gs + step + tc;
      if (ng < g[ns2]) { g[ns2] = ng; par[ns2] = s;
        float ddx = fabsf((float)(nx - tx)), ddy = fabsf((float)(ny - ty));
        hpush(ng + (ddx > ddy ? ddx - ddy + 1.41421f * ddy : ddy - ddx + 1.41421f * ddx), ns2); }
    }
    float vc = vcost[y * W + x];
    if (vc < 1e8f) {
      for (int nl = 0; nl < L; nl++) { if (nl == l) continue; int nc = (nl * H + y) * W + x; if (cost[nc] >= 1e8f) continue;
        int ns2 = nc * 8 + d; float ng = gs + vc;
        if (ng < g[ns2]) { g[ns2] = ng; par[ns2] = s; hpush(ng + hh, ns2); } }
    }
  }
  int n = 0;
  if (found >= 0) { int s = found; while (s >= 0 && n < outmax) { out[n++] = s >> 3; s = par[s]; } }
  free(g); free(par);
  return found >= 0 ? n : -nexp;
}
