#!/usr/bin/env bash
#
# Full attestation tour: runs the isolette workflow, and — with a ladder
# flag — the gumbo (temp-control-jvm) three-tier workflow as well.
#
# This is a thin wrapper; the independent workflows live in:
#   ./examples/run_isolette_workflow.sh   (env check, provision, bundle, ladder)
#   ./examples/run_gumbo_workflow.sh      (three-tier ladder + semantic tier)
#
# Usage (flags map onto both workflows, preserving historic semantics):
#   ./examples/run_full_workflow.sh                    # isolette only, clean
#   ./examples/run_full_workflow.sh --three-tier       # + gumbo ladder, clean
#   ./examples/run_full_workflow.sh --tamper           # tamper demos (both, if
#                                                      # a ladder flag is set)
#   ./examples/run_full_workflow.sh --repair           # implies --three-tier
#   ./examples/run_full_workflow.sh --tamper-semantic  # implies --three-tier;
#                                                      # gumbo only
#   ./examples/run_full_workflow.sh --reprovision      # isolette golden refresh

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

TAMPER=false
REPROVISION=false
THREE_TIER=false
TAMPER_SEMANTIC=false
REPAIR=false
for arg in "$@"; do
  case "$arg" in
    --tamper)          TAMPER=true ;;
    --reprovision)     REPROVISION=true ;;
    --three-tier)      THREE_TIER=true ;;
    --tamper-semantic) TAMPER_SEMANTIC=true; THREE_TIER=true ;;
    --repair)          REPAIR=true; THREE_TIER=true ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done
if $TAMPER && $TAMPER_SEMANTIC; then
  echo "choose one of --tamper / --tamper-semantic" >&2; exit 2
fi

ISO_ARGS=()
$TAMPER && ISO_ARGS+=(--tamper)
$REPROVISION && ISO_ARGS+=(--reprovision)
$REPAIR && ISO_ARGS+=(--repair)
"$DIR/run_isolette_workflow.sh" "${ISO_ARGS[@]+"${ISO_ARGS[@]}"}"

if $THREE_TIER; then
  GUMBO_ARGS=()
  $TAMPER && GUMBO_ARGS+=(--tamper)
  $TAMPER_SEMANTIC && GUMBO_ARGS+=(--tamper-semantic)
  $REPAIR && GUMBO_ARGS+=(--repair)
  "$DIR/run_gumbo_workflow.sh" "${GUMBO_ARGS[@]+"${GUMBO_ARGS[@]}"}"
fi
