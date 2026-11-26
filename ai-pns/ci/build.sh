#!/bin/bash
# build.sh : configure and build the fork with ccache, inside the ai-pns/ci/Dockerfile image.
#   KPNS_SRC    source tree (default: two levels above this file)
#   KPNS_BUILD  build dir   (default: $KPNS_SRC/build)
#   JOBS        ninja parallelism (default: nproc)
#   CCACHE_DIR  compiler cache (default: $KPNS_SRC/.ccache)
#   KPNS_TARGETS  ninja targets (default: what the package needs; "all" builds every KiCad program)
# `ninja pcbnew` alone does not produce resources/images.tar.gz and schemas/ (pcbnew then stops at
# start-up on an error dialog), so the default list adds those and the 3D model plugins.
set -euo pipefail
H=$(cd "$(dirname "$0")" && pwd)
: "${KPNS_SRC:=$(cd "$H/../.." && pwd)}"
: "${KPNS_BUILD:=$KPNS_SRC/build}"
: "${JOBS:=$(nproc)}"
export CCACHE_DIR=${CCACHE_DIR:-$KPNS_SRC/.ccache}
export CCACHE_BASEDIR=$KPNS_SRC CCACHE_NOHASHDIR=1 CCACHE_COMPRESS=1
export CCACHE_MAXSIZE=${CCACHE_MAXSIZE:-4G}
mkdir -p "$CCACHE_DIR"
ccache -z >/dev/null

if [ ! -f "$KPNS_BUILD/build.ninja" ]; then
  # PCH off: ccache cannot reuse results of translation units that include a precompiled header
  cmake -G Ninja -S "$KPNS_SRC" -B "$KPNS_BUILD" -DCMAKE_BUILD_TYPE=Release \
    -DKICAD_BUILD_QA_TESTS=OFF -DKICAD_BUILD_I18N=OFF -DKICAD_SPICE_QA=OFF -DKICAD_USE_SENTRY=OFF \
    -DKICAD_SCRIPTING_WXPYTHON=OFF -DKICAD_UPDATE_CHECK=OFF -DKICAD_USE_PCH=OFF -DUSE_CCACHE=ON \
    ${KPNS_CMAKE_ARGS:-}
fi
: "${KPNS_TARGETS:=pcbnew pcbnew_kiface bitmap_archive_build schema_build_copy api_schema_build_copy remote_provider_schema_build_copy s3d_plugin_idf s3d_plugin_oce s3d_plugin_vrml}"
start=$(date +%s)
# shellcheck disable=SC2086
ninja -C "$KPNS_BUILD" -j"$JOBS" $KPNS_TARGETS
echo "ninja took $(( $(date +%s) - start )) s with -j$JOBS"
ccache -s
