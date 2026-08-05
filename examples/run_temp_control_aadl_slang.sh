#!/usr/bin/env bash
#
# Gumbo (temp-control-jvm) attestation workflow: the outcome-routed decision
# tree on the blackboard.
#
#   eval    temp_control_aadl_slang_l1a+l1b     hashes + contract blocks          ~1s
#   on pass temp_control_aadl_slang_validation  sireum tipe/logika/test    ~min  (--validate)
#   on fail temp_control_aadl_slang_l2          per-contract slices        ~1s
#
# The chosen tier's pass ends the run in good standing; its failure moves
# the entry to the escalate segment with that tier's failure report.
#
# Protocol dirs live in tests/fixtures (provisioned by the cvm-mcp dashboard).
#
# Usage:
#   ./examples/run_temp_control_aadl_slang.sh              # clean: l1 passes, done (~1s)
#   ./examples/run_temp_control_aadl_slang.sh --validate   # clean: l1 pass is provisional,
#                                                 # sireum confirmation (~min)
#   ./examples/run_temp_control_aadl_slang.sh --tamper     # live-tree tamper: l1 fails,
#                                                 # l2 attributes the contract,
#                                                 # entry escalates with report;
#                                                 # snapshot restores the tree
#
# Paths overridable via env vars (WORKSPACE, PYBB).

set -euo pipefail

WORKSPACE="${WORKSPACE:-$HOME/Claude_workspace}"
PYBB="${PYBB:-$WORKSPACE/pybb}"
PYTHON="$PYBB/.venv/bin/python"

TAMPER=false
VALIDATE=false
for arg in "$@"; do
  case "$arg" in
    --tamper)   TAMPER=true ;;
    --validate) VALIDATE=true ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

banner() {
  echo
  echo "==============================================================="
  echo "  $1"
  echo "==============================================================="
}

# ── Step 0: environment check ─────────────────────────────────────────────────
banner "Step 0: environment check"
ok=true
checks=("$WORKSPACE/cvm/_build/default/theories/cvm"
        "$WORKSPACE/asp-libs/target/release/hashfile"
        "$WORKSPACE/temp-control-jvm" "$PYTHON")
$VALIDATE && checks+=("$WORKSPACE/bin/sireum")
for f in "${checks[@]}"; do
  if [ -e "$f" ]; then
    echo "  [ok]      $f"
  else
    echo "  [MISSING] $f"
    ok=false
  fi
done
$ok || { echo "Missing prerequisites — see pybb/attestation/README.md"; exit 1; }

# ── Step 1: the decision tree ─────────────────────────────────────────────────
banner "Step 1: outcome-routed attestation"
ARGS=""
if $VALIDATE; then
  ARGS="--validate"
  echo "  Confirmation tier enabled: a passing l1 is provisional until the"
  echo "  live Sireum tools concur (takes minutes)."
fi
if $TAMPER; then
  ARGS="$ARGS --tamper"
  echo "  Tampering the live tree (clean snapshot restores it after): l1 fails,"
  echo "  l2 attributes the contract, and the entry escalates with the l2 report."
else
  echo "  Clean run against the provisioned tree."
fi
echo
( cd "$PYBB" && "$PYTHON" examples/temp_control_aadl_slang.py $ARGS \
    2>/dev/null | sed 's/^/  /' )

banner "Done"
echo "  The blackboard history above is the audit trail; the trust summary"
echo "  is the decision. See pybb/attestation/README.md for details."
