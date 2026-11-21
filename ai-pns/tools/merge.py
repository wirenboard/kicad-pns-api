#!/usr/bin/env python3
"""merge.py BASE.kicad_pcb OUT.kicad_pcb PART1.kicad_pcb:NET,NET,... [PART2.kicad_pcb:NETS ...]
          [--clearance 0.24] [--neck-clearance 0.2286] [--keep-locks] [--force-version]

Builds OUT = BASE with, for every part, all top-level segments / arcs / vias of the part's listed
nets replaced by that part's copper of those nets (text-level splice of the s-expression blocks;
everything else - footprints, zones, outline, other nets - comes from BASE unchanged).
Run with any python3 that has shapely (no KiCad needed). Parts are boards saved by the fork
(save.py, 10.99 format); BASE must have the same (version ...) header, i.e. be a fork round-trip
(open BASE in the fork and save it with save.py) - otherwise refused unless --force-version.
"(locked yes)" is stripped from all tracks/vias in OUT unless --keep-locks.

Report (stdout):
  * per part: copper of NON-listed nets that differs from BASE (the agent shoved foreign copper;
    merge discards those moves, so the part's own routes may now collide with the original copper);
  * CONFLICT lines: part copper closer than --clearance (0.24; --neck-clearance 0.2286 when both
    items touch a rule area of BASE whose name matches --relaxed-area, default '_NECK$'; see
    examples/rules.example.kicad_dru) to copper of another net
    from another part or from the copper kept from BASE (same layer; through vias on every layer).
    Pads and zones are not checked (the routing agent's DRC covered pads; zones refill after merge).
Exit code 0 = merged without conflicts, 3 = merged, conflicts reported, 2 = refused.
Zone fills in OUT are stale: load OUT in the fork and run_drc(refill=True) before judging."""
import argparse
import math
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kpcb  # noqa: E402
from shapely.geometry import LineString, Point, Polygon  # noqa: E402
from shapely.ops import nearest_points, unary_union  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402

COPPER = ("segment", "arc", "via")


def load(path):
    s = open(path, encoding="utf-8").read()
    m = re.search(r"\(version (\d+)\)", s[:200])
    return s, (m.group(1) if m else "?")


def copper_blocks(s):
    out = []
    for a, b, h in kpcb.top_blocks(s):
        if h in COPPER:
            node = kpcb.parse(s[a:b])
            out.append((a, b, h, kpcb.net_of(node), node))
    return out


def key(h, node):
    """geometry identity of a copper item (ignores uuid / lock)"""
    parts = [h]
    for f in ("start", "mid", "end", "at", "width", "size", "drill", "layer", "layers"):
        x = kpcb.field(node, f)
        if x:
            parts.append(tuple(round(float(v), 4) if re.match(r"^-?[\d.]+$", v) else v for v in x[1:] if isinstance(v, str)))
    return tuple(parts)


def all_copper_layers(s):
    """copper layers in stack order (F.Cu, In1.Cu, ..., B.Cu)"""
    a, b, _ = next(blk for blk in kpcb.top_blocks(s) if blk[2] == "layers")
    names = [x[1] for x in kpcb.parse(s[a:b])[1:] if isinstance(x, list) and len(x) > 1 and x[1].endswith(".Cu")]
    inner = sorted((x for x in names if x.startswith("In")), key=lambda x: int(x[2:-3]))
    return ["F.Cu"] + inner + ["B.Cu"]


def unlock(text):
    """strip (locked yes) from every top-level segment/arc/via block"""
    out, pos = [], 0
    for a, b, h in kpcb.top_blocks(text):
        if h in COPPER:
            out.append(text[pos:a])
            out.append(re.sub(r"\s*\(locked yes\)", "", text[a:b]))
            pos = b
    out.append(text[pos:])
    return "".join(out)


def arc_points(p0, pm, p1, n=24):
    (ax, ay), (bx, by), (cx, cy) = p0, pm, p1
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return [p0, p1]
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    t0, tm, t1 = (math.atan2(p[1] - uy, p[0] - ux) for p in (p0, pm, p1))

    def norm(t):
        return (t - t0) % (2 * math.pi)
    sweep = norm(t1)
    if norm(tm) > sweep:  # goes the other way round
        sweep -= 2 * math.pi
    return [(ux + r * math.cos(t0 + sweep * i / n), uy + r * math.sin(t0 + sweep * i / n)) for i in range(n + 1)]


