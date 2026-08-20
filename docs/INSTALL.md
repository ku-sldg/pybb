# Installing the pybb demo stack

This guide gets a fresh machine from `git clone` to both interactive
demo arcs running with a passing attestation readiness gate:

- **`examples/demo_rocq.sh`** — the temp-control Rocq workflow: a formal
  model measured, appraised, tampered with, and repaired under Copland
  attestation (8 scenes; see `docs/demo_rocq_script_summary.md`).
- **`examples/demo_isolette.sh`** — the isolette SysMLv2 → HAMR → Rust/Verus
  workflow: spec drift, promotion gates, and toolchain identity (10 scenes;
  see `docs/demo_isolette_script_summary.md`).

## Supported platforms

| Platform | Status |
|---|---|
| macOS arm64 (Apple Silicon) | tested |
| Linux x86_64 (Debian/Ubuntu) | written to spec, **untested** — please report problems and successes |

Not covered: Intel macOS, Windows/WSL. The Lean examples (not part of
these two demos) are additionally macOS-only as written (`.dylib`
artifact names in `pybb/attestation/tools.py`).

## Required layout

Almost every component location is a `Path.home()`-derived constant in
pybb, so the layout is **fixed** — the installer creates it:

| Component | Pinned version | Location |
|---|---|---|
| pybb (this repo, `dev` branch) | — | anywhere; `~/Claude_workspace/pybb` recommended |
| CVM (`ku-sldg/cvm`) | branch `fix/explicit-stdin-flag` | `~/Claude_workspace/cvm` |
| asp-libs (`ku-sldg/asp-libs`) | branch `hamr-asps` | `~/Claude_workspace/asp-libs` |
| copland-evidence-tools (optional) | branch `req-file-input` | `~/Claude_workspace/copland-evidence-tools` |
| Rocq Prover (opam switch **named `5.2`**, OCaml 5.2.0) | coq 9.0.1 | `~/.opam/5.2` |
| Verus (binary release) | 0.2026.01.23.1650a05 | `~/Claude_workspace/verus-<plat>` + symlink `~/Claude_workspace/verus-dist` |
| Rust (rustup) | nightly-2026-01-25 (+ stable) | `~/.rustup`, `~/.cargo` |
| Sireum kekinian (HAMR) | 4.20260720.6a05e505 | `~/Applications/Sireum` |
| sysml-aadl-libraries | commit `9016cbc` | `~/Claude_workspace/sysml-aadl-libraries` |
| tool wrappers (generated) | — | `~/Claude_workspace/bin` |

All version pins live in one place: [`scripts/versions.sh`](../scripts/versions.sh).
They are load-bearing — tool bytes are hashed into the attested baselines,
and the isolette crates pin the matching Rust nightly and Verus crate
versions. sysml-aadl-libraries must be **no newer than the Sireum
release** (newer library commits crash older frontends).

Budget roughly **10–15 GB of disk** and **45–90 minutes** (the opam/coq
build of the CVM dominates; the first isolette Verus run later cold-builds
its crates for several more minutes).

## Prerequisites

