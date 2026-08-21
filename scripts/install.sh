#!/usr/bin/env bash
# install.sh — build the full pybb attested-development stack and bring
# both demo arcs (examples/demo_rocq.sh, examples/demo_isolette.sh) to a
# passing readiness gate on THIS machine. See docs/INSTALL.md.
#
# Idempotent: every step starts with a state probe (binary present and
# at the pinned version, repo on the pinned ref, readiness PASS) and is
# skipped when already satisfied — re-running on a healthy machine is a
# fast no-op walk, and a failed run resumes where it stopped.
#
# Flags:
#   --dry-run              probe every step, execute nothing
#   --skip-sireum          skip Sireum + sysml-aadl-libraries + isolette
#                          provisioning (demo_isolette scenes 3/8 and its
#                          readiness gate need Sireum)
#   --skip-evidence-tools  skip copland-evidence-tools (the evidence
#                          summarizer degrades gracefully without it)
#   --only <step>          run exactly one step
#   --from <step>          start at <step> (resume after a failure)
#   --list-steps           print the step names and exit

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=versions.sh
. "$SCRIPT_DIR/versions.sh"

STEPS=(prereqs rustup opam-switch clone-repos build-cvm build-asp-libs
       build-evidence-tools verus sireum wrappers pybb-venv
       provision-rocq provision-isolette)

DRY_RUN=0 SKIP_SIREUM=0 SKIP_CET=0 ONLY="" FROM=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --skip-sireum) SKIP_SIREUM=1 ;;
    --skip-evidence-tools) SKIP_CET=1 ;;
    --only) ONLY="$2"; shift ;;
    --from) FROM="$2"; shift ;;
    --list-steps) printf '%s\n' "${STEPS[@]}"; exit 0 ;;
    -h|--help) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown flag: $1 (see --help)" >&2; exit 2 ;;
  esac
  shift
done
for name in $ONLY $FROM; do
  case " ${STEPS[*]} " in *" $name "*) ;; *)
    echo "unknown step: $name (see --list-steps)" >&2; exit 2 ;; esac
done

