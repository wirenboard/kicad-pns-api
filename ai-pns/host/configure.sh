#!/bin/bash
# configure.sh [extra cmake args] : configure the fork with Ninja into $KPNS_BUILD using the
# toolchain from $KPNS_DEPS (source env.sh first if you build with unpacked .debs; with a
# system-installed toolchain and KiCad build deps, unset KPNS_DEPS-based flags as needed).
# Then: ninja -C "$KPNS_BUILD"   (the default target: pcbnew alone lacks resources/images.tar.gz and
# schemas/, which pcbnew needs at start-up; no install needed, see run_pcbnew.sh)
H=$(cd "$(dirname "$0")" && pwd); source "$H/env.sh"
cmake -G Ninja -S "$KPNS_SRC" -B "$KPNS_BUILD" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$KPNS_BUILD/install" \
  -DKICAD_BUILD_QA_TESTS=OFF -DKICAD_BUILD_I18N=OFF -DKICAD_SPICE_QA=OFF -DKICAD_USE_SENTRY=OFF \
  -DKICAD_SCRIPTING_WXPYTHON=OFF -DKICAD_UPDATE_CHECK=OFF \
  -DCMAKE_C_COMPILER="$KPNS_DEPS/usr/bin/gcc" -DCMAKE_CXX_COMPILER="$KPNS_DEPS/usr/bin/g++" \
  -DOCC_INCLUDE_DIR="$KPNS_DEPS/usr/include/opencascade" -DOCC_LIBRARY_DIR="$KPNS_DEPS/usr/lib/x86_64-linux-gnu" "$@"
