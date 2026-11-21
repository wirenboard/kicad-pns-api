#!/bin/bash
# add_pkg.sh PKG... : download .deb packages (plus their dependencies that are not installed on the
# system) into $KPNS_DEBS, unpack them into $KPNS_DEPS and repoint dangling .so links to system libs.
# Debian/Ubuntu with apt; no root needed. Full package list of a working build: deps_list.txt
#   xargs -a deps_list.txt ./add_pkg.sh
source "$(cd "$(dirname "$0")" && pwd)/paths.sh"
D=$KPNS_DEPS; mkdir -p "$D" "$KPNS_DEBS"
L=$(apt-get install --dry-run -y "$@" 2>/dev/null | awk '/^Inst /{print $2}')
cd "$KPNS_DEBS"; for p in $L; do ls ${p}_*.deb >/dev/null 2>&1 || apt-get download $p >/dev/null 2>&1 || echo "download failed $p"; done
for p in $L; do f=$(ls ${p}_*.deb 2>/dev/null | head -1); [ -n "$f" ] && dpkg -x "$f" "$D" && echo "unpacked $f"; done
find "$D" -xtype l | while read -r l; do bn=$(basename "$(readlink "$l")"); for dir in /usr/lib/x86_64-linux-gnu /lib/x86_64-linux-gnu /usr/lib; do [ -e "$dir/$bn" ] && { ln -sfn "$dir/$bn" "$l"; break; }; done; done