def geoms(h, node, cu_layers):
    """[(layer, shapely geometry)] of one copper item"""
    pt = lambda f: (float(kpcb.field(node, f)[1]), float(kpcb.field(node, f)[2]))  # noqa: E731
    if h == "via":
        g = Point(pt("at")).buffer(float(kpcb.field(node, "size")[1]) / 2, quad_segs=8)
        ls = [x for x in kpcb.field(node, "layers")[1:] if isinstance(x, str)]
        if len(ls) == 2 and ls[0] in cu_layers and ls[1] in cu_layers:
            i, j = sorted((cu_layers.index(ls[0]), cu_layers.index(ls[1])))
            ls = cu_layers[i:j + 1] if (ls[0], ls[1]) != ("F.Cu", "B.Cu") else cu_layers
        return [(L, g) for L in ls]
    w = float(kpcb.field(node, "width")[1])
    line = LineString([pt("start"), pt("end")] if h == "segment" else arc_points(pt("start"), pt("mid"), pt("end")))
    if line.length == 0:
        line = Point(pt("start"))
    return [(kpcb.field(node, "layer")[1], line.buffer(w / 2, quad_segs=8))]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base")
    ap.add_argument("out")
    ap.add_argument("parts", nargs="+", metavar="PART.kicad_pcb:NET,NET")
    ap.add_argument("--clearance", type=float, default=0.24, help="copper-copper minimum outside the neck areas")
    ap.add_argument("--neck-clearance", type=float, default=0.2286,
                    help="minimum when both items touch a relaxed rule area of BASE (see --relaxed-area)")
    ap.add_argument("--relaxed-area", default="_NECK$",
                    help="regex for names of rule areas inside which --neck-clearance applies")
    ap.add_argument("--keep-locks", action="store_true")
    ap.add_argument("--force-version", action="store_true")
    a = ap.parse_args()

    base, bver = load(a.base)
    cu_layers = all_copper_layers(base)
    parts, owner = [], {}
    for spec in a.parts:
        path, _, nets = spec.rpartition(":")
        if not path or not nets:
            sys.exit(f"bad part spec {spec!r} (want PATH:NET,NET,...)")
        nets = [n.strip() for n in nets.split(",") if n.strip()]
        for n in nets:
            if n in owner:
                print(f"REFUSED: net {n} listed in {owner[n]} and {path}")
                sys.exit(2)
            owner[n] = path
        s, ver = load(path)
        if ver != bver and not a.force_version:
            print(f"REFUSED: {path} is version {ver}, BASE is {bver} (round-trip BASE through the fork: open + save.py)")
            sys.exit(2)
        parts.append((path, set(nets), s))

    bblocks = copper_blocks(base)
    bnets = {n for *_, n, _ in bblocks}
    bkeys = defaultdict(set)
    for _, _, h, n, node in bblocks:
        bkeys[n].add(key(h, node))

    # foreign-copper report + collect the part blocks
    new_text, items = [], []  # items: (source, net, layer, geom)
    for path, nets, s in parts:
        pblocks = copper_blocks(s)
        pkeys = defaultdict(set)
        for _, _, h, n, node in pblocks:
            pkeys[n].add(key(h, node))
        moved = {n: (len(pkeys[n] - bkeys[n]), len(bkeys[n] - pkeys[n]))
                 for n in (set(pkeys) | set(bkeys)) - nets if pkeys[n] != bkeys[n]}
        mine = [blk for blk in pblocks if blk[3] in nets]
        unknown = {blk[3] for blk in mine} - bnets
        print(f"part {path}: {len(mine)} items on {len(nets)} nets"
              + (f"; nets new to BASE: {','.join(sorted(unknown))}" if unknown else ""))
        absent = nets - {blk[3] for blk in mine}
        if absent:
            print(f"  note: no copper in part for {','.join(sorted(absent))} (their BASE copper is removed)")
        for n, (add, rem) in sorted(moved.items()):
            print(f"  FOREIGN {n}: {add} items differ from BASE, {rem} BASE items missing -> discarded (part's routes were laid against the moved copy)")
        for a_, b_, h, n, node in mine:
            new_text.append(s[a_:b_])
            new = key(h, node) not in bkeys[n]
            items.extend((path, n, L, g, new) for L, g in geoms(h, node, cu_layers))

    # splice: drop BASE copper of all part nets, insert part copper after the last kept copper block
    drop = [(x, y) for x, y, h, n, node in bblocks if n in owner]
    kept = [(x, y, h, n, node) for x, y, h, n, node in bblocks if n not in owner]
    tops = kpcb.top_blocks(base)
    anchor = kept[-1][1] if kept else next((x for x, y, h in tops if h == "zone"), tops[-1][1])
    ins = "".join("\n\t" + t for t in new_text)
    out, pos = [], 0
    edits = sorted([(x, y, "") for x, y in drop] + [(anchor, anchor, ins)], key=lambda e: (e[0], e[1]))
    for x, y, rep in edits:
        if x < pos:
            continue
        seg = base[pos:x]
        if rep == "" and x != y:  # removing a block: also eat the indentation before it
            seg = seg.rstrip("\t ")
            if seg.endswith("\n"):
                seg = seg[:-1]
        out.append(seg)
        out.append(rep)
        pos = y
    out.append(base[pos:])
    res = "".join(out)
    if not a.keep_locks:
        res = unlock(res)
    tmp = a.out + ".tmp"
    open(tmp, "w", encoding="utf-8").write(res)
    os.replace(tmp, a.out)
    chk = copper_blocks(res)
    print(f"OUT {a.out}: {len(chk)} copper items ({len(bblocks)} in BASE, {len(drop)} replaced by {len(new_text)})")

    # clearance check: part copper vs other parts' and kept BASE copper of other nets
    for x, y, h, n, node in kept:
        items.extend(("BASE", n, L, g, False) for L, g in geoms(h, node, cu_layers))
    by_layer = defaultdict(list)
    for it in items:
        by_layer[it[2]].append(it)
    necks = []
    for x, y, h in kpcb.top_blocks(base):
        m = re.search(r'\(name "([^"]*)"\)', base[x:y]) if h == "zone" else None
        if m and re.search(a.relaxed_area, m.group(1)):
            pts = [(float(m.group(1)), float(m.group(2))) for m in re.finditer(r"\(xy (\S+) (\S+)\)", base[x:y])]
            necks.append(Polygon(pts))
    neck = unary_union(necks) if necks else None
    in_neck = {}
    conflicts = []
    reach = max(a.clearance, a.neck_clearance)
    for L, its in by_layer.items():
        tree = STRtree([it[3] for it in its])
        for i, (src, net, _, g, new) in enumerate(its):
            if src == "BASE":
                continue
            for j in tree.query(g.buffer(reach)):
                src2, net2, _, g2, new2 = its[j]
                # other net, other source, not both unchanged from BASE; part-vs-part pairs once
                if net2 == net or src2 == src or not (new or new2) or (src2 != "BASE" and j < i):
                    continue
                d = g.distance(g2)
                if d >= reach - 1e-6:
                    continue
                for gg in (g, g2):
                    if id(gg) not in in_neck:
                        in_neck[id(gg)] = bool(neck is not None and neck.intersects(gg))
                lim = a.neck_clearance if in_neck[id(g)] and in_neck[id(g2)] else a.clearance
                if d < lim - 1e-6:
                    p = g.intersection(g2).centroid if d == 0 else nearest_points(g, g2)[0]
                    conflicts.append((L, src, net, src2, net2, d, p.x, p.y, lim))
    seen = set()
    for L, s1, n1, s2, n2, d, x, y, lim in sorted(conflicts, key=lambda c: (c[5], c[0])):
        k = (L, n1, n2, round(x, 1), round(y, 1))
        if k in seen:
            continue
        seen.add(k)
        print(f"CONFLICT {L} {os.path.basename(s1)}:{n1} vs {os.path.basename(s2)}:{n2} gap {d:.4f} < {lim} at ({x:.3f},{y:.3f})")
    print(f"{len(seen)} conflicts")
    sys.exit(3 if seen else 0)


main()
