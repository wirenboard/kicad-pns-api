#!/bin/bash
# cdrc.sh FORK.kicad_pcb TAG BASE10.kicad_pcb [BASE10.kicad_pro] [RULES.kicad_dru]
#   copy the fork board's copper onto a stock-10.0 BASE (k10.py), run stock kicad-cli DRC with zone
#   refill -> TAG.kicad_pcb, TAG_drc.json + a summary (unconnected per net, violations per type).
#   The .kicad_pro / .kicad_dru default to the ones next to BASE10. SAVE=1 also saves the refilled board.
set -e; H=$(cd "$(dirname "$0")" && pwd); T=$2; B=$3
[ -f "$1" ] && [ -n "$T" ] && [ -f "$B" ] || { echo "usage: $0 FORK.kicad_pcb TAG BASE10.kicad_pcb [PRO] [DRU]"; exit 2; }
P=${4:-${B%.kicad_pcb}.kicad_pro}; R=${5:-${B%.kicad_pcb}.kicad_dru}
python3 $H/k10.py "$B" "$1" $T.kicad_pcb >/dev/null; [ -f "$P" ] && cp "$P" $T.kicad_pro; [ -f "$R" ] && cp "$R" $T.kicad_dru
kicad-cli pcb drc --refill-zones ${SAVE:+--save-board} -o ${T}_drc.json --format json $T.kicad_pcb >/dev/null 2>&1 || true
python3 - ${T}_drc.json <<'PY'
import json,collections,re,sys
d=json.load(open(sys.argv[1]))
un=collections.Counter(re.search(r'\[([^\]]*)\]',v['items'][0]['description']).group(1) for v in d['unconnected_items'])
cop=[v for v in d['violations'] if v['type'] not in ('silk_over_copper','silk_overlap','silk_edge_clearance','text_height','pth_inside_courtyard','npth_inside_courtyard','courtyards_overlap','text_thickness')]
print('unconnected',len(d['unconnected_items']),dict(sorted(un.items())))
print('violations',collections.Counter(v['type'] for v in cop))
PY
