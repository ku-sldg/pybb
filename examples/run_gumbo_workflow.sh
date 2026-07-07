#!/usr/bin/env bash
#
# Gumbo (temp-control-jvm) attestation workflow: the three-tier escalation
# ladder on the blackboard.
#
#   tier 1  gumbo_l1          whole-file hashes          ~1s
#   tier 2  gumbo_l2          per-contract slices        ~1s   (on l1 fail)
#   tier 3  gumbo_validation  sireum tipe/logika/test    ~min  (on l2 fail)
#
# Protocol dirs live in cvm-mcp/protocol_dirs (provisioned by the dashboard).
#
# Usage:
#   ./examples/run_gumbo_workflow.sh                    # clean: tier 1 passes
#   ./examples/run_gumbo_workflow.sh --tamper           # temp-copy text tamper:
#                                                       # all tiers run, hypothesis
#                                                       # "modified yet still verifies"
#   ./examples/run_gumbo_workflow.sh --tamper-semantic  # flip a GumboX oracle
#                                                       # predicate in the REAL
#                                                       # project (backed up +
#                                                       # restored): all tiers FAIL
#   ./examples/run_gumbo_workflow.sh --repair           # with a tamper mode:
#                                                       # RepairKS golden restore,
#                                                       # re-attest (preempts tier 3)
#
# Paths overridable via env vars (WORKSPACE, PYBB).

set -euo pipefail

WORKSPACE="${WORKSPACE:-$HOME/Claude_workspace}"
PYBB="${PYBB:-$WORKSPACE/pybb}"
PYTHON="$PYBB/.venv/bin/python"

TAMPER=false
TAMPER_SEMANTIC=false
REPAIR=false
for arg in "$@"; do
  case "$arg" in
    --tamper)          TAMPER=true ;;
    --tamper-semantic) TAMPER_SEMANTIC=true ;;
    --repair)          REPAIR=true ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done
if $TAMPER && $TAMPER_SEMANTIC; then
  echo "choose one of --tamper / --tamper-semantic" >&2; exit 2
fi

banner() {
  echo
  echo "==============================================================="
  echo "  $1"
  echo "==============================================================="
}

# ── Step 0: environment check ─────────────────────────────────────────────────
banner "Step 0: environment check"
ok=true
for f in "$WORKSPACE/cvm/_build/default/theories/cvm" \
         "$WORKSPACE/asp-libs/target/release/hashfile" \
         "$WORKSPACE/temp-control-jvm" "$WORKSPACE/bin/sireum" "$PYTHON"; do
  if [ -e "$f" ]; then
    echo "  [ok]      $f"
  else
    echo "  [MISSING] $f"
    ok=false
  fi
done
$ok || { echo "Missing prerequisites — see pybb/attestation/README.md"; exit 1; }

# ── Step 1: the three-tier ladder ─────────────────────────────────────────────
banner "Step 1: three-tier ladder"
echo "  tier 1  gumbo_l1          whole-file hashes          ~1s"
echo "  tier 2  gumbo_l2          per-contract slices        ~1s   (on l1 fail)"
echo "  tier 3  gumbo_validation  sireum tipe/logika/test    ~min  (on l2 fail)"
echo
REPAIR_ARG=""
if $REPAIR; then
  REPAIR_ARG="--repair"
  echo "  RepairKS enabled: failing measured ranges are restored from"
  echo "  provisioned goldens, then re-attested (repair preempts tier 3)."
fi

if $TAMPER_SEMANTIC; then
  GUMBOX="$WORKSPACE/temp-control-jvm/slang/src/main/bridge/tc/TempControlSoftwareSystem/TempControlPeriodic_p_tcproc_tempControl_GumboX.scala"
  GUMBOX_BAK="$GUMBOX.pybb_backup"
  restore_gumbox() {
    [ -f "$GUMBOX_BAK" ] && mv -f "$GUMBOX_BAK" "$GUMBOX"
  }
  echo "  Semantic tamper: flipping FanCmd.Off -> FanCmd.On on line 119 of the"
  echo "  TempControl GumboX oracle (inside measured range 113-120), in the"
  echo "  REAL project. Text changes (tiers 1-2 fail) AND meaning changes"
  echo "  (tier 3: GumboX unit tests refute the inverted oracle)."
  echo "  Backing up the oracle; it will be restored on exit."
  echo
  cp "$GUMBOX" "$GUMBOX_BAK"
  trap restore_gumbox EXIT
  "$PYTHON" - "$GUMBOX" <<'EOF'
import sys
p = sys.argv[1]
lines = open(p).read().splitlines(keepends=True)
expected = "latestFanCmd == CoolingFan.FanCmd.Off &&"
assert expected in lines[118], f"line 119 changed upstream: {lines[118]!r}"
lines[118] = lines[118].replace("FanCmd.Off", "FanCmd.On")
open(p, "w").write("".join(lines))
EOF
  ( cd "$PYBB" && "$PYTHON" examples/gumbo_attestation.py --validate $REPAIR_ARG \
      2>/dev/null | sed 's/^/  /' ) || true
  echo
  echo "  Restoring the GumboX oracle from backup..."
  restore_gumbox
  trap - EXIT
  echo "  [ok] oracle restored"
elif $TAMPER; then
  echo "  Tampering a temp copy of the watched files."
  echo
  ( cd "$PYBB" && "$PYTHON" examples/gumbo_attestation.py --tamper --validate $REPAIR_ARG \
      2>/dev/null | sed 's/^/  /' )
else
  echo "  Clean run: tier 1 passes, so tiers 2 and 3 never fire."
  echo
  ( cd "$PYBB" && "$PYTHON" examples/gumbo_attestation.py --validate $REPAIR_ARG \
      2>/dev/null | sed 's/^/  /' )
fi

banner "Done"
echo "  The blackboard history above is the audit trail; the hypothesis is"
echo "  the trust decision. See pybb/attestation/README.md for details."