BOLD=$'\033[1m'; DIM=$'\033[2m'; RESET=$'\033[0m'
die() { echo "ERROR: $*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
banner() { echo; echo "${BOLD}==[ $1 ]== $2${RESET}"; }

# rustup/cargo land here; a fresh install needs them on PATH immediately
export PATH="$HOME/.cargo/bin:$PATH"

CURRENT_STEP="(setup)"
trap 'echo; echo "${BOLD}FAILED at step ${CURRENT_STEP}${RESET} — fix the error above, then" >&2;
      echo "re-run scripts/install.sh (or: scripts/install.sh --from ${CURRENT_STEP})" >&2' ERR

# find_python — newest interpreter satisfying pyproject's >=3.11
find_python() {
  local c
  for c in python3.13 python3.12 python3.11 python3; do
    if have "$c" && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' \
        2>/dev/null; then
      echo "$c"; return 0
    fi
  done
  return 1
}

# clone_pinned <url> <dest> <branch-or-empty> [commit]
clone_pinned() {
  local url="$1" dest="$2" branch="$3" commit="${4:-}"
  if [ ! -d "$dest/.git" ]; then
    if [ -n "$branch" ]; then
      git clone --branch "$branch" "$url" "$dest"
    else
      git clone "$url" "$dest"
    fi
    [ -n "$commit" ] && git -C "$dest" checkout --quiet "$commit"
    return 0
  fi
  # existing checkout: verify the ref, never mutate a user's clone
  if [ -n "$commit" ]; then
    [ "$(git -C "$dest" rev-parse HEAD)" = "$commit" ] \
      || die "$dest exists but is not at pinned commit $commit —
    move it aside, or: git -C $dest checkout $commit"
  elif [ -n "$branch" ]; then
    [ "$(git -C "$dest" rev-parse --abbrev-ref HEAD)" = "$branch" ] \
      || die "$dest exists but is not on branch '$branch' —
    move it aside, or: git -C $dest checkout $branch"
  fi
}

repo_at_ref() {  # repo_at_ref <dest> <branch-or-empty> [commit]
  local dest="$1" branch="$2" commit="${3:-}"
  [ -d "$dest/.git" ] || return 1
  if [ -n "$commit" ]; then
    [ "$(git -C "$dest" rev-parse HEAD 2>/dev/null)" = "$commit" ]
  else
    [ "$(git -C "$dest" rev-parse --abbrev-ref HEAD 2>/dev/null)" = "$branch" ]
  fi
}

# ── wrapper contents ────────────────────────────────────────────────────────
# These bytes are attested: the tool tiers hash the installed wrappers
# against blessed goldens. The rocq and cargo-verus texts MUST stay
# byte-identical to the --restore-tools heredocs in examples/demo_rocq.sh
# and examples/demo_isolette.sh (marked KEEP IN SYNC there).

wrapper_rocq() { cat <<'EOF'
#!/usr/bin/env bash
# Workspace wrapper: rocq (the Rocq Prover, opam switch 5.2)
# (CVM child processes see this via CvmConfig.path_prepend).
# The opam bin dir is prepended so rocq's own subprocesses (coqc,
# coqdep, ...) resolve from the same pinned switch.
export PATH="$HOME/.opam/5.2/bin:$PATH"
exec "$HOME/.opam/5.2/bin/rocq" "$@"
EOF
}

wrapper_dune() { cat <<'EOF'
#!/usr/bin/env bash
# Workspace wrapper: dune (build tool for the Rocq examples, opam
# switch 5.2). (CVM child processes see this via
# CvmConfig.path_prepend.) The opam bin dir is prepended so dune's
# coq rules resolve rocq/coqc/coqdep from the same pinned switch.
export PATH="$HOME/.opam/5.2/bin:$PATH"
exec "$HOME/.opam/5.2/bin/dune" "$@"
EOF
}

wrapper_cargo_verus() { cat <<'EOF'
#!/usr/bin/env bash
# Workspace wrapper: cargo-verus with the Verus distribution and cargo on PATH
# (CVM child processes see this via CvmConfig.path_prepend).
export PATH="$HOME/Claude_workspace/verus-dist:$HOME/.cargo/bin:$PATH"
exec "$HOME/Claude_workspace/verus-dist/cargo-verus" "$@"
EOF
}

wrapper_verus() { cat <<'EOF'
#!/usr/bin/env bash
# Workspace wrapper: verus with the Verus distribution on PATH
# (CVM child processes see this via CvmConfig.path_prepend, so the
# run_command_verus ASP resolves `verus` here).
export PATH="$HOME/Claude_workspace/verus-dist:$PATH"
exec "$HOME/Claude_workspace/verus-dist/verus" "$@"
EOF
}

wrapper_sireum() { cat <<'EOF'
#!/usr/bin/env bash
# Workspace wrapper: sireum (the HAMR standalone distribution)
# (CVM child processes see this via CvmConfig.path_prepend).
export SIREUM_HOME="$HOME/Applications/Sireum"
exec "$HOME/Applications/Sireum/bin/sireum" "$@"
EOF
}

# ── steps ───────────────────────────────────────────────────────────────────

probe_prereqs() {
  # a functional .venv stands in for a PATH python — venv creation is
  # the only thing that needs one
  find_python >/dev/null || probe_pybb_venv || return 1
  have git && have curl && have unzip && have opam || return 1
  if [ "$PLATFORM" = macos ]; then
    brew list zeromq >/dev/null 2>&1
  else
    pkg-config --exists libzmq 2>/dev/null
  fi
}

do_prereqs() {
  if [ "$PLATFORM" = macos ]; then
    xcode-select -p >/dev/null 2>&1 \
      || die "Xcode Command Line Tools missing — run: xcode-select --install"
    have brew || die "Homebrew missing — install it from https://brew.sh"
    brew install opam zeromq gmp pkg-config
    find_python >/dev/null || brew install python@3.12
  else
    have apt-get || die "no apt-get — install these with your package manager:
    build-essential git curl unzip xz-utils m4 pkg-config libgmp-dev
    libzmq3-dev python3 (>=3.11) python3-venv opam (>=2.1)"
    sudo apt-get update
    # bubblewrap: opam's build sandbox (see do_opam_switch for the fallback
    # when the kernel restricts unprivileged user namespaces)
    sudo apt-get install -y build-essential git curl unzip xz-utils m4 \
      pkg-config libgmp-dev libzmq3-dev bubblewrap python3 python3-venv
    have opam || sudo apt-get install -y opam \
      || die "could not install opam via apt — see https://opam.ocaml.org/doc/Install.html"
  fi
  find_python >/dev/null || die "no python >= 3.11 on PATH after prereq install"
}

probe_rustup() {
  have rustup \
    && out_has "^stable" rustup toolchain list \
    && out_has "$RUST_NIGHTLY" rustup toolchain list \
    && out_has "^$VERUS_TOOLCHAIN" rustup toolchain list
}

do_rustup() {
  if ! have rustup; then
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
      | sh -s -- -y --no-modify-path
  fi
  rustup toolchain install stable
  # nightly pin + components must match the isolette crates'
  # rust-toolchain.toml (Verus hooks rustc internals); the
  # aarch64-unknown-none cross target is covered by -Z build-std +
  # rust-src, no prebuilt target needed
  rustup toolchain install "$RUST_NIGHTLY" \
    -c rustfmt -c rust-src -c rustc-dev -c llvm-tools-preview -c rust-analyzer
  # the verus launcher refuses to run without the exact toolchain the
  # release binaries were built with
  rustup toolchain install "$VERUS_TOOLCHAIN"
}

probe_opam_switch() {
  out_has_line "$OPAM_SWITCH" opam switch list --short \
    && out_has "ku-sldg" opam repo list --all --short
}

do_opam_switch() {
  if [ ! -d "$HOME/.opam" ]; then
    # Ubuntu 23.10+ restricts unprivileged user namespaces (AppArmor),
    # which can break opam's bubblewrap sandbox even when installed —
    # fall back to unsandboxed builds with a warning (common on CI)
    if ! opam init --bare --no-setup -y; then
      echo "warning: opam init failed with sandboxing — retrying with"
      echo "--disable-sandboxing (opam builds will run unsandboxed)"
      rm -rf "$HOME/.opam"
      opam init --bare --no-setup --disable-sandboxing -y
    fi
  fi
  out_has_line "$OPAM_SWITCH" opam switch list --short \
    || opam switch create "$OPAM_SWITCH" "$OCAML_COMPILER" -y
  out_has "coq-released" opam repo list --all --short \
    || opam repo add coq-released https://coq.inria.fr/opam/released \
         --all-switches --set-default
  out_has "ku-sldg" opam repo list --all --short \
    || opam repo add ku-sldg/opam-repo "$KU_SLDG_OPAM_REPO" \
         --all-switches --set-default
}

probe_clone_repos() {
  repo_at_ref "$WORKSPACE/cvm" "$CVM_BRANCH" \
    && repo_at_ref "$WORKSPACE/asp-libs" "$ASP_LIBS_BRANCH" \
    && { [ "$SKIP_CET" = 1 ] \
         || repo_at_ref "$WORKSPACE/copland-evidence-tools" "" "$CET_COMMIT"; } \
    && { [ "$SKIP_SIREUM" = 1 ] \
         || repo_at_ref "$WORKSPACE/sysml-aadl-libraries" "" "$SYSML_LIBS_COMMIT"; }
}

do_clone_repos() {
  mkdir -p "$WORKSPACE"
  clone_pinned "$CVM_URL" "$WORKSPACE/cvm" "$CVM_BRANCH"
  clone_pinned "$ASP_LIBS_URL" "$WORKSPACE/asp-libs" "$ASP_LIBS_BRANCH"
  [ "$SKIP_CET" = 1 ] \
    || clone_pinned "$CET_URL" "$WORKSPACE/copland-evidence-tools" "" "$CET_COMMIT"
  # pinned no newer than the Sireum release: newer library commits crash
  # older frontends (see examples/isolette_rust.py)
  [ "$SKIP_SIREUM" = 1 ] \
    || clone_pinned "$SYSML_LIBS_URL" "$WORKSPACE/sysml-aadl-libraries" \
         "" "$SYSML_LIBS_COMMIT"
}

probe_build_cvm() { [ -x "$WORKSPACE/cvm/_build/default/theories/cvm" ]; }

do_build_cvm() {
  echo "${DIM}(building the CVM pulls coq $ROCQ_VERSION + the Copland opam"
  echo " packages — this is the long step, expect 20-40 minutes)${RESET}"
  ( cd "$WORKSPACE/cvm" \
    && opam install ./rocq-cvm.opam --switch="$OPAM_SWITCH" --deps-only -y \
    && opam exec --switch="$OPAM_SWITCH" -- dune build )
}

probe_build_asp_libs() {
  [ -x "$WORKSPACE/asp-libs/target/release/hashfile" ] \
    && [ -x "$WORKSPACE/asp-libs/target/release/sig" ]
}

do_build_asp_libs() {
  ( cd "$WORKSPACE/asp-libs" && make )
}

probe_build_evidence_tools() {
  [ "$SKIP_CET" = 1 ] || [ -x \
    "$WORKSPACE/copland-evidence-tools/_build/default/theories/copland_evidence_tools" ]
}

do_build_evidence_tools() {
  [ "$SKIP_CET" = 1 ] && return 0
  ( cd "$WORKSPACE/copland-evidence-tools" \
    && opam install ./rocq-copland-evidence-tools.opam \
         --switch="$OPAM_SWITCH" --deps-only -y \
    && opam exec --switch="$OPAM_SWITCH" -- dune build )
}

probe_verus() {
  [ -x "$VERUS_DIST_LINK/verus" ] \
    && out_has "$VERUS_VERSION" "$VERUS_DIST_LINK/verus" --version
}

do_verus() {
  if [ ! -x "$VERUS_DIST_DIR/verus" ]; then
    local tmp zip url
    tmp="$(mktemp -d)"
    url="https://github.com/verus-lang/verus/releases/download/release%2F${VERUS_VERSION}/verus-${VERUS_VERSION}-${VERUS_PLAT}.zip"
    zip="$tmp/verus.zip"
    echo "downloading $url"
    curl -fL -o "$zip" "$url"
    ( cd "$tmp" && unzip -q "$zip" )
    local extracted
    extracted="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d)"
    [ "$(echo "$extracted" | wc -l)" -eq 1 ] && [ -x "$extracted/verus" ] \
      || die "unexpected verus zip layout under $tmp — install by hand into $VERUS_DIST_DIR"
    mkdir -p "$WORKSPACE"
    mv "$extracted" "$VERUS_DIST_DIR"
    rm -rf "$tmp"
  fi
  if [ "$PLATFORM" = macos ]; then
    # what the dist's macos_allow_gatekeeper.sh does (that script itself
    # doesn't run cleanly under bash): strip the quarantine bit so
    # Gatekeeper doesn't block the downloaded binaries
    xattr -dr com.apple.quarantine "$VERUS_DIST_DIR" 2>/dev/null || true
  fi
  ln -sfn "$VERUS_DIST_DIR" "$VERUS_DIST_LINK"
  # surface what --version actually says (the probe suppresses stderr) —
  # this is the first thing to read when a fresh platform misbehaves
  echo "verus --version reports:"
  "$VERUS_DIST_LINK/verus" --version || echo "(verus --version exited $?)"
  if [ "$PLATFORM" = linux ] && command -v ldd >/dev/null 2>&1; then
    echo "dynamic deps:"
    ldd "$VERUS_DIST_DIR/verus" || true
  fi
}

probe_sireum() {
  [ "$SKIP_SIREUM" = 1 ] && return 0
  [ -x "$SIREUM_HOME_DIR/bin/sireum" ] \
    && out_has "$SIREUM_TAG" "$SIREUM_HOME_DIR/bin/sireum" --version
}

do_sireum() {
  [ "$SKIP_SIREUM" = 1 ] && return 0
  if [ ! -x "$SIREUM_HOME_DIR/bin/sireum" ]; then
    local tmp tar url extracted
    tmp="$(mktemp -d)"
    url="https://github.com/sireum/kekinian/releases/download/${SIREUM_TAG}/sireum-cli-${SIREUM_PLAT}.tar.xz"
    tar="$tmp/sireum.tar.xz"
    echo "downloading $url"
    curl -fL -o "$tar" "$url"
    mkdir "$tmp/extract"
    tar -xJf "$tar" -C "$tmp/extract"
    extracted="$(find "$tmp/extract" -mindepth 1 -maxdepth 1 -type d)"
    [ "$(echo "$extracted" | wc -l)" -eq 1 ] && [ -x "$extracted/bin/sireum" ] \
      || die "unexpected sireum tar layout under $tmp — install by hand into $SIREUM_HOME_DIR"
    mkdir -p "$(dirname "$SIREUM_HOME_DIR")"
    mv "$extracted" "$SIREUM_HOME_DIR"
    rm -rf "$tmp"
  elif ! out_has "$SIREUM_TAG" "$SIREUM_HOME_DIR/bin/sireum" --version; then
    die "$SIREUM_HOME_DIR exists but is not Sireum v$SIREUM_TAG —
    move it aside and re-run (the isolette baselines are pinned to that release)"
  fi
  mkdir -p "$WORKSPACE/.sireum_cache"
  # first run bootstraps further downloads — do it now, not mid-demo
  "$SIREUM_HOME_DIR/bin/sireum" --version >/dev/null
}

probe_wrappers() {
  wrapper_rocq        | cmp -s - "$WORKSPACE/bin/rocq" \
  && wrapper_dune        | cmp -s - "$WORKSPACE/bin/dune" \
  && wrapper_cargo_verus | cmp -s - "$WORKSPACE/bin/cargo-verus" \
  && wrapper_verus       | cmp -s - "$WORKSPACE/bin/verus" \
  && [ -x "$WORKSPACE/bin/sireum" ]
}

do_wrappers() {
  mkdir -p "$WORKSPACE/bin"
  wrapper_rocq        > "$WORKSPACE/bin/rocq"
  wrapper_dune        > "$WORKSPACE/bin/dune"
  wrapper_cargo_verus > "$WORKSPACE/bin/cargo-verus"
  wrapper_verus       > "$WORKSPACE/bin/verus"
  # sireum's wrapper is NOT hash-attested; respect a deliberate existing
  # one (e.g. a maintainer pointing at a development Sireum tree)
  if [ ! -e "$WORKSPACE/bin/sireum" ]; then
    wrapper_sireum > "$WORKSPACE/bin/sireum"
  else
    echo "keeping the existing $WORKSPACE/bin/sireum (not attested)"
  fi
  chmod +x "$WORKSPACE/bin/rocq" "$WORKSPACE/bin/dune" \
           "$WORKSPACE/bin/cargo-verus" "$WORKSPACE/bin/verus" \
           "$WORKSPACE/bin/sireum"
}

driver_ready() {  # driver_ready <driver.py> [extra args...] — prints + gates
  local driver="$1" out; shift
  out="$( (cd "$REPO" && "$REPO/.venv/bin/python" "examples/$driver" "$@" --ready) 2>&1 )" \
    || true
  printf '%s\n' "$out"
  grep -q "readiness: PASS" <<<"$out"
}

driver_ready_quiet() {  # same gate, no output (for probes)
  local driver="$1" out; shift
  out="$( (cd "$REPO" && "$REPO/.venv/bin/python" "examples/$driver" "$@" --ready) 2>&1 )" \
    || true
  grep -q "readiness: PASS" <<<"$out"
}

probe_pybb_venv() {
  [ -x "$REPO/.venv/bin/python" ] \
    && "$REPO/.venv/bin/python" -c 'import pybb, pydantic' 2>/dev/null
}

do_pybb_venv() {
  local py
  py="$(find_python)" || die "no python >= 3.11 on PATH"
  # the demo scripts hardcode <repo>/.venv/bin/python — the name matters
  [ -d "$REPO/.venv" ] || "$py" -m venv "$REPO/.venv"
  "$REPO/.venv/bin/pip" install --upgrade pip
  "$REPO/.venv/bin/pip" install -e "$REPO[dev]"
}

# The committed baselines under golden/ and tests/fixtures/ are signed
# hashes of the BASELINE OWNER's absolute paths and tool bytes; readiness
# on any other machine (or after the wrappers step rewrites a wrapper)
# must be re-rooted by provisioning + blessing HERE. See docs/INSTALL.md.

# wrapper_blessed <wrapper> <fixture-asp_args.json> <filepath-suffix>
# Readiness does NOT re-hash live tool bytes (that happens at attestation
# time), so the provision probes must check the attested wrappers against
# the blessed goldens themselves — otherwise a rewritten wrapper leaves a
# "ready" install that fails its first real measurement.
wrapper_blessed() {
  [ -f "$1" ] && [ -f "$2" ] || return 1
  "$REPO/.venv/bin/python" - "$1" "$2" "$3" <<'PYEOF'
import base64, hashlib, json, sys
digest = base64.b64encode(
    hashlib.sha256(open(sys.argv[1], "rb").read()).digest()).decode()
args = json.load(open(sys.argv[2]))
golden = next((a["golden_b64"] for a in args.get("hashfile", {}).values()
               if a.get("filepath", "").endswith(sys.argv[3])), None)
sys.exit(0 if golden == digest else 1)
PYEOF
}

# fixture_local <asp_args.json> <repo-subpath> — the fixture's file
# targets point into THIS repo checkout. The committed baselines carry
# the BASELINE OWNER's absolute paths, and the signed bundles verify
# self-consistently on ANY machine (readiness never reads live targets),
# so readiness alone cannot tell whose machine a baseline belongs to —
# the first real attestation is what fails. Path ownership is the tell.
fixture_local() {
  grep -q "\"filepath\": \"$REPO/$2" "$1" 2>/dev/null
}

probe_provision_rocq() {
  probe_pybb_venv || return 1
  fixture_local "$REPO/tests/fixtures/temp_control_rocq_model/asp_args.json" \
    "targets/temp-control-rocq/" || return 1
  wrapper_blessed "$WORKSPACE/bin/rocq" \
    "$REPO/tests/fixtures/temp_control_rocq_verification/asp_args.json" \
    "Claude_workspace/bin/rocq" || return 1
  wrapper_blessed "$WORKSPACE/bin/dune" \
    "$REPO/tests/fixtures/temp_control_rocq_verification/asp_args.json" \
    "Claude_workspace/bin/dune" || return 1
  driver_ready_quiet temp_control_rocq.py
}

do_provision_rocq() {
  echo "${DIM}(provisioning + blessing the rocq baselines — rocq compiles the
 model as part of the blessing lint)${RESET}"
  ( cd "$REPO" && "$REPO/.venv/bin/python" examples/temp_control_rocq.py \
      --provision --bless-model --bless-tools )
  driver_ready temp_control_rocq.py \
    || die "rocq readiness still FAILs after provisioning — see output above"
}