- **macOS**: Xcode Command Line Tools (`xcode-select --install`) and
  [Homebrew](https://brew.sh). The installer brews `opam zeromq gmp
  pkg-config` (and `python@3.12` if no Python ≥ 3.11 is present).
- **Linux (apt)**: sudo access. The installer installs `build-essential
  git curl unzip xz-utils m4 pkg-config libgmp-dev libzmq3-dev python3
  python3-venv opam`. opam must end up ≥ 2.1 (Ubuntu ≥ 23.04's apt
  package is fine; otherwise use the
  [official install script](https://opam.ocaml.org/doc/Install.html)).
- Network access to github.com, the opam repositories
  (opam.ocaml.org, coq.inria.fr), and crates.io.
- **No API keys are required.** `ANTHROPIC_API_KEY` is optional and only
  used by demo_rocq scene 5 with `--repair-strategy llm` (it dry-runs
  without a key). `OPENAI_API_KEY` is only for the AutoVerus example,
  which these demos don't use.

## Running the installer

```bash
git clone -b dev https://github.com/ku-sldg/pybb.git ~/Claude_workspace/pybb
cd ~/Claude_workspace/pybb
scripts/install.sh
```

The installer is **idempotent**: every step starts with a state probe
(binary present at the pinned version, repo on the pinned ref, readiness
PASS) and is skipped when already satisfied. Re-running after a failure
resumes where it stopped; `--from <step>` jumps straight there.

```
scripts/install.sh --list-steps      # the step names
scripts/install.sh --dry-run         # probe everything, execute nothing
scripts/install.sh --from build-cvm  # resume at a step
scripts/install.sh --only wrappers   # run exactly one step
scripts/install.sh --skip-sireum     # rocq demo only (no isolette)
scripts/install.sh --skip-evidence-tools
```

Steps, in order: `prereqs` (packages) → `rustup` (stable + pinned
nightly with Verus's components) → `opam-switch` (switch `5.2`,
`coq-released` and `ku-sldg` repos) → `clone-repos` → `build-cvm` (the
long one) → `build-asp-libs` → `build-evidence-tools` → `verus`
(download release, symlink `verus-dist`) → `sireum` (download release) →
`wrappers` (generate `~/Claude_workspace/bin/*`) → `pybb-venv`
(`.venv` + `pip install -e .[dev]`) → `provision-rocq` →
`provision-isolette`.

Afterwards, verify any time with the read-only doctor:

```bash
scripts/check_install.sh           # component checks
scripts/check_install.sh --ready   # + both readiness gates (~1-2 min)
```

## Why the installer re-provisions and re-blesses

The repository ships signed golden baselines (`golden/`,
`tests/fixtures/*/asp_args.json`, `golden/_bundles/*/provision_bundle.json`).
Those baselines are **hashes of the baseline owner's machine**: absolute
file paths and the exact bytes of their tool wrappers and binaries. On
any other machine the readiness gate would (correctly!) refuse to run —
that refusal is the attestation story working as designed.

So provisioning + blessing is a first-class install step, not a
workaround: the last two steps run

```bash
.venv/bin/python examples/temp_control_rocq.py --provision --bless-model --bless-tools
.venv/bin/python examples/isolette_rust.py --frontend sysml --provision --bless-props
```

and then require `readiness: PASS` from both drivers. This roots the
attested baselines in *your* paths and *your* tool bytes.

**Note: this rewrites tracked files** under `tests/fixtures/` and
`golden/` (and adds a `golden/<your-absolute-repo-path>` mirror). That is
expected and local — leave it uncommitted. `git checkout -- tests/fixtures
golden` restores the maintainer baseline, after which readiness FAILs on
your machine until you re-provision.

## Running the demos

Quick unattended smoke runs (no pauses, decision beats auto-resolved):

```bash
examples/demo_rocq.sh --fast --auto bless --no-vscode
examples/demo_isolette.sh --fast --auto bless --no-vscode
```

The real, interactive arcs (run in a terminal; both need a TTY for their
pause/decision prompts; `--help` on either script lists every flag):

```bash
examples/demo_rocq.sh                 # 8 scenes
examples/demo_isolette.sh             # 10 scenes
examples/demo_rocq.sh --scenes "1 2 3"
```

Expect `(measurements running — first output can take ~30-60s)` pauses —
that's the CVM measuring, not a hang. The **first** isolette run
cold-builds the Verus crates and downloads their pinned crates.io
dependencies (`vstd`/`verus_builtin`), which takes several minutes once.

Only one demo can run at a time (they share a lock — see
troubleshooting below).

## Environment overrides

Everything works with no environment setup. For non-standard layouts:

| Variable | Overrides |
|---|---|
| `CVM_BINARY` | CVM binary (default `~/Claude_workspace/cvm/_build/default/theories/cvm`) |
| `ASP_BIN` | ASP binaries dir (default `~/Claude_workspace/asp-libs/target/release`) |
| `COPLAND_EVIDENCE_TOOLS` | evidence summarizer binary (optional feature) |
| `VERUS_DIST` | Verus distribution dir (default `~/Claude_workspace/verus-dist`) |

Note that the *attested tool wrappers* in `~/Claude_workspace/bin`
hardcode the canonical layout — if you relocate a toolchain, re-bless
afterwards.

## Troubleshooting

- **`readiness: FAIL` naming golden/baseline mismatches** right after
  cloning: expected — you haven't provisioned yet. Run the installer (or
  its last two steps).
- **`readiness: FAIL` naming a tool hash** (e.g. `bin/rocq` or
  `bin/cargo-verus`): the wrapper's bytes drifted from the blessing.
  `examples/demo_rocq.sh --restore-tools` /
  `examples/demo_isolette.sh --restore-tools` reinstalls the canonical
  wrapper and proves it against the blessed golden; if the wrapper
  *legitimately* changed, re-bless instead (`--provision --bless-tools`
  for rocq, `--provision` for isolette).
- **`DEMO ABORT: another demo run (pid N) holds .demo.lock`** with no
  demo actually running: a previous run was killed hard. The scripts
  self-heal stale locks when the pid is dead; if needed,
  `rm -rf .demo.lock` from the repo root.
- **A long silence during a demo or provisioning**: cold Verus/cargo
  builds and CVM measurement batches are multi-minute. The scripts print
  a warning where this is expected.
- **opam fails on zeromq/conf-zmq**: install the system package
  (`brew install zeromq` / `apt install libzmq3-dev`) and re-run; opam ≥
  2.1 normally handles this via depexts.
- **macOS Gatekeeper blocks verus**: run
  `~/Claude_workspace/verus-dist/macos_allow_gatekeeper.sh` (the
  installer does this; it can need re-running after a manual re-download).
- **Sireum's first invocation downloads more components**: expected; the
  installer triggers it during the `sireum` step so it doesn't happen
  mid-demo.
- **`git status` shows modified files under `tests/fixtures/` and
  `golden/`**: expected after provisioning — see
  [above](#why-the-installer-re-provisions-and-re-blesses).
