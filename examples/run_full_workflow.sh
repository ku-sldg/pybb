#!/usr/bin/env bash
#
# Full HAMR attestation workflow: environment check -> provisioning (only if
# needed) -> blackboard attestation of the isolette contract slices via the
# rodeo transport.
#
# Usage:
#   ./examples/run_full_workflow.sh                # provision if needed, clean run
#   ./examples/run_full_workflow.sh --tamper       # + tamper/fail/restore demo
#   ./examples/run_full_workflow.sh --reprovision  # force fresh golden evidence
#                                                  # (a trust decision: declares the
#                                                  #  CURRENT tree known-good)
#
# All paths can be overridden via environment variables (see below).

set -euo pipefail

WORKSPACE="${WORKSPACE:-$HOME/Claude_workspace}"
CVM_BINARY="${CVM_BINARY:-$WORKSPACE/cvm/_build/default/theories/cvm}"
ASP_BIN="${ASP_BIN:-$WORKSPACE/asp-libs/target/release}"
RUST_AM_CLIENTS="${RUST_AM_CLIENTS:-$WORKSPACE/rust-am-clients}"
RODEO="$RUST_AM_CLIENTS/target/release/rust-rodeo-client"
INSPECTA="${INSPECTA:-$WORKSPACE/INSPECTA-models}"
ROOT="$INSPECTA/isolette/hamr/microkit/attestation"
PYBB="${PYBB:-$WORKSPACE/pybb}"
PYTHON="$PYBB/.venv/bin/python"

TAMPER=false
REPROVISION=false
for arg in "$@"; do
  case "$arg" in
    --tamper)      TAMPER=true ;;
    --reprovision) REPROVISION=true ;;
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
for f in "$CVM_BINARY" "$RODEO" "$ASP_BIN/hamr_readfile_range_many" \
         "$ROOT/aadl_attestation_report.json" "$PYTHON"; do
  if [ -e "$f" ]; then
    echo "  [ok]      $f"
  else
    echo "  [MISSING] $f"
    ok=false
  fi
done
$ok || { echo "Missing prerequisites — see pybb/attestation/README.md"; exit 1; }

# ── Step 1: provisioning (out-of-band trust decision) ─────────────────────────
banner "Step 1: provisioning"
if [ -f "$ROOT/hamr_maestro_term.json" ] && \
   [ -f "$ROOT/hamr_maestro_golden_evidence.json" ] && ! $REPROVISION; then
  echo "  Already provisioned (term + golden evidence present) — skipping."
  echo "  Use --reprovision to re-declare the current tree known-good."
else
  echo "  Generating term and golden evidence from the attestation report..."
  ( cd "$RUST_AM_CLIENTS" && ASP_BIN="$ASP_BIN" "$RODEO" \
      --cvm-filepath "$CVM_BINARY" \
      --hamr-report-filepath "$ROOT/aadl_attestation_report.json" \
      --manifest-filepath testing/manifests/Manifest_P0.json \
      --session-filepath rodeo_configs/sessions/session_union.json \
      --provisioned-evidence-filepath "$ROOT/hamr_maestro_golden_evidence.json" \
      2>&1 | grep -v '^{' | sed 's/^/  /' ) || { echo "  provisioning FAILED"; exit 1; }
fi
echo "  Provisioned artifacts:"
ls -la "$ROOT"/hamr_maestro_*.json | sed 's/^/    /'

# ── Step 2: blackboard attestation (clean or tampered) ────────────────────────
MONITOR="$INSPECTA/isolette/aadl/aadl/packages/Monitor.aadl"

restore_monitor() {
  git -C "$INSPECTA" checkout --quiet -- \
    isolette/aadl/aadl/packages/Monitor.aadl 2>/dev/null || true
}

if $TAMPER; then
  banner "Step 2a: TAMPERED attestation run (expect FAIL)"
  trap restore_monitor EXIT
  echo "  Corrupting line 192 of Monitor.aadl (inside a measured GUMBO slice)..."
  "$PYTHON" - "$MONITOR" <<'EOF'
import sys
p = sys.argv[1]
lines = open(p).read().splitlines(keepends=True)
lines[191] = lines[191].rstrip("\n") + " -- TAMPERED\n"
open(p, "w").write("".join(lines))
EOF
  if ( cd "$PYBB" && "$PYTHON" examples/isolette_attestation.py 2>/dev/null | sed 's/^/  /' ); then
    echo "  NOTE: script exit reflects the demo run, not the verdict — read the hypothesis above."
  fi
  echo
  echo "  Restoring Monitor.aadl from git..."
  restore_monitor
  trap - EXIT
  git -C "$INSPECTA" diff --quiet -- isolette/aadl/aadl/packages/Monitor.aadl \
    && echo "  [ok] tree restored"

  banner "Step 2b: clean attestation run after restore (expect PASS)"
else
  banner "Step 2: blackboard attestation run (expect PASS)"
fi

( cd "$PYBB" && "$PYTHON" examples/isolette_attestation.py 2>/dev/null | sed 's/^/  /' )

banner "Done"
echo "  The blackboard history above is the audit trail; the hypothesis is the"
echo "  trust decision. See pybb/attestation/README.md for the gumbo (CVM"
echo "  transport) demos and the test suite."
