"""
immudb backend for the attestation ledger (docs/ledger_plan.md, sections A,
B.3, H; decision 3).

Keys and canonical values are exactly those of `ledger.py`; a run's records
go in with one `execAll` (atomic), reads use `verifiedGet` with a persistent
client state so the client checks the server's inclusion and consistency
proofs itself. A SQL mirror table, `attestation_records`, is written after
the KV batch for external `immuclient`/SQL readers; it is a convenience view
(each row carries the KV value's `content_sha256`) and `rebuild_mirror()`
regenerates it from the KV history, so the KV side alone is the ledger.

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
    Ledger,
    LedgerConfig,
    LedgerError,
    LedgerRecord,
    Receipt,
    RunRecords,
    AppraisalRecord,
    EvidenceRecord,
    LocatorRecord,
    NonceRecord,
    VerdictRecord,
    key_for,
    parse_record,
    sha256_hex,
)

RECORD_PREFIXES = ("nonce/", "evidence/", "verdict/", "locator/", "appraisal/", "bundle/", "restore/")

MIRROR_TABLE = "attestation_records"
# immudb caps indexed key sizes: the longest ledger key is ~80 bytes
# (`appraisal/<64 hex>/<seq>`), so the primary key is VARCHAR[128]
MIRROR_DDL = f"""CREATE TABLE IF NOT EXISTS {MIRROR_TABLE} (
  key VARCHAR[128], kind VARCHAR[16], nid VARCHAR[64], protocol_id VARCHAR[96],
  passed BOOLEAN, assurance VARCHAR[16], freshness VARCHAR[16], blob_sha256 VARCHAR[64],
  created_at VARCHAR[32], content_sha256 VARCHAR[64], PRIMARY KEY key)"""
MIRROR_INDEXES = (
    f"CREATE INDEX IF NOT EXISTS ON {MIRROR_TABLE}(nid)",
    f"CREATE INDEX IF NOT EXISTS ON {MIRROR_TABLE}(protocol_id, created_at)",
)
# two statements: immudb-py cannot bind a NULL parameter, so records without
# a verdict omit the `passed` column (NULL by omission)
MIRROR_UPSERT = (f"UPSERT INTO {MIRROR_TABLE}(key, kind, nid, protocol_id, passed, assurance, "
                 f"freshness, blob_sha256, created_at, content_sha256) VALUES "
                 f"(@key, @kind, @nid, @protocol_id, @passed, @assurance, @freshness, "
                 f"@blob_sha256, @created_at, @content_sha256)")
MIRROR_UPSERT_NO_VERDICT = (f"UPSERT INTO {MIRROR_TABLE}(key, kind, nid, protocol_id, assurance, "
                            f"freshness, blob_sha256, created_at, content_sha256) VALUES "
                            f"(@key, @kind, @nid, @protocol_id, @assurance, @freshness, "
                            f"@blob_sha256, @created_at, @content_sha256)")


def _client_module():
    try:
        import immudb  # noqa: F401
        from immudb import ImmudbClient
        from immudb.datatypes import KeyValue
        from immudb.rootService import PersistentRootService
    except ImportError as e:  # pragma: no cover
        raise LedgerError("immudb-py is not installed (pip install 'pybb[ledger]')") from e
    return ImmudbClient, KeyValue, PersistentRootService


def mirror_row(key: str, rec: LedgerRecord) -> Dict[str, Any]:
    d = rec.to_dict()
    passed = d.get("passed") if rec.kind in ("verdict", "appraisal") else None
    return {
        "key": key, "kind": rec.kind, "nid": d.get("nid") or "",
        "protocol_id": d.get("protocol_id") or "", "passed": passed,
        "assurance": d.get("assurance") or d.get("evidence_assurance") or "",
        "freshness": d.get("freshness") or "", "blob_sha256": d.get("blob_sha256") or "",
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
        except Exception as e:  # already exists
            if "already" not in str(e).lower() and "exists" not in str(e).lower():
                raise
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

    def get_record(self, key: str) -> Optional[LedgerRecord]:
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

    def _write_batch(self, records: List[LedgerRecord]) -> Receipt:
        if not records:
            raise LedgerError("empty batch")
        keys = [key_for(r) for r in records]
        ops = [self._KeyValue(key=k.encode(), value=r.canonical()) for k, r in zip(keys, records)]
        try:
            header = self.client.execAll(ops)
        except Exception as e:
            raise LedgerError(f"immudb execAll failed: {e}") from e
        tx = int(header.id)
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

    def history(self) -> Iterator[Tuple[int, str, LedgerRecord]]:
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

    def _scan(self, prefix: str) -> Dict[str, dict]:
        out: Dict[str, dict] = {}
        try:
            found = self.client.scan(b"", prefix.encode(), False, 1000)
        except Exception:
            return out
        for k, v in found.items():
            out[k.decode()] = json.loads(v)
        return out

    def get(self, nid: str) -> RunRecords:
        nonce = self.get_record(f"nonce/{nid}")
        evidence = self.get_record(f"evidence/{nid}")
        verdict = self.get_record(f"verdict/{nid}")
        if not (isinstance(nonce, NonceRecord) and isinstance(evidence, EvidenceRecord)
                and isinstance(verdict, VerdictRecord)):
            raise LedgerError(f"run {nid} is not (fully) in the ledger")
        appraisals = [parse_record(v) for _k, v in sorted(self._scan(f"appraisal/{nid}/").items())]
        locators = [parse_record(v) for _k, v in sorted(self._scan(f"locator/{nid}/").items())]
        appraiser_nonces: List[NonceRecord] = []
        for a in appraisals:
            an = self.get_record(f"nonce/{a.anid}")  # type: ignore[attr-defined]
            if isinstance(an, NonceRecord):
                appraiser_nonces.append(an)
        return RunRecords(nonce=nonce, evidence=evidence, verdict=verdict,
                          appraisals=[a for a in appraisals if isinstance(a, AppraisalRecord)],
                          appraiser_nonces=appraiser_nonces,
                          locators=[l for l in locators if isinstance(l, LocatorRecord)])

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