probe_provision_isolette() {
  [ "$SKIP_SIREUM" = 1 ] && return 0
  probe_pybb_venv || return 1
  fixture_local "$REPO/tests/fixtures/isolette_sysmlv2_rust_props/asp_args.json" \
    "targets/isolette-microkit/" || return 1
  wrapper_blessed "$WORKSPACE/bin/cargo-verus" \
    "$REPO/tests/fixtures/isolette_sysmlv2_rust_verus/asp_args.json" \
    "Claude_workspace/bin/cargo-verus" || return 1
  driver_ready_quiet isolette_rust.py --frontend sysml
}

do_provision_isolette() {
  [ "$SKIP_SIREUM" = 1 ] && return 0
  echo "${DIM}(provisioning + blessing the isolette baselines)${RESET}"
  ( cd "$REPO" && "$REPO/.venv/bin/python" examples/isolette_rust.py \
      --frontend sysml --provision --bless-props )
  driver_ready isolette_rust.py --frontend sysml \
    || die "isolette readiness still FAILs after provisioning — see output above"
}

# ── driver ──────────────────────────────────────────────────────────────────

main() {
  echo "${BOLD}pybb stack installer${RESET} — platform: $PLATFORM" \
       "($VERUS_PLAT / $SIREUM_PLAT), workspace: $WORKSPACE"
  if [ "$PLATFORM" = linux ]; then
    echo "${BOLD}WARNING:${RESET} Linux support is written to spec but UNTESTED —"
    echo "please report problems (and successes)."
  fi
  [ "$DRY_RUN" = 1 ] && echo "(dry run: probing only, executing nothing)"

  local n=0 started=0 fn
  for step in "${STEPS[@]}"; do
    n=$((n + 1))
    if [ -n "$ONLY" ] && [ "$step" != "$ONLY" ]; then continue; fi
    if [ -n "$FROM" ]; then
      [ "$step" = "$FROM" ] && started=1
      [ "$started" = 1 ] || continue
    fi
    banner "$n/${#STEPS[@]}" "$step"
    fn="${step//-/_}"
    if "probe_$fn"; then
      echo "already satisfied — skipping"
      continue
    fi
    if [ "$DRY_RUN" = 1 ]; then
      echo "would run (not currently satisfied)"
      continue
    fi
    CURRENT_STEP="$step"
    "do_$fn"
    "probe_$fn" || die "step '$step' ran but its probe still fails"
    echo "done."
  done
  CURRENT_STEP="(finished)"

  [ "$DRY_RUN" = 1 ] && { echo; echo "dry run complete."; return 0; }

  echo
  banner "✓" "install complete"
  if ! git -C "$REPO" diff --quiet -- tests/fixtures golden 2>/dev/null; then
    echo "Provisioning rewrote tracked baseline files (expected, local to"
    echo "this machine — do NOT commit unless you own the blessed baseline):"
    git -C "$REPO" status --short -- tests/fixtures golden | head -20
    echo "${DIM}(restore the maintainer baseline with:"
    echo "  git checkout -- tests/fixtures golden"
    echo " — readiness will then FAIL here until you re-provision)${RESET}"
  fi
  cat <<EOF

Next steps (from $REPO):

  Doctor / sanity check:
    scripts/check_install.sh            (add --ready to re-run the gates)

  Re-provision + re-bless (only needed again if a tool or model changes):
    .venv/bin/python examples/temp_control_rocq.py --provision --bless-model --bless-tools
    .venv/bin/python examples/isolette_rust.py --frontend sysml --provision --bless-props

  Quick unattended demo runs (no pauses, auto-resolve the decision beats):
    examples/demo_rocq.sh --fast --auto bless --no-vscode
    examples/demo_isolette.sh --fast --auto bless --no-vscode

  Full interactive arcs (the real demos — run in a terminal, ~30-60 min each;
  the first isolette run cold-builds the Verus crates and downloads their
  pinned dependencies, so its early scenes are slow once):
    examples/demo_rocq.sh               (8 scenes; --help for flags)
    examples/demo_isolette.sh           (10 scenes; --help for flags)
    ... or a subset:  examples/demo_rocq.sh --scenes "1 2 3"

  Docs: docs/INSTALL.md, docs/demo_rocq_script_summary.md,
        docs/demo_isolette_script_summary.md
EOF
}

main
