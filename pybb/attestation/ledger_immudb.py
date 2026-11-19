"""
immudb backend for the attestation ledger (docs/ledger_plan.md, sections A,
B.3, H, K; decision 3).

Keys and canonical values are exactly those of `ledger.py`; a batch goes in
with one `ExecAll` (atomic) carrying a `keyMustNotExist` precondition for
every `bundle/` key it writes, so the uniqueness rule (one bundle per nonce)
is enforced by the server as well as by pybb. Reads use `verifiedGet` with a
persistent client state so the client checks the server's inclusion and
consistency proofs itself. A SQL mirror table, `attestation_records`, is
written after the KV batch for external `immuclient`/SQL readers; it is a
convenience view (each row carries the KV value's `content_sha256`) and
`rebuild_mirror()` regenerates it from the KV history, so the KV side alone
is the ledger.

Bootstrap (database + non-admin user) is `ImmudbLedger.bootstrap(...)`,
also exposed as `python -m pybb.attestation.ledger_immudb bootstrap` for
`scripts/immudb_dev.sh` and the test fixture.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .ledger import (
    DuplicateNonceError,
    Ledger,
    LedgerConfig,
    LedgerError,
    Receipt,
    key_for,
    parse_record,
)

# v2 prefixes first; the v1 prefixes keep a v1 database readable through `history()`
RECORD_PREFIXES = ("bundle/", "judged_by/", "mirror/", "restore/",
                   "nonce/", "evidence/", "verdict/", "locator/", "appraisal/")

MIRROR_TABLE = "attestation_records"
# immudb caps indexed key sizes: the longest ledger key is ~140 bytes
# (`judged_by/<64 hex>/<64 hex>`), so the primary key is VARCHAR[160]
MIRROR_DDL = f"""CREATE TABLE IF NOT EXISTS {MIRROR_TABLE} (
  key VARCHAR[160], kind VARCHAR[16], role VARCHAR[16], protocol_id VARCHAR[96],
  input_bid VARCHAR[64], appraisal_kind VARCHAR[32], passed BOOLEAN,
  assurance VARCHAR[16], freshness VARCHAR[16], blob_sha256 VARCHAR[64],
  created_at VARCHAR[32], content_sha256 VARCHAR[64], PRIMARY KEY key)"""
MIRROR_INDEXES = (
    f"CREATE INDEX IF NOT EXISTS ON {MIRROR_TABLE}(input_bid)",
    f"CREATE INDEX IF NOT EXISTS ON {MIRROR_TABLE}(protocol_id, created_at)",
)
_COLS = ("key", "kind", "role", "protocol_id", "input_bid", "appraisal_kind", "passed",
         "assurance", "freshness", "blob_sha256", "created_at", "content_sha256")
# two statements: immudb-py cannot bind a NULL parameter, so records without
# a verdict omit the `passed` column (NULL by omission)
MIRROR_UPSERT = (f"UPSERT INTO {MIRROR_TABLE}({', '.join(_COLS)}) VALUES "
                 f"({', '.join('@' + c for c in _COLS)})")
_COLS_NO_VERDICT = tuple(c for c in _COLS if c != "passed")
MIRROR_UPSERT_NO_VERDICT = (f"UPSERT INTO {MIRROR_TABLE}({', '.join(_COLS_NO_VERDICT)}) VALUES "
                            f"({', '.join('@' + c for c in _COLS_NO_VERDICT)})")


def _client_module():
    try:
        import immudb  # noqa: F401
        from immudb import ImmudbClient
        from immudb.datatypes import KeyValue
        from immudb.rootService import PersistentRootService
    except ImportError as e:  # pragma: no cover
        raise LedgerError("immudb-py is not installed (pip install 'pybb[ledger]')") from e
    return ImmudbClient, KeyValue, PersistentRootService


def mirror_row(key: str, rec: Any) -> Dict[str, Any]:
    """The SQL mirror's view of one record (v2 columns; v1 records map onto
    the same columns as far as they can)."""
    d = rec.to_dict()
    passed: Optional[bool] = None
    role = d.get("role") or ""
    input_bid = ""
    appraisal_kind = ""
    if rec.kind == "bundle" and d.get("verdict"):
        passed = d["verdict"].get("passed")
    if rec.kind == "bundle" and d.get("inputs"):
        input_bid = d["inputs"][0].get("bid") or ""
        appraisal_kind = d.get("appraisal_kind") or ""
    if rec.kind == "judged_by":
        input_bid = d.get("bid") or ""
    if rec.kind in ("verdict", "appraisal"):  # v1
        passed = d.get("passed")
    blob = d.get("blob_sha256") or (d.get("blob") or {}).get("blob_sha256") or ""
    return {
        "key": key, "kind": rec.kind, "role": role,
        "protocol_id": d.get("protocol_id") or "", "input_bid": input_bid,
        "appraisal_kind": appraisal_kind, "passed": passed,
        "assurance": d.get("assurance") or d.get("evidence_assurance") or "",
        "freshness": d.get("freshness") or "", "blob_sha256": blob,
        "created_at": d.get("created_at") or "", "content_sha256": rec.content_sha256(),
    }


class ImmudbLedger(Ledger):
    """The ledger on an immudb database (plan decision 3: local Homebrew
    service for dev/demo, ephemeral server per test session)."""

    def __init__(self, config: LedgerConfig, client: Any = None, login: bool = True):
        self.config = config
        ImmudbClient, KeyValue, PersistentRootService = _client_module()
        self._KeyValue = KeyValue
        if client is None:
            state_dir = Path(os.path.expanduser(config.state_dir))
            state_dir.mkdir(parents=True, exist_ok=True)
            state_file = state_dir / f"immudb_state_{config.host}_{config.port}_{config.db}"
            client = ImmudbClient(f"{config.host}:{config.port}",
                                  rs=PersistentRootService(str(state_file)))
        self.client = client
        if login:
            if not config.password:
                raise LedgerError("immudb password not set (PYBB_IMMUDB_PASSWORD or LedgerConfig.password)")
            try:
                self.client.login(config.user, config.password, database=config.db.encode())
            except Exception as e:
                raise LedgerError(f"immudb login failed for {config.user}@{config.db}: {e}") from e
        self._ensure_mirror()

    # -- bootstrap ------------------------------------------------------------

    @classmethod
    def bootstrap(cls, config: LedgerConfig, admin_password: str = "immudb",
                  admin_user: str = "immudb") -> None:
        """Create the database and a read/write non-admin user (idempotent)."""
        ImmudbClient, _KeyValue, _Prs = _client_module()
        from immudb.datatypes import ReadWrite

        admin = ImmudbClient(f"{config.host}:{config.port}")
        admin.login(admin_user, admin_password)
        dbs = {d.databaseName if hasattr(d, "databaseName") else str(d) for d in admin.databaseList()}
        if config.db not in dbs:
            admin.createDatabase(config.db.encode())
        try:
            admin.createUser(config.user, config.password, ReadWrite, config.db.encode())
        except Exception as e:  # already exists: grant on the (possibly new) database instead
            if "already" not in str(e).lower() and "exists" not in str(e).lower():
                raise
            from immudb.grpc import schema_pb2

            admin.changePermission(schema_pb2.GRANT, config.user, config.db, ReadWrite)
        admin.logout()

    # -- SQL mirror -----------------------------------------------------------

    def _ensure_mirror(self) -> None:
        try:
            self.client.sqlExec(MIRROR_DDL)
            for stmt in MIRROR_INDEXES:
                self.client.sqlExec(stmt)
        except Exception as e:
            raise LedgerError(f"could not create the SQL mirror table: {e}") from e

    def _mirror(self, rows: List[Dict[str, Any]]) -> None:
        for row in rows:
            if row.get("passed") is None:
                self.client.sqlExec(MIRROR_UPSERT_NO_VERDICT, {k: v for k, v in row.items() if k != "passed"})
            else:
                self.client.sqlExec(MIRROR_UPSERT, row)

    def rebuild_mirror(self) -> int:
        """Regenerate every mirror row from the KV history; returns the count."""
        n = 0
        for _tx, key, rec in self.history():
            self._mirror([mirror_row(key, rec)])
            n += 1
        return n

    def mirror_query(self, sql: str, params: Optional[dict] = None) -> list:
        return self.client.sqlQuery(sql, params or {})

    # -- Ledger ---------------------------------------------------------------

    def exists(self, key: str) -> bool:
        try:
            return key.encode() in self.client.getAll([key.encode()])
        except Exception:
            return False

    def get_record(self, key: str) -> Optional[Any]:
        try:
            resp = self.client.verifiedGet(key.encode())
        except Exception:
            return None
        if not getattr(resp, "verified", True):
            raise LedgerError(f"verifiedGet of {key}: proof did not verify")
        return parse_record(json.loads(resp.value))

    def tx_of(self, key: str) -> Optional[int]:
        try:
            return int(self.client.verifiedGet(key.encode()).id)
        except Exception:
            return None

    def _exec_all(self, keys: List[str], records: List[Any]) -> int:
        """One atomic ExecAll. Every non-challenge `bundle/` key carries a
        `keyMustNotExist` precondition (plan K.3): immudb-py 1.5 does not
        expose preconditions, so the request is built on the stub directly."""
        from immudb.grpc import schema_pb2

        ops = [schema_pb2.Op(kv=schema_pb2.KeyValue(key=k.encode(), value=r.canonical()))
               for k, r in zip(keys, records)]
        pre = [schema_pb2.Precondition(keyMustNotExist=schema_pb2.Precondition.KeyMustNotExistPrecondition(key=k.encode()))
               for k, r in zip(keys, records)
               if r.kind == "bundle" and getattr(r, "role", None) != "challenge"]
        req = schema_pb2.ExecAllRequest(Operations=ops, noWait=False, preconditions=pre)
        header = self.client._stub.ExecAll(req)
        return int(header.id)

    def _write_batch(self, records: List[Any]) -> Receipt:
        if not records:
            raise LedgerError("empty batch")
        keys = [key_for(r) for r in records]
        try:
            tx = self._exec_all(keys, records)
        except Exception as e:
            if "precondition" in str(e).lower():
                raise DuplicateNonceError(f"immudb refused the batch: a bundle key already exists ({e})") from e
            raise LedgerError(f"immudb ExecAll failed: {e}") from e
        # the client-side proof check: the first key of the batch must verify
        # against the persisted state (which this call advances)
        verified = False
        try:
            resp = self.client.verifiedGet(keys[0].encode())
            verified = bool(getattr(resp, "verified", True)) and int(resp.id) == tx
        except Exception as e:
            raise LedgerError(f"post-write verification failed: {e}") from e
        # mirror rows are a derived view; a failure here never undoes the KV tx
        try:
            self._mirror([mirror_row(k, r) for k, r in zip(keys, records)])
        except Exception as e:
            sys.stderr.write(f"[ledger] SQL mirror write failed (KV tx {tx} stands): {e}\n")
        return Receipt(tx=tx, keys=keys, verified=verified)

    def history(self) -> Iterator[Tuple[int, str, Any]]:
        """Every record in tx order, reading each tx's keys and the value as
        of that tx (verified). SQL-internal entries are skipped."""
        last = int(self.client.currentState().txId)
        for tx in range(1, last + 1):
            try:
                keys = self.client.txById(tx) or []  # immudb-py: entry keys, prefix stripped
            except Exception:
                continue
            for key in keys:
                key = bytes(key)
                try:
                    k = key.decode("utf-8")
                except UnicodeDecodeError:
                    continue  # SQL-internal entries carry binary keys
                if not k.startswith(RECORD_PREFIXES):
                    continue
                try:
                    resp = self.client.verifiedGetAt(key, atTx=tx)
                except Exception:
                    continue
                yield tx, k, parse_record(json.loads(resp.value))

    def scan_prefix(self, prefix: str) -> Dict[str, Any]:
        """Latest record per key under `prefix` (a real server-side scan)."""
        out: Dict[str, Any] = {}
        try:
            found = self.client.scan(b"", prefix.encode(), False, 1000)
        except Exception:
            return out
        for k, v in found.items():
            out[k.decode()] = parse_record(json.loads(v))
        return out

    def db_name(self) -> str:
        return self.config.db

    def state(self) -> dict:
        """The server's current state for the evidence-repo mirror (plan H)."""
        st = self.client.currentState()
        return {"kind": "immudb", "db": self.config.db, "tx_id": int(st.txId),
                "tx_hash_hex": bytes(st.txHash).hex()}


def _main(argv: List[str]) -> int:
    if len(argv) >= 1 and argv[0] == "bootstrap":
        cfg = LedgerConfig()
        admin_pw = os.environ.get("IMMUDB_ADMIN_PASSWORD", "immudb")
        ImmudbLedger.bootstrap(cfg, admin_password=admin_pw)
        print(f"bootstrapped database '{cfg.db}' and user '{cfg.user}' on {cfg.host}:{cfg.port}")
        return 0
    print("usage: python -m pybb.attestation.ledger_immudb bootstrap", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
