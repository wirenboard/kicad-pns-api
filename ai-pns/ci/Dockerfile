# Debian 13 (trixie) image that builds, packages and smoke-tests the fork in CI (and locally).
# Unlike host/Dockerfile.trixie (which pairs with an unpacked .deb tree in $KPNS_DEPS), everything
# here is installed with apt, so the image alone is enough:
#   docker build -t kpns-ci:trixie ai-pns/ci
#   docker run --rm -u $(id -u):$(id -g) -v "$PWD:$PWD" -w "$PWD" kpns-ci:trixie ai-pns/ci/build.sh
FROM debian:13-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN echo 'Acquire::Retries "10";' > /etc/apt/apt.conf.d/80retries && apt-get update \
 && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build ccache pkgconf gettext swig protobuf-compiler \
    glslang-tools spirv-tools python3 python3-dev python3-venv git ca-certificates file patchelf \
    xz-utils zstd \
    libboost-dev libboost-atomic-dev libboost-chrono-dev libboost-date-time-dev \
    libboost-filesystem-dev libboost-locale-dev libboost-serialization-dev libboost-system-dev \
    libboost-thread-dev \
    libcairo2-dev libpixman-1-dev libcurl4-openssl-dev libssl-dev libgit2-dev libsqlite3-dev \
    libzstd-dev zlib1g-dev libglew-dev libglm-dev libgl-dev libegl-dev libglu1-mesa-dev \
    libgtk-3-dev libharfbuzz-dev libfontconfig-dev libfreetype-dev libsecret-1-dev \
    libwxgtk3.2-dev libwxgtk-webview3.2-dev libngspice0-dev libnng-dev libprotobuf-dev \
    libocct-foundation-dev libocct-modeling-algorithms-dev libocct-modeling-data-dev \
    libocct-ocaf-dev libocct-visualization-dev libocct-data-exchange-dev \
    libpoppler-glib-dev unixodbc-dev libfreeimage-dev libxmu-dev libxt-dev libspnav-dev libjpeg-dev \
    libwayland-dev \
    xvfb xauth \
 && rm -rf /var/lib/apt/lists/*
