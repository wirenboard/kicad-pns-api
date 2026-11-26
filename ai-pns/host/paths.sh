# paths.sh : common locations for the ai-pns host scripts (sourced, not run).
# Every value can be overridden from the environment.
#   KPNS_SRC      KiCad source tree (this repository)              default: two levels above this file
#   KPNS_BUILD    CMake build dir with build/pcbnew/pcbnew          default: $KPNS_SRC/build (package root in a release package)
#   KPNS_DEPS     .deb packages unpacked here (toolchain + libs)    default: $KPNS_SRC/../kpns-deps
#   KPNS_DEBS     downloaded .deb files                             default: $KPNS_SRC/../kpns-debs
#   KPNS_HOSTLIB  the few libraries the host lacks (make_hostlib.sh) default: $KPNS_STATE/hostlib
#   KPNS_STATE    per-instance work dirs, configs, logs             default: ${XDG_STATE_HOME:-$HOME/.local/state}/kicad-pns
#   KPNS_PY       python with protobuf 5.29 + pynng                 default: python3
#   KPNS_SOCK_PREFIX  short dir prefix for API sockets (<108 chars) default: /tmp/kpns  (instance N -> /tmp/kpnsN)
H_=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
: "${KPNS_SRC:=$(cd "$H_/../.." && pwd)}"
# in an unpacked release package ai-pns/ sits next to pcbnew/, so the package root is the "build"
[ -z "${KPNS_BUILD:-}" ] && [ -x "$KPNS_SRC/pcbnew/pcbnew" ] && KPNS_BUILD=$KPNS_SRC
: "${KPNS_BUILD:=$KPNS_SRC/build}"
: "${KPNS_DEPS:=$(cd "$KPNS_SRC/.." && pwd)/kpns-deps}"
: "${KPNS_DEBS:=$(cd "$KPNS_SRC/.." && pwd)/kpns-debs}"
: "${KPNS_STATE:=${XDG_STATE_HOME:-$HOME/.local/state}/kicad-pns}"
: "${KPNS_HOSTLIB:=$KPNS_STATE/hostlib}"
: "${KPNS_PY:=python3}"
: "${KPNS_SOCK_PREFIX:=/tmp/kpns}"
KPNS_PYAPI=$(cd "$H_/../pyapi" && pwd)
export KPNS_SRC KPNS_BUILD KPNS_DEPS KPNS_DEBS KPNS_STATE KPNS_HOSTLIB KPNS_PY KPNS_SOCK_PREFIX KPNS_PYAPI

# kpns_config DIR : make a private KiCad config dir with the IPC API server enabled (once). The first-run
# prompts are marked as answered and empty global library tables are created, so that the setup
# wizard does not appear.
kpns_config() {
  local C=$1 t
  [ -f "$C/10.99/kicad_common.json" ] && return 0
  mkdir -p "$C/10.99"
  printf '{\n  "api": { "enable_server": true },\n  "do_not_show_again": { "update_check_prompt": true, "data_collection_prompt": true }\n}\n' \
    > "$C/10.99/kicad_common.json"
  for t in fp_lib_table sym_lib_table design_block_lib_table; do
    [ -f "$C/10.99/${t//_/-}" ] || printf '(%s\n\t(version 7)\n)\n' "$t" > "$C/10.99/${t//_/-}"
  done
}

# kpns_ready SOCKET NAME : exit 0 when the API on SOCKET answers with an open board
kpns_ready() {
  timeout 30 "$KPNS_PY" -c "
import sys; sys.path.insert(0, '$KPNS_PYAPI')
from pns import *
c = KiCadClient('$1', '$2', '', 20000); doc = board_doc(c); print('READY')" 2>/dev/null | grep -q READY
}
