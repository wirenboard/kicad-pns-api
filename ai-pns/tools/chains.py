"""chains.py BOARD.kicad_pcb OUT.json : the rule-5 defects of fancheck.py (zigzag jogs, detours) as track chains.
A chain runs between two nodes on one layer (fancheck's nodes: pad centres, vias, vertices of degree != 2).
Writes JSON [{kind, net, layer, A, B, pts, segs, w, ws, ln, st, padA, padB}], mm, y up; layer letters
F, B and 1..30 for In1..In30 (the letters of tools/rt.py). padA/padB describe an SMD pad at the chain end
(long axis, half length, square or not). Used by pnsfix.py to pick targets; importable (allchains(path)).
Needs stock pcbnew."""
import sys, json, math, collections
import pcbnew as K
mm = K.ToMM
R = lambda v: round(v, 4)


def letter(b, lid):
    n = b.GetLayerName(lid)
    return 'F' if n == 'F.Cu' else 'B' if n == 'B.Cu' else n[2:-3] if n.startswith('In') else n


def load(path):
    b = K.LoadBoard(path)
    anchors = collections.defaultdict(list); vias = set()
    for f in b.GetFootprints():
        for p in f.Pads():
            q = p.GetPosition(); anchors[p.GetNetname()].append((mm(q.x), mm(q.y)))
    for t in b.GetTracks():
        if t.GetClass() == 'PCB_VIA':
            q = t.GetPosition(); anchors[t.GetNetname()].append((mm(q.x), mm(q.y))); vias.add((t.GetNetname(), R(mm(q.x)), R(mm(q.y))))
    adj = collections.defaultdict(list); segw = {}
    for t in b.GetTracks():
        if t.GetClass() != 'PCB_TRACK': continue
        s, e = t.GetStart(), t.GetEnd(); a = (R(mm(s.x)), R(mm(s.y))); c = (R(mm(e.x)), R(mm(e.y)))
        if a == c: continue
        k = (t.GetNetname(), t.GetLayer()); adj[k + a].append(c); adj[k + c].append(a)
        segw[(k, frozenset((a, c)))] = mm(t.GetWidth())
    return b, anchors, vias, adj, segw


def allchains(path):
    b, anchors, vias, adj, segw = load(path)
    def isnode(k): return len(adj[k]) != 2 or (k[0], k[2], k[3]) in vias or any(abs(k[2]-px) < 1e-3 and abs(k[3]-py) < 1e-3 for px, py in anchors[k[0]])
    out = []; seen = set()
    for key in list(adj):
        if not isnode(key): continue
        for nxt in adj[key]:
            net, L = key[0], key[1]; path = [(key[2], key[3]), nxt]; prev = (key[2], key[3]); cur = nxt
            while not isnode((net, L) + cur):
                o = [p for p in adj[(net, L) + cur] if p != prev]
                if not o: break
                prev, cur = cur, o[0]; path.append(cur)
            segs = [frozenset((path[i], path[i+1])) for i in range(len(path)-1)]
            sig = (net, L, frozenset(segs))
            if sig in seen: continue
            seen.add(sig)
            ln = sum(math.hypot(path[i+1][0]-path[i][0], path[i+1][1]-path[i][1]) for i in range(len(path)-1))
            st = math.hypot(path[-1][0]-path[0][0], path[-1][1]-path[0][1])
            ws = [segw[((net, L), s)] for s in segs]
            out.append(dict(net=net, layer=letter(b, L), pts=[(x, -y) for x, y in path], ln=ln, st=st, ws=ws, w=max(ws)))
    return out


def isjog(pts):
    """index list of zigzag segments (fancheck b) inside the chain"""
    r = []
    for i in range(1, len(pts) - 2):
        a, c = pts[i], pts[i+1]; l = math.hypot(c[0]-a[0], c[1]-a[1])
        if l >= 0.3 or l < 1e-6: continue
        u = (a[0]-pts[i-1][0], a[1]-pts[i-1][1]); v = (pts[i+2][0]-c[0], pts[i+2][1]-c[1])
        nu, nv = math.hypot(*u), math.hypot(*v)
        if nu > 1e-6 and nv > 1e-6 and abs((u[0]*v[1]-u[1]*v[0])/(nu*nv)) < 1e-3 and (u[0]*v[0]+u[1]*v[1]) > 0 \
                and abs(((c[0]-a[0])*u[1]-(c[1]-a[1])*u[0])/(nu*l)) > 1e-3:
            r.append(i)
    return r


def isdet(c): return c['st'] > 0.05 and c['ln'] > 1.5 * c['st'] and c['ln'] - c['st'] > 1.0


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] in ('-h', '--help'):
        print(__doc__); sys.exit(0 if len(sys.argv) > 1 and sys.argv[1] in ('-h', '--help') else 2)
    out = []
    b = K.LoadBoard(sys.argv[1]); PADS = []
    for f in b.GetFootprints():
        for p in f.Pads():
            if p.GetAttribute() != K.PAD_ATTRIB_SMD: continue
            q = p.GetPosition(); bb = p.GetBoundingBox(); w, h = mm(bb.GetWidth()), mm(bb.GetHeight())
            PADS.append((p.GetNetname(), mm(q.x), -mm(q.y), w, h, len(f.Pads()), f.GetReference() + '.' + p.GetNumber()))
    def padinfo(net, x, y):
        for n, px, py, w, h, np_, nm in PADS:
            if n == net and abs(px - x) < 2e-3 and abs(py - y) < 2e-3:
                return dict(ax='x' if w >= h else 'y', h=max(w, h) / 2, sq=abs(w - h) < 0.05, name=nm)
        return None
    for c in allchains(sys.argv[1]):
        kinds = (['jog'] if isjog(c['pts']) else []) + (['det'] if isdet(c) else [])
        if kinds:
            c['kind'] = kinds; c['A'] = c['pts'][0]; c['B'] = c['pts'][-1]
            c['padA'] = padinfo(c['net'], *c['A']); c['padB'] = padinfo(c['net'], *c['B'])
            c['segs'] = [list(c['pts'][i]) + list(c['pts'][i+1]) for i in range(len(c['pts'])-1)]
            out.append(c)
    json.dump(out, open(sys.argv[2], 'w'), indent=0)
    print(len(out), 'chains', collections.Counter(tuple(c['kind']) for c in out))
