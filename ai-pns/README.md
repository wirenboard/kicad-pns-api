# KiCad with a push-and-shove router API, for AI agents

> **This is not upstream KiCad.** It is a fork of the KiCad development branch (10.99) with extra
> IPC API commands. Report KiCad bugs to [KiCad's GitLab](https://gitlab.com/kicad/code/kicad).
> Issues and pull requests on this GitHub repository are not watched.

This fork adds IPC API commands that drive pcbnew's interactive **push-and-shove (PNS) router**.
They run the same code path as routing with the mouse, but the clicks come from an API request.
It is meant for AI agents and scripts that route PCBs headlessly: the agent decides where a track
goes, and KiCad's router does the geometry, shoving and DRC-aware placement.

The branch `api-pns-router` carries the API. This directory, `ai-pns/`, holds the client, the host
scripts and the tools we use around it.

## What the API adds

All commands are in `api/proto/board/board_commands.proto`. Each one commits as one undo step.

| command | what it does |
|---|---|
| `RouteTrack` | Routes one track from `start` through `points`, each point acting as a click. Options: `mode` (shove, walkaround, mark obstacles), `width`, `finish_at_last_point`, `free_angle`, `corner_mode` (mitered/rounded 45/90). Diff pairs: `diff_pair`, `diff_pair_gap`. Vias: `point_layers`, where a layer change places a through via at the previous point, plus `via_diameter` and `via_drill`. It is all or nothing. The response returns `success`, `completed`, `message`, the reached `end`, and the created and removed item ids. |
| `DragTrack` | Drags the segment, arc or via under `grab` to `target`, like the interactive drag (45 degree) tool. It shoves neighbours in shove mode and refuses locked items. |
| `CleanupTracks` | Runs "Cleanup Tracks & Vias" on all nets or on the listed nets: merge segments, delete dangling tracks or vias, tracks in pads, shorting tracks and redundant vias. Supports `dry_run`. |
| `RunDrc` | Runs DRC and returns the violations (type, severity, description, position, layer, items, rule). It writes no markers or files. Options: `refill_zones`, `report_all_track_errors`, `nets` (filter). |

The commands need a board editor frame, so pcbnew runs as a GUI process on a virtual X display
(Xvfb). No real display is needed. They do not work in `kicad-cli`.

**Upstream base:** KiCad master `4cf93977` of 21.11.2026, merged into this branch (it was based on
master of 28.09.2026 before). Upstream KiCad changes are brought in by merging master; the branch
history is never rewritten.

Two smaller router changes are on this branch too:
- diff-pair length tuning recognises the pair gap it observes;
- a build fix for older glm.

## Installing a release build

Linux x86_64 builds are attached to the
[GitHub releases](https://github.com/wirenboard/kicad-pns-api/releases) of this repository. Every
CI run also keeps the same package as a workflow artifact for 30 days (Actions tab, "Build
binaries"). A package holds `pcbnew` only, built on Debian 13 (trixie). It is tested on Debian 13
and Ubuntu 24.04; other distributions need glibc 2.38+ and GTK 3.

**Host packages** (Debian 13 / Ubuntu 24.04 names; most desktops have them already):

```bash
sudo apt install libgtk-3-0t64 libwebkit2gtk-4.1-0 libsecret-1-0 libasound2t64 \
  libgl1 libegl1 libglx-mesa0 libgl1-mesa-dri xvfb python3-venv
```

Everything else (wxWidgets, OpenCascade, protobuf, nng, libgit2, Boost, ...) is bundled in `lib/`.

**Install:**

```bash
V=v1.0.0   # the release tag
F=kicad-pns-$V-linux-x86_64.tar.xz
curl -LO https://github.com/wirenboard/kicad-pns-api/releases/download/$V/$F
curl -LO https://github.com/wirenboard/kicad-pns-api/releases/download/$V/$F.sha256
sha256sum -c $F.sha256
tar -xJf $F                                    # anywhere; the package is relocatable
cd kicad-pns-$V-linux-x86_64
python3 -m venv venv && venv/bin/pip install -r ai-pns/requirements.txt
KPNS_PY=$PWD/venv/bin/python ai-pns/ci/smoke.sh   # self-test on a private Xvfb :97
```

**Package layout:**

| path | what |
|---|---|
| `bin/kicad-pns-pcbnew` | launcher: creates `$KICAD_CONFIG_HOME` (default `~/.config/kicad-pns`) with the API server enabled and no setup wizard, then runs pcbnew |
| `pcbnew/`, `plugins/3d/`, `resources/images.tar.gz`, `schemas/` | KiCad, in the layout of a build tree, so it finds its data next to itself |
| `lib/` | KiCad's own and bundled libraries; the binaries find them through a relative RUNPATH |
| `ai-pns/` | this directory: Python client, host scripts, tools; `ai-pns/requirements.txt` for the client |
| `share/demo-stickhub/` | KiCad's StickHub demo board, used by the self-test |
| `BUILDINFO` | source commit, build OS, required glibc, list of bundled libraries |

**Running.** The host scripts work from the unpacked package unchanged: `ai-pns/host/paths.sh`
detects the package and uses it as `$KPNS_BUILD`.

```bash
export KPNS_PY=$PWD/venv/bin/python
ai-pns/host/hoststart_n.sh 1 board.kicad_pcb board.kicad_pro   # Xvfb :91, socket /tmp/kpns1/kicad/api.sock
```

Or run the launcher yourself, on any X display:

```bash
TMPDIR=/tmp/kp1 DISPLAY=:97 bin/kicad-pns-pcbnew board.kicad_pcb   # API socket ipc:///tmp/kp1/kicad/api.sock
```

Stock footprint and symbol libraries are not included; the API works on the board as it is.

**CI.** `.github/workflows/kicad-pns-build.yml` builds the package in the image of
`ai-pns/ci/Dockerfile` (`ai-pns/ci/build.sh`, with ccache), packs it (`ai-pns/ci/package.sh`) and
runs the self-test in clean Debian 13 and Ubuntu 24.04 containers (`ai-pns/ci/test-clean.sh`). A
tag `v*` publishes the package and its `.sha256` as a release. The same scripts run locally:

```bash
docker build -t kpns-ci ai-pns/ci
docker run --rm -u $(id -u):$(id -g) -v "$PWD:$PWD" -w "$PWD" -e JOBS=8 kpns-ci ai-pns/ci/build.sh
docker run --rm -u $(id -u):$(id -g) -v "$PWD:$PWD" -w "$PWD" kpns-ci ai-pns/ci/package.sh dist
ai-pns/ci/test-clean.sh ubuntu:24.04 dist/kicad-pns-*-linux-x86_64.tar.xz
```

## Building from source

This is a normal KiCad build. See [KiCad's build docs](https://dev-docs.kicad.org/en/build/linux/)
for the dependency list. Since the November 2026 upstream base, the build also needs the Vulkan
shader tools `glslangValidator` and `spirv-opt` (Debian: `glslang-tools`, `spirv-tools`) and SQLite3.
The agents only use `pcbnew`, but build the default target: `pcbnew` alone does not produce
`resources/images.tar.gz` and `schemas/`, and without them pcbnew stops at start-up on an error
dialog.

```bash
cmake -G Ninja -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DKICAD_BUILD_QA_TESTS=OFF -DKICAD_BUILD_I18N=OFF -DKICAD_SPICE_QA=OFF -DKICAD_USE_SENTRY=OFF \
  -DKICAD_SCRIPTING_WXPYTHON=OFF -DKICAD_UPDATE_CHECK=OFF
ninja -C build
```

There is no need to install the build. Run it from the build tree with `KICAD_RUN_FROM_BUILD_DIR=1`.

**Without root, or on a host without KiCad's build dependencies**, we built in a Debian 13 (trixie)
environment with gcc 14 and OpenCascade 7.8. All packages were unpacked from `.deb` files into a
private directory; nothing was installed system-wide. `host/deps_list.txt` is the package list of
that build. The commands below show the procedure; they have not been rerun from scratch:

```bash
cd ai-pns/host
xargs -a deps_list.txt ./add_pkg.sh   # apt-get download + dpkg -x into $KPNS_DEPS
./configure.sh                        # the cmake line above, using the compiler and OCC from $KPNS_DEPS
source env.sh && ninja -C "$KPNS_BUILD"
```

On a host that is not Debian 13, run these steps in
the container of `host/Dockerfile.trixie`. It adds CMake 3.31, the shader tools and the runtime
libraries the unpacked toolchain loads from `/usr`; mount the source, build and `$KPNS_DEPS`
directories at the same paths as on the host. The resulting `pcbnew` runs on the host as described
below. What we actually ran for the November 2026 base: an existing `$KPNS_DEPS` tree from the
earlier build, its dangling `.so` links repointed to the image's libraries from inside the container
(the last step of `add_pkg.sh`), then `configure.sh` and `ninja`. `add_pkg.sh` itself has not been
run in this image (it needs apt lists and `apt-get download`). The unpacked `wx-config` reports `/usr` as its prefix, which sends CMake to a
`/usr/include/wx-3.2` the container does not have. Replace `$KPNS_DEPS/usr/bin/wx-config` with a
wrapper script:
`exec $KPNS_DEPS/usr/lib/x86_64-linux-gnu/wx/config/gtk3-unicode-3.2 --prefix=$KPNS_DEPS/usr "$@"`.

`host/paths.sh` documents every location variable (`KPNS_SRC`, `KPNS_BUILD`, `KPNS_DEPS`,
`KPNS_STATE`, ...). By default the source is this repository and the build goes to `./build`.

Notes:
- **No Python (SWIG) bindings in this build.** Old SWIG action plugins do not run in it. Tools that
  need `import pcbnew` (`transplant.py`, `fancheck.py`, `gridrouter/`) use a stock KiCad 10
  installation's Python module.
- **Board files are saved in the 10.99 format.** Stock KiCad 10.0 and its `kicad-cli` cannot open
  them. `tools/k10.py` and `tools/transplant.py` put the fork's copper back into a 10.0 file.
- **Running ninja re-runs CMake if the CMake files changed.** It then needs the same CMake modules
  as the configure step, so run ninja in the same environment (container) as the configure.
- **The board file format moves with upstream.** A build of a newer base saves boards with a newer
  version number (20261031 for the November 2026 base); an older build of this fork cannot open
  them.

## Running headless

The host scripts start pcbnew on a private Xvfb display. Each instance gets a private config, a
working copy of the board and its own API socket.

**Host requirements:**
- `Xvfb`, `xdotool`, and a Python with `protobuf` 5.29 and `pynng`:

  ```bash
  python3 -m venv venv && venv/bin/pip install -r ai-pns/requirements.txt
  export KPNS_PY=$PWD/venv/bin/python
  ```

- **If the build used unpacked `.deb` libraries:** do not put all of `$KPNS_DEPS` on
  `LD_LIBRARY_PATH`. The host's own GTK image loaders crash with it.
  - Link only what the host lacks, usually OpenCascade, FreeImage and libjpeg62:
    `host/make_hostlib.sh` creates `$KPNS_HOSTLIB` (symlinks) and reports any library that is
    still missing.
  - On a host with KiCad's runtime dependencies installed, `$KPNS_HOSTLIB` can stay empty.

**Instances:**

```bash
ai-pns/host/hoststart_n.sh 1 board.kicad_pcb board.kicad_pro   # -> READY ipc:///tmp/kpns1/kicad/api.sock pid 12345
ai-pns/host/hoststart_n.sh 2 other.kicad_pcb other.kicad_pro   # independent second instance
ai-pns/host/hoststop_n.sh 1 --xvfb                              # stop instance 1 and its Xvfb
```

- **Per instance N (1..6):**
  - Xvfb `:9N`;
  - socket `ipc:///tmp/kpnsN/kicad/api.sock`;
  - work dir `$KPNS_STATE/hosttestN` (board copy, `pcbnew.log`, `pcbnew.pid`);
  - config `$KPNS_STATE/hostcfgN`.
- **The board is copied.** The instance never writes back to your file. Save with
  `tools/save.py SOCKET out.kicad_pcb`.
- A `board.kicad_dru` next to the `.kicad_pro` is copied along (custom rules).
- **A running instance is not replaced.** `hoststart_n.sh` refuses (exit 3, `BUSY`) unless you pass
  `--force`, so one agent cannot kill another agent's unsaved work. Give each agent its own N.
- **Instances are independent.** Two instances started at the same moment both come up. Stopping
  one leaves the other answering. Startup takes about 15 to 30 s.
- `hoststart.sh` is the single-instance variant on `:99`. `start.sh` is a minimal variant that
  only waits for the socket.

**What the scripts take care of:**
- **Socket path length.** The IPC socket path must be shorter than 108 characters (Unix socket
  limit). KiCad puts it under `$TMPDIR/kicad/`, so the scripts set a short `TMPDIR`
  (`$KPNS_SOCK_PREFIX`, default `/tmp/kpns`).
- **Private config.** `KICAD_CONFIG_HOME` points to a private directory whose
  `10.99/kicad_common.json` has `"api": {"enable_server": true}`. The scripts create it if it is
  missing.
- **First-run dialogs.** A new private config is created with the first-run prompts answered and
  empty library tables, so the setup wizard does not appear. If it does (a config made by an older
  version of the scripts), the scripts click through it with `xdotool`, using fixed positions for a
  1920x1080 screen without a window manager. They also answer "Rescue" for items on undefined
  layers.
  - If an instance hangs at start, look at its display: `xwd -root -display :9N`.
  - Quit gracefully once after the first run so the config is written.
- **No real display.** `WAYLAND_DISPLAY` is unset so nothing opens on your desktop.

## Python client

`pyapi/` holds the client:
- `kipy/` is a trimmed copy of kicad-python's client. Its protobuf modules are generated from this
  tree's `api/proto`, because the PyPI package lacks the router messages. MIT licence, see
  `pyapi/kipy/LICENSE`.
- `nk_base.py` has small helpers.
- `pns.py` has the router calls.

```python
import sys; sys.path.insert(0, "ai-pns/pyapi")
import pns
from nk_base import bdt

c = pns.client_inst(1)                    # instance 1 of hoststart_n.sh (or KiCadClient(socket, name, "", timeout_ms))
doc = pns.board_doc(c)
before = pns.snapshot(c, doc)             # all tracks/arcs/vias

r = pns.route_track(c, doc, (10.0, 20.0), [(15.0, 20.0), (18.0, 23.0)], layer=bdt.BL_F_Cu,
                    width=0.254, mode="shove", corner="mitered45", finish=True,
                    point_layers=[bdt.BL_F_Cu, bdt.BL_B_Cu], via_diameter=0.7, via_drill=0.3)
viol = pns.run_drc(c, doc, nets=["NET1"], refill=True)
if not r.success or any(v.type in ("clearance", "shorting_items") for v in viol):
    pns.rollback(c, doc, before)          # also undoes neighbours moved by a failed shove

pns.drag_track(c, doc, grab=(12.0, 20.0), target=(12.0, 21.0), layer=bdt.BL_F_Cu)
pns.cleanup_tracks(c, doc, nets=["NET1"], merge=True, dangling=True)
pns.tracks_of(c, doc, "NET1")            # [(start, end, layer), ...]
```

Coordinates are in mm, in KiCad's own system (y down).
`rt.py` and `gridrouter/` use y-up coordinates by default (y = -KiCad y). For diff pairs pass `diff_pair=True` and
optionally `gap=`. Tuning patterns (`nk_base.tuning_pattern`, `create`) use the regular
`CreateItems` API.

## Tools

The Python tools run with `$KPNS_PY`. The tools that need `pcbnew` or shapely say so in their
docstring.

| file | what |
|---|---|
| `tools/lock.py SOCKET --nets A,B` | Locks all copper except these nets, so shove can only move your own copper. `--unlock` and `--status` also exist. |
| `tools/save.py SOCKET OUT` | Checkpoints the open board via `SaveDocumentToString`, written atomically. |
| `tools/baseline_drc.py SOCKET [OUT.tsv] [--refill] [--diff BASE.tsv]` | Dumps DRC as TSV, or prints only the violations that are not in a baseline. |
| `tools/drcsum.py N\|SOCKET` | DRC counts per type and unconnected items per net. |
| `tools/merge.py BASE OUT PART:NETS ...` | Integrator: merges the copper of several agents' boards, one net group each, into BASE. Reports foreign edits and clearance conflicts. Needs shapely. |
| `tools/kpcb.py` | Minimal s-expression access to `.kicad_pcb`, used by `merge.py`. |
| `tools/rt.py` | Interactive helper: `R(n).go(net, pts)` routes, checks DRC and rolls back on regressions. |
| `tools/drive.py GUIDES.json` | Routes planned guide paths with the PNS router, shove then walkaround, with optional rip-up. |
| `tools/clean.py [SOCKET]` | Runs `CleanupTracks` repeatedly on the whole board. |
| `tools/transplant.py BASE10 TRACKS.json OUT` | Puts tracks dumped by `drive.py --save` into a stock 10.0 board. Needs stock `pcbnew`. |
| `tools/k10.py BASE10 FORK OUT` | Text-level copy of the fork board's copper into a 10.0 board. |
| `tools/cdrc.sh FORK TAG BASE10` | `k10.py` plus stock `kicad-cli pcb drc --refill-zones`, with a summary. |
| `tools/fancheck.py BOARD10` | Geometry checks: 45-degree angles, ends on pad centres, pad exits along the pad axis. Needs stock `pcbnew`. |
| `gridrouter/fr.py`, `lib2.py`, `astar.c` | A multi-layer grid A* finisher on a stock 10.0 board, for nets the PNS router cannot reach. Board-specific keep-outs go in a config: see the docstring and `fr_config.example.json`. Build with `cc -O2 -shared -fPIC -o libastar.so astar.c -lm`. |
| `examples/rules.example.kicad_dru` | Custom rules: a track and clearance minimum, a relaxed "neck" area for fine-pitch parts, and a power via check. |

### Parallel routing by several agents

1. Prepare a common start board (BASE) by opening it in the fork once and saving it with
   `save.py`. `merge.py` requires the same file version for BASE and all parts.
2. Give each agent a disjoint set of nets and its own instance N:
   - start with `hoststart_n.sh N BASE PROJECT.kicad_pro`;
   - run `lock.py SOCKET --nets <own nets>`;
   - route;
   - check with `baseline_drc.py --refill --diff baseline.tsv`;
   - checkpoint often with `save.py`.
3. **Owning a net means owning all of its copper.** `merge.py` replaces every segment, arc and via
   of the listed nets with the part's copy. It discards changes to other nets and reports them as
   `FOREIGN`. It reports copper closer than `--clearance` to another net as `CONFLICT`.
4. Load OUT in the fork and run DRC with refill against the baseline.

### Router behaviour to expect

- **Judge by geometry and DRC, not by flags.**
  - `success`/`completed` can report OK while the track stopped short of the end pad. Check
    `r.end`, `tracks_of()` and `run_drc(nets=[net])`.
  - A net is done when DRC shows no `unconnected_items` and no `track_dangling` for it.
- **A failed shove attempt can leave neighbours moved.** Always snapshot before a route and
  `rollback()` on failure.
- **Vias:** the router places a 0.7/0.3 via unless you pass `via_diameter`/`via_drill`. It does
  not use the netclass via. One layer-change call has been seen to return `success=True` without
  placing a via, so count the vias.
- **Do not use `corner="rounded45"`.** The router created the arcs but dropped the straight piece
  between an arc and the next segment, which left dangling items. `None` and `"mitered45"`
  connect.
- **Locked copper is not shoved.** The route walks around it or fails with
  `could not reach point N`. Locks are saved in the board.
- **A route that does not start on copper of a net creates a net-less track.** Start on a pad,
  via or track of the net.
- **`cleanup_tracks` without `nets` edits every net.** Pass your nets when others own the rest
  of the board.
- **`run_drc` without `refill=True` sees unfilled zones.**
- The `rule` field of a violation can read `Local override` for everything. The `description`
  names the rule or netclass.
- **A custom rule that relaxes width or clearance applies per segment.** A segment that merely
  touches the rule area gets the relaxed values along its whole length. The router applies the
  relaxed clearance to every segment of a `route_track` call that touches the area. Route a
  fine-pitch neck in its own call that ends just outside the area, then continue at full width.

## Documentation

- [docs/QUICKSTART.md](docs/QUICKSTART.md): a short start for humans and AI agents.
- [docs/ROUTING_RECIPE.md](docs/ROUTING_RECIPE.md): how we route a board with this tool, from rules
  and fan-out to A* guides smoothed by the PNS router, and how track widths are chosen.

## Licence

KiCad, and with it this branch, is GPL-3.0-or-later. `pyapi/kipy/` is MIT (see its LICENSE).
