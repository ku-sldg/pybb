#!/usr/bin/env bash
#
# Isolette attestation workflow (INSPECTA-models, HAMR attestation report):
#   Step 0  environment check
#   Step 1  provisioning of the rodeo attestation root (only if needed)
#   Step 2  bundle attestation via the rodeo transport
#   Step 3  l1 -> l2 escalation ladder via the report-guided cvm-mcp
#           protocol dirs (CVM transport)
#
# Usage:
#   ./examples/run_isolette_workflow.sh                # clean runs
#   ./examples/run_isolette_workflow.sh --tamper       # bundle: tamper real
#                                                      # Monitor.aadl + git
#                                                      # restore; ladder: tamper
#                                                      # a temp copy (path_map)
#   ./examples/run_isolette_workflow.sh --repair       # ladder: RepairKS golden
#                                                      # restore + re-attest
#   ./examples/run_isolette_workflow.sh --reprovision  # force fresh golden
#                                                      # evidence (trust decision)
#
# All paths overridable via env vars (WORKSPACE, CVM_BINARY, ASP_BIN,
# RUST_AM_CLIENTS, INSPECTA, CVM_MCP, PYBB).

set -euo pipefail

WORKSPACE="${WORKSPACE:-$HOME/Claude_workspace}"
CVM_BINARY="${CVM_BINARY:-$WORKSPACE/cvm/_build/default/theories/cvm}"
ASP_BIN="${ASP_BIN:-$WORKSPACE/asp-libs/target/release}"
RUST_AM_CLIENTS="${RUST_AM_CLIENTS:-$WORKSPACE/rust-am-clients}"
RODEO="$RUST_AM_CLIENTS/target/release/rust-rodeo-client"
INSPECTA="${INSPECTA:-$WORKSPACE/INSPECTA-models}"
ROOT="$INSPECTA/isolette/hamr/microkit/attestation"
CVM_MCP="${CVM_MCP:-$WORKSPACE/cvm-mcp}"
PYBB="${PYBB:-$WORKSPACE/pybb}"
PYTHON="$PYBB/.venv/bin/python"

TAMPER=false
REPROVISION=false
REPAIR=false
for arg in "$@"; do
  case "$arg" in
    --tamper)      TAMPER=true ;;
    --reprovision) REPROVISION=true ;;
    --repair)      REPAIR=true ;;
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
banner "Step 1: provisioning (rodeo attestation root)"
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

# ── Step 2: bundle attestation via rodeo transport ────────────────────────────
restore_monitor() {
  git -C "$INSPECTA" checkout --quiet -- \
    isolette/aadl/aadl/packages/Monitor.aadl 2>/dev/null || true
}

if $TAMPER; then
  banner "Step 2a: TAMPERED bundle run, rodeo transport (expect FAIL)"
  trap restore_monitor EXIT
  echo "  Corrupting line 192 of Monitor.aadl (inside a measured GUMBO slice)..."
  "$PYTHON" - "$INSPECTA/isolette/aadl/aadl/packages/Monitor.aadl" <<'EOF'
import sys
p = sys.argv[1]
lines = open(p).read().splitlines(keepends=True)
lines[191] = lines[191].rstrip("\n") + " -- TAMPERED\n"
open(p, "w").write("".join(lines))
EOF
  ( cd "$PYBB" && "$PYTHON" examples/isolette_attestation.py 2>/dev/null | sed 's/^/  /' ) || true
  echo
  echo "  Restoring Monitor.aadl from git..."
  restore_monitor
  trap - EXIT
  git -C "$INSPECTA" diff --quiet -- isolette/aadl/aadl/packages/Monitor.aadl \
    && echo "  [ok] tree restored"

  banner "Step 2b: clean bundle run after restore (expect PASS)"
else
  banner "Step 2: bundle attestation, rodeo transport (expect PASS)"
fi

( cd "$PYBB" && "$PYTHON" examples/isolette_attestation.py 2>/dev/null | sed 's/^/  /' )

# ── Step 3: l1 -> l2 ladder via report-guided cvm-mcp protocol dirs ───────────
banner "Step 3: isolette ladder (report-guided provisioning, CVM transport)"
if [ ! -f "$CVM_MCP/protocol_dirs/isolette_l2/asp_args.json" ]; then
  echo "  [MISSING] $CVM_MCP/protocol_dirs/isolette_l2 — generate with"
  echo "  cvm-mcp/hamr_report_protocols.py and provision via the dashboard."
  exit 1
fi
echo "  isolette_l1 (13 file hashes) -> isolette_l2 (85 contract slices)"
echo "  Protocol dirs generated from the HAMR attestation report;"
echo "  goldens provisioned by the cvm-mcp dashboard flow."
echo
ISO_ARGS=""
if $TAMPER; then
  ISO_ARGS="--tamper"
  echo "  Tampering a temp copy of a measured guarantee clause."
fi
if $REPAIR; then
  ISO_ARGS="$ISO_ARGS --repair"
  echo "  RepairKS enabled: golden restore + re-attestation."
fi
echo
( cd "$PYBB" && "$PYTHON" examples/isolette_ladder_attestation.py \
    --protocols-root "$CVM_MCP/protocol_dirs" $ISO_ARGS \
    2>/dev/null | sed 's/^/  /' )

banner "Done"
echo "  The blackboard history above is the audit trail; the hypothesis is"
echo "  the trust decision. See pybb/attestation/README.md for details."
