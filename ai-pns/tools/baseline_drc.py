#!/usr/bin/env python3
"""baseline_drc.py SOCKET [OUT.tsv] [--refill] [--diff BASELINE.tsv] [--nets A,B]

Dump run_drc of the board open in a fork instance as TSV (type, x, y, description, items).
--diff  print only violations that are not in BASELINE.tsv (matched on type + item descriptions,
        position ignored) - i.e. what your routing added. Make the baseline from the start board
        with the same options (--refill). Item descriptions carry track lengths, so a shoved foreign track shows up
        as new even if its violation is old: read the list, don't just count it.
--nets  limit DRC to these nets (faster; the baseline should then be made with the same list)."""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pyapi"))
import pns  # noqa: E402
from nk_base import KiCadClient, board_doc  # noqa: E402

args, opts, it = [], {}, iter(sys.argv[1:])
for a in it:
    if a in ("--diff", "--nets"):
        opts[a] = next(it)
    elif a.startswith("--"):
        opts[a] = True
    else:
        args.append(a)
c = KiCadClient(args[0], "bdrc", "", 900000)
d = board_doc(c)
nets = [n for n in opts.get("--nets", "").split(",") if n]
rows = sorted({(v.type, f"{v.position.x_nm / 1e6:.3f}", f"{v.position.y_nm / 1e6:.3f}", v.description,
                " | ".join(sorted(v.item_descriptions)))
               for v in pns.run_drc(c, d, nets=nets, refill=bool(opts.get("--refill")))})
if "--diff" in opts:
    base = Counter()
    for line in open(opts["--diff"], encoding="utf-8"):
        f = line.rstrip("\n").split("\t")
        base[(f[0], f[4])] += 1
    new = []
    for r in rows:
        k = (r[0], r[4])
        if base[k] > 0:
            base[k] -= 1
        else:
            new.append(r)
    rows = new
out = open(args[1], "w", encoding="utf-8") if len(args) > 1 else sys.stdout
for r in rows:
    print("\t".join(r), file=out)
if out is not sys.stdout:
    print(f"{len(rows)} violations -> {args[1]}")
else:
    print(f"# {len(rows)} violations" + (" not in baseline" if "--diff" in opts else ""), file=sys.stderr)
