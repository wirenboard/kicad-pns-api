#!/bin/bash
# make_hostlib.sh : collect into $KPNS_HOSTLIB (symlinks) the only libraries a typical desktop host
# lacks to run the built pcbnew: OpenCascade (libTK*), FreeImage and libjpeg62 from $KPNS_DEPS.
# The host's own GTK/wx/etc. are used otherwise: putting all of $KPNS_DEPS on LD_LIBRARY_PATH
# crashes the host GTK image loaders. If pcbnew still fails to start, run
#   LD_LIBRARY_PATH=$KPNS_HOSTLIB ldd $KPNS_BUILD/pcbnew/pcbnew | grep 'not found'
# and link the missing ones from $KPNS_DEPS the same way.
source "$(cd "$(dirname "$0")" && pwd)/paths.sh"
L=$KPNS_DEPS/usr/lib/x86_64-linux-gnu; mkdir -p "$KPNS_HOSTLIB"
n=0
for f in "$L"/libTK*.so.* "$L"/libfreeimage*.so* "$L"/libjpeg.so.62*; do
  [ -e "$f" ] || continue; ln -sfn "$f" "$KPNS_HOSTLIB/$(basename "$f")"; n=$((n+1))
done
echo "$n links in $KPNS_HOSTLIB"
LD_LIBRARY_PATH=$KPNS_HOSTLIB ldd "$KPNS_BUILD/pcbnew/pcbnew" 2>/dev/null | grep 'not found' || echo "pcbnew: no missing libraries"
