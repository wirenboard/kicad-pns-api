#!/usr/bin/env python3
"""save.py SOCKET PATH : checkpoint the board open in a fork pcbnew instance to PATH (10.99 format).

Uses the API's SaveDocumentToString (the instance's own board.kicad_pcb is not touched), writes
PATH atomically. Reload a checkpoint with host/hoststart_n.sh N PATH PROJECT.kicad_pro --force."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pyapi"))
from nk_base import board_doc  # noqa: E402
from kipy.client import KiCadClient  # noqa: E402
from kipy.proto.common.commands import editor_commands_pb2 as edc  # noqa: E402

if len(sys.argv) != 3:
    sys.exit(__doc__)
sock, path = sys.argv[1], sys.argv[2]
c = KiCadClient(sock, f"save{os.getpid()}", "", 120000)
doc = board_doc(c)
cmd = edc.SaveDocumentToString()
cmd.document.CopyFrom(doc)
txt = c.send(cmd, edc.SavedDocumentResponse).contents
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    f.write(txt)
os.replace(tmp, path)
print(f"saved {path} ({len(txt)} bytes)")
