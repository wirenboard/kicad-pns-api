#!/bin/bash
# test-clean.sh IMAGE TARBALL : unpack the package in a fresh container of IMAGE (debian:13,
# ubuntu:24.04, ...) that has only the documented runtime packages, and run its smoke test there.
# Proves the package is relocatable and bundles everything beyond those packages.
set -euo pipefail
IMG=$1; T=$(cd "$(dirname "$2")" && pwd)/$(basename "$2")
RUNTIME="libgtk-3-0t64 libsecret-1-0 libgl1 libegl1 libopengl0 libglx-mesa0 libgl1-mesa-dri"
docker run --rm -v "$T:/pkg.tar.xz:ro" "$IMG" bash -c "
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends $RUNTIME xvfb xz-utils python3-venv ca-certificates > /dev/null
mkdir -p /opt/k && tar -xJf /pkg.tar.xz -C /opt/k && R=\$(ls -d /opt/k/*)
python3 -m venv /opt/venv && /opt/venv/bin/pip install -q -r \$R/ai-pns/requirements.txt
. /etc/os-release && echo \"== \$PRETTY_NAME, glibc \$(ldd --version | head -1 | awk '{print \$NF}')\"
bad=\$(find \$R -type f \( -name '*.so*' -o -name '*.kiface' -o -path '*/pcbnew/pcbnew' \) -exec ldd {} + 2>&1 | grep -E 'not found|version .* not found' | sort -u || true)
[ -z \"\$bad\" ] || { echo \"missing libraries:\"; echo \"\$bad\"; exit 1; }
echo 'all ELF files resolve their libraries'
KPNS_PY=/opt/venv/bin/python \$R/ai-pns/ci/smoke.sh \$R
"
