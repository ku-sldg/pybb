#!/usr/bin/env bash
# Local immudb for pybb's attestation ledger (docs/ledger_plan.md, decision 3).
#
#   scripts/immudb_dev.sh install     brew install + start the launchd service
#   scripts/immudb_dev.sh bootstrap   create database `pybb` and user `pybb`
#   scripts/immudb_dev.sh status      service state, version, databases
#   scripts/immudb_dev.sh rotate-admin NEWPASS
#                                     change the default admin password (do this
#                                     once; then export IMMUDB_ADMIN_PASSWORD)
#
# Environment:
#   PYBB_IMMUDB_USER       (default pybb)      the non-admin user pybb logs in as
#   PYBB_IMMUDB_PASSWORD   (required for bootstrap; 8-32 chars, upper+lower+digit+symbol)
#   IMMUDB_ADMIN_PASSWORD  (default immudb)    admin password used by bootstrap/status
#
# The service binds 0.0.0.0:3322 by default; this script leaves networking to
# Homebrew's service definition — for a shared instance see plan decision 3.
set -euo pipefail

PYBB_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYBB_ROOT}/.venv/bin/python"
[ -x "$PY" ] || PY=python3

cmd="${1:-status}"
case "$cmd" in
  install)
    command -v brew >/dev/null || { echo "Homebrew is required" >&2; exit 1; }
    brew list immudb >/dev/null 2>&1 || brew install immudb
    brew services start immudb
    echo "immudb service started; data under $(brew --prefix)/var/immudb"
    "$PY" -m pip show immudb-py >/dev/null 2>&1 || "$PY" -m pip install 'immudb-py>=1.5'
    ;;
  bootstrap)
    : "${PYBB_IMMUDB_PASSWORD:?set PYBB_IMMUDB_PASSWORD for the pybb user}"
    "$PY" -m pybb.attestation.ledger_immudb bootstrap
    ;;
  status)
    brew services info immudb 2>/dev/null || true
    immudb version 2>/dev/null | head -1 || echo "immudb binary not found"
    ;;
  rotate-admin)
    new="${2:?usage: immudb_dev.sh rotate-admin NEWPASS}"
    old="${IMMUDB_ADMIN_PASSWORD:-immudb}"
    "$PY" - "$old" "$new" <<'EOF'
import sys
from immudb import ImmudbClient
old, new = sys.argv[1], sys.argv[2]
c = ImmudbClient("127.0.0.1:3322"); c.login("immudb", old)
c.changePassword("immudb", new, old); c.logout()
print("admin password changed; export IMMUDB_ADMIN_PASSWORD accordingly")
EOF
    ;;
  *)
    sed -n '2,20p' "$0"; exit 2 ;;
esac
