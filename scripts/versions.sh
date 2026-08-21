# versions.sh — pinned versions + platform detection shared by
# scripts/install.sh and scripts/check_install.sh. Source, don't run.
#
# These pins are load-bearing: tool bytes are hashed into the attested
# baselines, and the isolette crates pin the matching Rust nightly and
# Verus crate versions. Bump them together, then re-provision/re-bless.

VERUS_VERSION="0.2026.01.23.1650a05"
SIREUM_TAG="4.20260720.6a05e505"
RUST_NIGHTLY="nightly-2026-01-25"
SYSML_LIBS_COMMIT="9016cbcceefa92f0068e1811923704dd261d15f1"
CVM_BRANCH="fix/explicit-stdin-flag"
ASP_LIBS_BRANCH="hamr-asps"
# the req-file-input feature branch was merged upstream (PR #2) and
# deleted — pin the merge commit on main
CET_COMMIT="9ac916b40e6eb59fb64f5b9dc7790002e3a8e362"
# The switch NAME must be exactly "5.2": the rocq/dune wrappers and
# examples/rocq_workflow.py hardcode ~/.opam/5.2/bin.
OPAM_SWITCH="5.2"
OCAML_COMPILER="ocaml-base-compiler.5.2.0"
ROCQ_VERSION="9.0.1"

CVM_URL="https://github.com/ku-sldg/cvm.git"
ASP_LIBS_URL="https://github.com/ku-sldg/asp-libs.git"
CET_URL="https://github.com/ku-sldg/copland-evidence-tools.git"
SYSML_LIBS_URL="https://github.com/santoslab/sysml-aadl-libraries.git"
KU_SLDG_OPAM_REPO="https://github.com/ku-sldg/opam-repo.git"

# out_has <pattern> <cmd...> — run cmd, test its output for <pattern>.
# Captures output FIRST: a bare `cmd | grep -q` under pipefail can fail
# on a successful match when grep's early exit SIGPIPEs the producer
# (timing-dependent — passed on macOS, failed on Linux CI).
out_has() {
  local pattern="$1" out; shift
  out="$("$@" 2>/dev/null)" || true
  grep -q -- "$pattern" <<<"$out"
}

out_has_line() {  # same, but exact whole-line match (grep -x)
  local pattern="$1" out; shift
  out="$("$@" 2>/dev/null)" || true
  grep -qx -- "$pattern" <<<"$out"
}

# Everything except the pybb repo itself hangs off this fixed layout
# (Path.home()-derived constants throughout pybb/attestation and the
# example drivers).
WORKSPACE="$HOME/Claude_workspace"
SIREUM_HOME_DIR="$HOME/Applications/Sireum"

case "$(uname -s)/$(uname -m)" in
  Darwin/arm64)
    PLATFORM=macos
    VERUS_PLAT=arm64-macos
    SIREUM_PLAT=mac-arm64
    ;;
  Linux/x86_64)
    PLATFORM=linux
    VERUS_PLAT=x86-linux
    SIREUM_PLAT=linux-amd64
    ;;
  *)
    echo "unsupported platform: $(uname -s)/$(uname -m)" >&2
    echo "(supported: macOS arm64, Linux x86_64)" >&2
    exit 2
    ;;
esac

VERUS_DIST_DIR="$WORKSPACE/verus-$VERUS_PLAT"   # unpacked release
VERUS_DIST_LINK="$WORKSPACE/verus-dist"          # platform-neutral symlink
