# env.sh : build environment with the toolchain and libraries unpacked from .deb files into
# $KPNS_DEPS (nothing installed system-wide; see add_pkg.sh). Source it before configure.sh / ninja.
# Do not use this LD_LIBRARY_PATH to *run* pcbnew on a host with its own GTK (image loaders crash);
# the host scripts use $KPNS_HOSTLIB instead.
source "$(dirname "${BASH_SOURCE[0]}")/paths.sh"
D=$KPNS_DEPS
export PATH=$D/usr/bin:$PATH
export CPATH=$D/usr/include:$D/usr/include/x86_64-linux-gnu${CPATH:+:$CPATH}
export LIBRARY_PATH=$D/usr/lib/x86_64-linux-gnu:$D/lib/x86_64-linux-gnu:$D/usr/lib
export LD_LIBRARY_PATH=$D/usr/lib/x86_64-linux-gnu:$D/lib/x86_64-linux-gnu:$D/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
export PKG_CONFIG_PATH=$D/usr/lib/x86_64-linux-gnu/pkgconfig:$D/usr/share/pkgconfig:$D/usr/lib/pkgconfig
export PKG_CONFIG_SYSROOT_DIR=$D
export CMAKE_PREFIX_PATH=$D/usr
# short TMPDIR: the IPC API socket path must stay below 108 characters
export TMPDIR=${KPNS_TMPDIR:-${KPNS_SOCK_PREFIX}0}; mkdir -p "$TMPDIR"
