#!/bin/bash
# run_pcbnew.sh [args] : run the freshly built pcbnew from the build tree inside the build
# environment (display ${DISPLAY:-:99}). For headless agent use prefer hoststart_n.sh.
source "$(cd "$(dirname "$0")" && pwd)/env.sh"
export KICAD_RUN_FROM_BUILD_DIR=1 DISPLAY=${DISPLAY:-:99}
exec "$KPNS_BUILD/pcbnew/pcbnew" "$@"
