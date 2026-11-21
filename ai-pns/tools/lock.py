#!/usr/bin/env python3
"""lock.py SOCKET --nets A,B,...  |  lock.py SOCKET --unlock  |  lock.py SOCKET --status

--nets   lock every track, arc and via whose net is NOT in the list and unlock those of the listed
         nets, so push & shove can only move the routing agent's own copper (locked items are
         walked around / block the route instead of being shoved).
--unlock unlock all tracks, arcs and vias.
--status print locked/unlocked counts.
The lock flag is saved in the board ((locked yes)), so it survives save.py and a reload; merge.py
takes copper from the parts as saved, so run --unlock (or not) as you like before saving."""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pyapi"))
from nk_base import board_doc, bt, bdt, ec, en  # noqa: E402
from kipy.proto.common.commands import editor_commands_pb2 as edc  # noqa: E402
from kipy.client import KiCadClient  # noqa: E402
from google.protobuf import any_pb2  # noqa: E402

KINDS = ((en.KOT_PCB_TRACE, bdt.Track), (en.KOT_PCB_ARC, bdt.Arc), (en.KOT_PCB_VIA, bdt.Via))


def items(c, doc):
    out = []
    for kind, cls in KINDS:
        r = c.send(ec.GetItems(header=bt.ItemHeader(document=doc), types=[kind]), ec.GetItemsResponse)
        for a in r.items:
            o = cls()
            if a.Unpack(o):
                out.append(o)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("socket")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--nets")
    g.add_argument("--unlock", action="store_true")
    g.add_argument("--status", action="store_true")
    a = ap.parse_args()
    c = KiCadClient(a.socket, f"lock{os.getpid()}", "", 120000)
    doc = board_doc(c)
    its = items(c, doc)
    if a.status:
        n = sum(1 for o in its if o.locked == bt.LS_LOCKED)
        print(f"{n} locked, {len(its) - n} unlocked")
        return
    keep = set(x.strip() for x in a.nets.split(",") if x.strip()) if a.nets else set()
    if a.nets:
        missing = keep - {o.net.name for o in its}
        if missing:
            print("note: no copper yet on", ",".join(sorted(missing)))
    req = ec.UpdateItems(header=bt.ItemHeader(document=doc))
    nl = nu = 0
    for o in its:
        want = bt.LS_LOCKED if (a.nets and o.net.name not in keep) else bt.LS_UNLOCKED
        nl += want == bt.LS_LOCKED
        nu += want == bt.LS_UNLOCKED
        if o.locked != want:
            o.locked = want
            x = any_pb2.Any()
            x.Pack(o)
            req.items.append(x)
    if req.items:
        r = c.send(req, ec.UpdateItemsResponse)
        bad = [u for u in r.updated_items if u.status.code != edc.ISC_OK]
        if bad:
            print(f"{len(bad)} updates failed: {bad[0].status}")
    print(f"{len(req.items)} changed; now {nl} locked, {nu} unlocked")


main()
