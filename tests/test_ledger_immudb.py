"""ImmudbLedger against an ephemeral immudb server (fixture `immudb_server`
in conftest; skipped when the `immudb` binary is absent)."""

import secrets

import pytest

from pybb.attestation.ledger import (
    DuplicateNonceError,
    LedgerConfig,
    LedgerError,
    MirrorRecord,
)
from pybb.attestation.ledger_immudb import ImmudbLedger

from test_ledger import _appraisal_bundle, _measurement_bundle
from test_ledger_runs import CannedClient, L1A

pytestmark = pytest.mark.ledger


@pytest.fixture
def ledger(immudb_server, tmp_path) -> ImmudbLedger:
    cfg = LedgerConfig(host=immudb_server["host"], port=immudb_server["port"], db=immudb_server["db"],
                       user=immudb_server["user"], password=immudb_server["password"],
                       state_dir=str(tmp_path / "state"), appraiser_id="ap-immu", evidence_repo="")
    return ImmudbLedger(cfg)


def _pair():
    m = _measurement_bundle(secrets.token_bytes(32))
    return m, _appraisal_bundle(m)


def test_commit_bundles_round_trip_with_verified_reads(ledger):
    m, a = _pair()
    receipt = ledger.commit_bundles([m, a])
    assert receipt.tx >= 1 and receipt.verified and len(receipt.keys) == 3
    assert ledger.get(m.bid) == m and ledger.get(a.bid) == a
    assert ledger.appraisals_of(m.bid) == [a]
    assert ledger.tx_of(f"bundle/{m.bid}") == receipt.tx
    with pytest.raises(DuplicateNonceError):
        ledger.commit_bundles([m, a])


def test_server_side_precondition_refuses_an_existing_bundle_key(ledger):
    """The KV write itself carries keyMustNotExist for every bundle key, so
    even a writer that skips pybb's own check cannot overwrite a bundle."""
    m, a = _pair()
    ledger.commit_bundles([m, a])
    tampered = m.model_copy(update={"assurance": "none"})
    with pytest.raises(LedgerError) as e:
        ledger._write_batch([tampered])
    assert "precondition" in str(e.value).lower()
    assert ledger.get(m.bid) == m  # the stored value is untouched
    # a mirror record (not a bundle) carries no precondition and writes normally
    ledger._write_batch([MirrorRecord(store="github:o/r", commit="c", state_tx=ledger.state()["tx_id"])])


def test_history_is_in_tx_order_and_skips_sql_internals(ledger):
    pairs = [_pair() for _ in range(2)]
    txs = [ledger.commit_bundles(list(p)).tx for p in pairs]
    seen = [(tx, key) for tx, key, _rec in ledger.history()]
    assert [tx for tx, _ in seen if tx in txs] == sorted(tx for tx, _ in seen if tx in txs)
    for (m, a), tx in zip(pairs, txs):
        assert {key for t, key in seen if t == tx} == {f"bundle/{m.bid}", f"bundle/{a.bid}", f"judged_by/{m.bid}/{a.bid}"}
    assert all(key.split("/")[0] in ("bundle", "judged_by", "mirror", "restore") for _tx, key in seen)
    assert set(ledger.scan_prefix(f"judged_by/{pairs[0][0].bid}/")) == {f"judged_by/{pairs[0][0].bid}/{pairs[0][1].bid}"}


def test_sql_mirror_rows_match_kv_content_hashes(ledger):
    m, a = _pair()
    ledger.commit_bundles([m, a])
    rows = ledger.mirror_query(
        "SELECT key, kind, role, passed, content_sha256 FROM attestation_records "
        "WHERE key = @mk OR input_bid = @bid", {"mk": f"bundle/{m.bid}", "bid": m.bid})
    by_key = {r[0] if isinstance(r, (list, tuple)) else r["key"]: r for r in rows}
    assert set(by_key) == {f"bundle/{m.bid}", f"bundle/{a.bid}", f"judged_by/{m.bid}/{a.bid}"}
    arow = by_key[f"bundle/{a.bid}"]
    vals = list(arow) if isinstance(arow, (list, tuple)) else list(arow.values())
    assert a.content_sha256() in vals and True in vals  # passed=True mirrored
    # a reader can verify the row against the KV value
    assert ledger.get_record(f"bundle/{a.bid}").content_sha256() == a.content_sha256()


def test_client_state_persists_and_advances(ledger, tmp_path):
    before = ledger.state()["tx_id"]
    m, a = _pair()
    ledger.commit_bundles([m, a])
    after = ledger.state()["tx_id"]
    assert after > before
    state_files = list((tmp_path / "state").glob("immudb_state_*"))
    assert state_files, "PersistentRootService must persist the verified root"
    # a second client over the same state file verifies the same records
    again = ImmudbLedger(ledger.config)
    assert again.get(a.bid).verdict == a.verdict


def test_bad_login_fails_closed(immudb_server, tmp_path):
    cfg = LedgerConfig(host=immudb_server["host"], port=immudb_server["port"], db=immudb_server["db"],
                       user=immudb_server["user"], password="Wrong-pass1!", state_dir=str(tmp_path / "s"))
    with pytest.raises(LedgerError, match="login failed"):
        ImmudbLedger(cfg)


def test_two_run_flow_commits_to_immudb(ledger):
    from pybb.attestation import ProtocolDir
    from pybb.attestation.ledger_runs import attest

    proto = ProtocolDir.load(str(L1A))
    cfg = ledger.config.model_copy(update={"verify_key_path": "/nonexistent.pem"})
    r = attest(CannedClient(), proto, ledger, cfg)
    assert r.error == "", r.error
    m = ledger.get(r.bid)
    a = ledger.appraisals_of(r.bid)[0]
    assert a.verdict.passed and m.assurance == "signed+nonce"
    assert a.inputs[0].binding_hash == m.rawev_sha256
    again = attest(CannedClient(), proto, ledger, cfg)
    assert "duplicate" in again.error
