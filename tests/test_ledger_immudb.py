"""ImmudbLedger against an ephemeral immudb server (fixture `immudb_server`
in conftest; skipped when the `immudb` binary is absent)."""

import secrets

import pytest

from pybb.attestation.ledger import (
    DuplicateNonceError,
    LedgerConfig,
    LedgerError,
    NonceRecord,
    sha256_hex,
)
from pybb.attestation.ledger_immudb import ImmudbLedger

from test_ledger import _b64, _nonce_record, _run_records
from test_ledger_runs import CannedClient, L1A

pytestmark = pytest.mark.ledger


@pytest.fixture
def ledger(immudb_server, tmp_path) -> ImmudbLedger:
    cfg = LedgerConfig(host=immudb_server["host"], port=immudb_server["port"], db=immudb_server["db"],
                       user=immudb_server["user"], password=immudb_server["password"],
                       state_dir=str(tmp_path / "state"), appraiser_id="ap-immu")
    return ImmudbLedger(cfg)


def test_commit_run_round_trip_with_verified_reads(ledger):
    n, an, ev, ap, vd = _run_records(nonce=secrets.token_bytes(32))
    receipt = ledger.commit_run(n, an, ev, ap, vd)
    assert receipt.tx >= 1 and receipt.verified and len(receipt.keys) == 5
    run = ledger.get(n.nid)
    assert run.evidence == ev and run.verdict == vd and run.nonce == n
    assert run.appraisals == [ap] and run.appraiser_nonces == [an]
    assert ledger.tx_of(f"evidence/{n.nid}") == receipt.tx
    with pytest.raises(DuplicateNonceError):
        ledger.commit_run(n, an, ev, ap, vd)


def test_history_is_in_tx_order_and_skips_sql_internals(ledger):
    runs = [_run_records(nonce=secrets.token_bytes(32)) for _ in range(2)]
    txs = [ledger.commit_run(*r).tx for r in runs]
    seen = [(tx, key) for tx, key, _rec in ledger.history()]
    assert [tx for tx, _ in seen if tx in txs] == sorted(tx for tx, _ in seen if tx in txs)
    for (n, *_), tx in zip(runs, txs):
        keys_in_tx = {key for t, key in seen if t == tx}
        assert keys_in_tx == {f"nonce/{n.nid}", f"evidence/{n.nid}", f"verdict/{n.nid}",
                              f"appraisal/{n.nid}/1"} | {k for k in keys_in_tx if k.startswith("nonce/")}
    assert all(key.split("/")[0] in ("nonce", "evidence", "verdict", "appraisal", "locator", "bundle", "restore")
               for _tx, key in seen)


def test_sql_mirror_rows_match_kv_content_hashes(ledger):
    n, an, ev, ap, vd = _run_records(nonce=secrets.token_bytes(32))
    ledger.commit_run(n, an, ev, ap, vd)
    rows = ledger.mirror_query(
        "SELECT key, kind, passed, assurance, content_sha256 FROM attestation_records WHERE nid = @nid",
        {"nid": n.nid})
    by_key = {r[0] if isinstance(r, (list, tuple)) else r["key"]: r for r in rows}
    assert set(by_key) == {f"evidence/{n.nid}", f"verdict/{n.nid}", f"appraisal/{n.nid}/1", f"nonce/{n.nid}"}
    verdict_row = by_key[f"verdict/{n.nid}"]
    vals = list(verdict_row) if isinstance(verdict_row, (list, tuple)) else list(verdict_row.values())
    assert vd.content_sha256() in vals and True in vals  # passed=True mirrored
    # a reader can verify the row against the KV value
    rec = ledger.get_record(f"verdict/{n.nid}")
    assert rec.content_sha256() == vd.content_sha256()


def test_client_state_persists_and_advances(ledger, tmp_path):
    before = ledger.state()["tx_id"]
    n, an, ev, ap, vd = _run_records(nonce=secrets.token_bytes(32))
    ledger.commit_run(n, an, ev, ap, vd)
    after = ledger.state()["tx_id"]
    assert after > before
    state_files = list((tmp_path / "state").glob("immudb_state_*"))
    assert state_files, "PersistentRootService must persist the verified root"
    # a second client over the same state file verifies the same records
    again = ImmudbLedger(ledger.config)
    assert again.get(n.nid).verdict == vd


def test_bad_login_fails_closed(immudb_server, tmp_path):
    cfg = LedgerConfig(host=immudb_server["host"], port=immudb_server["port"], db=immudb_server["db"],
                       user=immudb_server["user"], password="Wrong-pass1!", state_dir=str(tmp_path / "s"))
    with pytest.raises(LedgerError, match="login failed"):
        ImmudbLedger(cfg)


def test_two_run_flow_commits_to_immudb(ledger):
    from pybb.attestation import ProtocolDir
    from pybb.attestation.ledger_runs import attest_with_ledger

    proto = ProtocolDir.load(str(L1A))
    cfg = ledger.config.model_copy(update={"verify_key_path": "/nonexistent.pem"})
    r = attest_with_ledger(CannedClient(), proto, ledger, cfg)
    assert r.error == "", r.error
    run = ledger.get(r.nonce_id)
    assert run.verdict.passed and run.evidence.assurance == "signed+nonce"
    assert run.appraisals[0].binding.evidence_hash == run.evidence.rawev_sha256
    again = attest_with_ledger(CannedClient(), proto, ledger, cfg)
    assert "duplicate nonce" in again.error
