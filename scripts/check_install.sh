#!/usr/bin/env bash
# check_install.sh — read-only doctor for the pybb demo stack.
# Verifies every component scripts/install.sh sets up, without changing
# anything. Exit 0 when all required checks pass.
#
#   --ready   also run both drivers' readiness gates (~30-60s each)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=versions.sh
. "$SCRIPT_DIR/versions.sh"

RUN_READY=0
case "${1:-}" in
  --ready) RUN_READY=1 ;;
  "") ;;
  -h|--help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "unknown flag: $1 (see --help)" >&2; exit 2 ;;
esac

export PATH="$HOME/.cargo/bin:$PATH"
FAILED=0
ok()   { printf '  ok    %s\n' "$1"; }
bad()  { printf '  FAIL  %s\n' "$1"; FAILED=1; }
skip() { printf '  skip  %s\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

PY="$REPO/.venv/bin/python"

echo "pybb stack doctor — platform: $PLATFORM, workspace: $WORKSPACE"
echo

echo "prerequisites:"
for c in git curl unzip opam rustup cargo; do
  have "$c" && ok "$c on PATH" || bad "$c missing from PATH"
done
if for c in python3.13 python3.12 python3.11 python3; do
     have "$c" && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' \
       2>/dev/null && break
   done; then ok "python >= 3.11"
elif [ -x "$PY" ] && "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
  skip "python >= 3.11 not on PATH (but .venv is already built — fine)"
else bad "no python >= 3.11 on PATH"; fi
if [ "$PLATFORM" = macos ]; then
  brew list zeromq >/dev/null 2>&1 && ok "zeromq (brew)" || bad "zeromq not installed (brew install zeromq)"
else
  pkg-config --exists libzmq 2>/dev/null && ok "libzmq (pkg-config)" || bad "libzmq missing (apt install libzmq3-dev)"
fi

echo "opam switch $OPAM_SWITCH:"
if opam switch list --short 2>/dev/null | grep -qx "$OPAM_SWITCH"; then
  ok "switch '$OPAM_SWITCH' exists"
  v="$("$HOME/.opam/$OPAM_SWITCH/bin/rocq" --version 2>/dev/null)"
  case "$v" in *"$ROCQ_VERSION"*) ok "rocq $ROCQ_VERSION" ;;
    *) bad "rocq missing or wrong version in ~/.opam/$OPAM_SWITCH/bin (want $ROCQ_VERSION)" ;; esac
  [ -x "$HOME/.opam/$OPAM_SWITCH/bin/dune" ] && ok "dune in switch" \
    || bad "dune missing from ~/.opam/$OPAM_SWITCH/bin"
else
  bad "opam switch '$OPAM_SWITCH' does not exist"
fi

echo "attestation stack:"
CVM_BIN="${CVM_BINARY:-$WORKSPACE/cvm/_build/default/theories/cvm}"
[ -x "$CVM_BIN" ] && ok "cvm binary ($CVM_BIN)" || bad "cvm binary missing ($CVM_BIN)"
ASP_DIR="${ASP_BIN:-$WORKSPACE/asp-libs/target/release}"
if [ -x "$ASP_DIR/hashfile" ] && [ -x "$ASP_DIR/sig" ]; then
  ok "asp-libs binaries ($ASP_DIR)"
else
  bad "asp-libs binaries missing ($ASP_DIR — cd asp-libs && make)"
fi
CET="${COPLAND_EVIDENCE_TOOLS:-$WORKSPACE/copland-evidence-tools/_build/default/theories/copland_evidence_tools}"
[ -x "$CET" ] && ok "copland-evidence-tools" \
  || skip "copland-evidence-tools absent (optional — summarizer degrades gracefully)"

echo "pinned repos:"
ref_is() {  # ref_is <dir> <branch-or-empty> [commit]
  [ -d "$1/.git" ] || return 1
  if [ -n "${3:-}" ]; then [ "$(git -C "$1" rev-parse HEAD 2>/dev/null)" = "$3" ]
  else [ "$(git -C "$1" rev-parse --abbrev-ref HEAD 2>/dev/null)" = "$2" ]; fi
}
ref_is "$WORKSPACE/cvm" "$CVM_BRANCH" && ok "cvm on $CVM_BRANCH" \
  || bad "cvm not on branch $CVM_BRANCH"
ref_is "$WORKSPACE/asp-libs" "$ASP_LIBS_BRANCH" && ok "asp-libs on $ASP_LIBS_BRANCH" \
  || bad "asp-libs not on branch $ASP_LIBS_BRANCH"
ref_is "$WORKSPACE/copland-evidence-tools" "" "$CET_COMMIT" \
  && ok "copland-evidence-tools at ${CET_COMMIT:0:9}" \
  || skip "copland-evidence-tools not at ${CET_COMMIT:0:9} (optional)"
ref_is "$WORKSPACE/sysml-aadl-libraries" "" "$SYSML_LIBS_COMMIT" \
  && ok "sysml-aadl-libraries at ${SYSML_LIBS_COMMIT:0:9}" \
  || bad "sysml-aadl-libraries not at pinned commit ${SYSML_LIBS_COMMIT:0:9} (isolette)"

echo "verus + rust:"
if [ -x "$VERUS_DIST_LINK/verus" ] \
   && "$VERUS_DIST_LINK/verus" --version 2>/dev/null | grep -q "$VERUS_VERSION"; then
  ok "verus $VERUS_VERSION via $VERUS_DIST_LINK"
