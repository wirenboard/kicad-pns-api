#!/bin/bash
# package.sh OUTDIR [NAME] : pack a built tree into a relocatable tarball OUTDIR/NAME.tar.xz (+ .sha256).
#   KPNS_SRC    source tree (default: two levels above this file)
#   KPNS_BUILD  build dir after a full `ninja` (default: $KPNS_SRC/build)
#   NAME        default: kicad-pns-<git describe>-linux-x86_64
# Run it where the build's libraries are installed in /usr (the ai-pns/ci/Dockerfile image).
#
# The package keeps the layout of a KiCad build tree (pcbnew/, plugins/3d/, schemas/, resources/), so
# KiCad finds its stock data and 3D plugins the way it does when run from a build dir. Libraries that
# a desktop Linux with GTK 3 has anyway (glibc, libstdc++, GTK/GLib/Pango/Cairo, X11/Wayland, GL,
# fontconfig/freetype, WebKitGTK) are taken from the host; everything else is copied into lib/ and
# every ELF file gets a RUNPATH relative to itself.
set -euo pipefail
H=$(cd "$(dirname "$0")" && pwd)
: "${KPNS_SRC:=$(cd "$H/../.." && pwd)}"
: "${KPNS_BUILD:=$KPNS_SRC/build}"
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
VER=$(git -C "$KPNS_SRC" describe --tags --always 2>/dev/null || echo unknown)
NAME=${2:-kicad-pns-$VER-linux-x86_64}
B=$KPNS_BUILD; R=$OUT/$NAME
rm -rf "$R"; mkdir -p "$R/bin" "$R/lib" "$R/share"

# --- KiCad files, in build-tree layout
cd "$B"
cp --parents pcbnew/pcbnew pcbnew/_pcbnew.kiface "$R/"
find plugins -name '*.so' -not -path '*/CMakeFiles/*' -exec cp --parents {} "$R/" \;
for f in common/libkicommon.so.* common/gal/libkigal.so.* api/libkiapi.so.* 3d-viewer/3d_cache/sg/libkicad_3dsg.so.*; do
  cp "$f" "$R/lib/"
done
# soname links for KiCad's own libraries
(cd "$R/lib"; for f in lib*.so.*; do s=$(objdump -p "$f" | awk '/SONAME/{print $2}'); [ -n "$s" ] && [ "$s" != "$f" ] && ln -sf "$f" "$s"; done; true)
mkdir -p "$R/schemas" "$R/resources"
cp schemas/*.json "$R/schemas/"
cp resources/images.tar.gz "$R/resources/"
[ -d resources/project_template ] && cp -r resources/project_template "$R/resources/"
cp kicad_build_version.txt "$R/share/" 2>/dev/null || true

# --- third-party libraries the host may lack
# Excluded (taken from the host): base system, toolkit and graphics stacks. A bundled copy of these
# would clash with the host's GTK modules, GL drivers or glibc.
EXCLUDE='^(ld-linux.*|libc|libm|libdl|librt|libpthread|libresolv|libutil|libanl|libmvec|libstdc\+\+|libgcc_s|libz|libgtk-3|libgdk-3|libgdk_pixbuf-2\.0|libglib-2\.0|libgio-2\.0|libgobject-2\.0|libgmodule-2\.0|libgthread-2\.0|libpango.*|libcairo.*|libharfbuzz.*|libfontconfig|libfreetype|libatk.*|libatspi|libdbus-1|libepoxy|libwayland.*|libxkbcommon.*|libX11|libX11-xcb|libXext|libXrender|libXi|libXfixes|libXrandr|libXcursor|libXdamage|libXcomposite|libXinerama|libXau|libXdmcp|libxcb.*|libGL|libEGL|libOpenGL|libGLdispatch|libGLX|libdrm|libgbm|libfribidi|libpixman-1|libpng16|libexpat|libffi|libmount|libblkid|libselinux|libpcre2-8|libsystemd|libudev|libuuid|libthai|libdatrie|libgraphite2|libbrotli.*|libbz2|liblzma|libzstd|libcloudproviders|libtinysparql.*|libtracker.*|libwebkit2gtk-4\.1|libjavascriptcoregtk-4\.1|libsoup-3\.0|libgstreamer.*|libgst.*|libsecret-1|libgcrypt|libgpg-error|libcap|libasound|libtiff|libwebp|libsharpyuv|libLerc|libjbig|libdeflate)\.so'
elfs() { find "$R" -type f \( -name '*.so*' -o -name '*.kiface' -o -path "$R/pcbnew/pcbnew" \) -exec sh -c 'file -b "$1" | grep -q ELF' _ {} \; -print; }
for pass in 1 2 3; do
  new=0
  while read -r so path; do
    echo "$so" | grep -Eq "$EXCLUDE" && continue
    [ -e "$R/lib/$so" ] && continue
    cp -L "$path" "$R/lib/$so"; new=$((new+1))
  done < <(elfs | xargs -d '\n' env LD_LIBRARY_PATH="$R/lib" ldd 2>/dev/null | awk '/=> \//{print $1, $3}' | sort -u)
  [ $new -eq 0 ] && break
done
missing=$(elfs | xargs -d '\n' env LD_LIBRARY_PATH="$R/lib" ldd 2>/dev/null | grep 'not found' | sort -u || true)
[ -z "$missing" ] || { echo "unresolved libraries:"; echo "$missing"; exit 1; }

# strip, then a RUNPATH relative to each file (no LD_LIBRARY_PATH needed)
elfs | xargs -d '\n' strip --strip-unneeded
elfs | while read -r f; do
  rel=$(realpath --relative-to="$(dirname "$f")" "$R/lib")
  patchelf --set-rpath "\$ORIGIN/$rel" "$f"
done

# --- launcher, client, demo board
install -m 755 "$H/kicad-pns-pcbnew" "$R/bin/kicad-pns-pcbnew"
(cd "$KPNS_SRC" && git archive HEAD ai-pns 2>/dev/null | tar -x -C "$R") || cp -r "$KPNS_SRC/ai-pns" "$R/"
cp -r "$KPNS_SRC/demos/stickhub" "$R/share/demo-stickhub"
cp "$KPNS_SRC/LICENSE.README" "$KPNS_SRC/LICENSE.GPLv3" "$R/share/" 2>/dev/null || true
{
  echo "name: $NAME"
  echo "source: $(git -C "$KPNS_SRC" rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "kicad: $(cat "$B/kicad_build_version.txt" 2>/dev/null || echo unknown)"
  echo "built on: $(. /etc/os-release && echo "$PRETTY_NAME")"
  echo "max GLIBC: $(elfs | xargs -d '\n' objdump -T 2>/dev/null | grep -o 'GLIBC_2\.[0-9]*' | sort -uV | tail -1)"
  echo "max GLIBCXX: $(elfs | xargs -d '\n' objdump -T 2>/dev/null | grep -o 'GLIBCXX_3\.4\.[0-9]*' | sort -uV | tail -1)"
  echo "bundled libraries:"; (cd "$R/lib" && ls | sed 's/^/  /')
} > "$R/BUILDINFO"

cd "$OUT"
tar -cf - "$NAME" | xz -T0 -6 > "$NAME.tar.xz"
sha256sum "$NAME.tar.xz" > "$NAME.tar.xz.sha256"
du -sh "$R" "$NAME.tar.xz"
cat "$R/BUILDINFO" | head -6