else
  bad "verus $VERUS_VERSION not found via $VERUS_DIST_LINK"
fi
TOOLCHAIN_TOML="$REPO/targets/isolette-microkit/hamr/microkit/crates/thermostat_rt_mhs_mhs/rust-toolchain.toml"
if [ -f "$TOOLCHAIN_TOML" ]; then
  pinned="$(sed -n 's/^channel = "\(.*\)"/\1/p' "$TOOLCHAIN_TOML")"
  [ "$pinned" = "$RUST_NIGHTLY" ] && ok "rust nightly pin matches crates ($RUST_NIGHTLY)" \
    || bad "versions.sh RUST_NIGHTLY=$RUST_NIGHTLY but crates pin $pinned"
fi
if have rustup && rustup toolchain list 2>/dev/null | grep -q "$RUST_NIGHTLY"; then
  ok "rust $RUST_NIGHTLY installed"
else
  bad "rust $RUST_NIGHTLY not installed (rustup toolchain install $RUST_NIGHTLY ...)"
fi

echo "sireum:"
if [ -x "$SIREUM_HOME_DIR/bin/sireum" ]; then
  "$SIREUM_HOME_DIR/bin/sireum" --version 2>/dev/null | grep -q "$SIREUM_TAG" \
    && ok "sireum v$SIREUM_TAG at $SIREUM_HOME_DIR" \
    || bad "$SIREUM_HOME_DIR present but not v$SIREUM_TAG"
else
  skip "sireum absent (demo_isolette scenes 3/8 + its readiness gate need it)"
fi

echo "workspace wrappers ($WORKSPACE/bin):"
for w in rocq dune cargo-verus verus sireum; do
  [ -x "$WORKSPACE/bin/$w" ] && ok "$w present" || bad "$w missing or not executable"
done
# hash the attested wrappers against the blessed fixture goldens — the
# same gate the demos' --restore-tools applies
wrapper_golden() {  # wrapper_golden <wrapper-path> <fixture-asp_args.json> <suffix>
  [ -x "$PY" ] && [ -f "$1" ] && [ -f "$2" ] || return 2
  "$PY" - "$1" "$2" "$3" <<'PYEOF'
import base64, hashlib, json, sys
digest = base64.b64encode(
    hashlib.sha256(open(sys.argv[1], "rb").read()).digest()).decode()
args = json.load(open(sys.argv[2]))
golden = next((a["golden_b64"] for a in args.get("hashfile", {}).values()
               if a.get("filepath", "").endswith(sys.argv[3])), None)
sys.exit(0 if golden == digest else 1)
PYEOF
}
for spec in \
  "rocq:tests/fixtures/temp_control_rocq_verification/asp_args.json:Claude_workspace/bin/rocq" \
  "cargo-verus:tests/fixtures/isolette_sysmlv2_rust_verus/asp_args.json:Claude_workspace/bin/cargo-verus"
do
  w="${spec%%:*}"; rest="${spec#*:}"; fixture="${rest%%:*}"; suffix="${rest#*:}"
  wrapper_golden "$WORKSPACE/bin/$w" "$REPO/$fixture" "$suffix"
  case $? in
    0) ok "$w matches its blessed golden" ;;
    1) bad "$w does NOT match its blessed golden — re-bless (see docs/INSTALL.md) or --restore-tools" ;;
    *) skip "$w golden check (venv or fixture missing)" ;;
  esac
done

echo "pybb:"
if [ -x "$PY" ] && "$PY" -c 'import pybb, pydantic' 2>/dev/null; then
  ok ".venv imports pybb + pydantic"
else
  bad ".venv missing or broken (python3 -m venv .venv && .venv/bin/pip install -e '.[dev]')"
fi
if [ -d "$REPO/.demo.lock" ]; then
  pid="$(cat "$REPO/.demo.lock/pid" 2>/dev/null)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    skip "demo lock held by live pid $pid (a demo is running)"
  else
    bad "stale .demo.lock (no live pid) — rm -rf $REPO/.demo.lock"
  fi
else
  ok "no stale .demo.lock"
fi

if [ "$RUN_READY" = 1 ]; then
  echo "readiness gates:"
  ready() {
    out="$( (cd "$REPO" && "$PY" "examples/$1" "${@:2}" --ready) 2>&1 )"
    grep -q "readiness: PASS" <<<"$out"
  }
  if [ -x "$PY" ]; then
    ready temp_control_rocq.py && ok "rocq readiness PASS" \
      || bad "rocq readiness FAIL (run: .venv/bin/python examples/temp_control_rocq.py --ready)"
    if [ -x "$SIREUM_HOME_DIR/bin/sireum" ]; then
      ready isolette_rust.py --frontend sysml && ok "isolette readiness PASS" \
        || bad "isolette readiness FAIL (run: .venv/bin/python examples/isolette_rust.py --frontend sysml --ready)"
    else
      skip "isolette readiness (no sireum)"
    fi
  else
    skip "readiness gates (no venv)"
  fi
fi

echo
if [ "$FAILED" = 1 ]; then
  echo "RESULT: FAIL — fix the items above (scripts/install.sh re-runs idempotently)"
  exit 1
fi
echo "RESULT: ok"
