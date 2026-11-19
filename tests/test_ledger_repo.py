"""Evidence repo: push, stated locations, mirror records, reconcile, verify,
replay (plan H, K decision 7), against a throwaway local bare git remote
standing in for GitHub."""

import base64
import gzip
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from pybb.attestation import FileLedger, ProtocolDir
from pybb.attestation.ledger import LedgerConfig, LedgerError, Location
from pybb.attestation.ledger_repo import (
    EvidenceRepo,
    pending_blobs,
    push_archive,
    read_journal,
    reconcile,
    record_provision_bundles,
    record_restore,
    replay,
    resolve_remote_location,
    stated_blobs,
    verify_mirror,
)
from pybb.attestation.ledger_runs import appraise_bundle, attest, fetch_bundle

from test_ledger_runs import APPR, L1A, CannedClient

REPO_ROOT = Path(__file__).parent.parent


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def remote_and_clone(tmp_path):
    bare = tmp_path / "pybb-evidence.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(bare), str(clone)], check=True)
    _git(clone, "config", "user.email", "ledger@test"); _git(clone, "config", "user.name", "ledger test")
    (clone / "README.md").write_text("evidence repo (test)\n")
    _git(clone, "add", "README.md"); _git(clone, "commit", "-q", "-m", "init"); _git(clone, "push", "-q", "origin", "main")
    return bare, clone


@pytest.fixture
def config(tmp_path, remote_and_clone):
    return LedgerConfig(state_dir=str(tmp_path / "state"), appraiser_id="ap-repo",
                        verify_key_path=str(tmp_path / "none.pem"), evidence_repo=str(remote_and_clone[1]))


STORE = "git:pybb-evidence"


def _archiver(root: Path):
    def archive(obj, pid, kind):
        d = root / "20261117-000000-abcd"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{pid}.{kind}.json.gz"
        seq = 1
        while p.exists():
            seq += 1
            p = d / f"{pid}.{kind}.{seq}.json.gz"
        with gzip.open(p, "wb") as f:
            f.write(json.dumps(obj).encode())
        return str(p)
    return archive


def _two_runs(ledger, config, archive_root):
    proto = ProtocolDir.load(str(L1A))
    archive = _archiver(archive_root)
    r1 = attest(CannedClient(), proto, ledger, config, archive=archive)
    assert r1.error == "", r1.error
    # second run with distinct nonces: tweak the canned packages' nonce slots
    raw2 = json.loads(json.dumps(CannedClient().raw)); appr2 = json.loads(json.dumps(APPR))
    raw2["PAYLOAD"][0]["RawEv"][1] = base64.b64encode(bytes([3]) * 32).decode()
    appr2["PAYLOAD"][0]["RawEv"][1] = base64.b64encode(bytes([4]) * 32).decode()
    r2 = attest(CannedClient(raw=raw2, appr=appr2), proto, ledger, config, archive=archive)
    assert r2.error == "", r2.error
    return proto, r1, r2


def test_slug_and_store_id_from_remote_url(remote_and_clone):
    bare, clone = remote_and_clone
    repo = EvidenceRepo(clone)
    assert repo.slug() == "pybb-evidence" and repo.store_id() == STORE
    hosted = EvidenceRepo(clone, slug="ku-sldg/pybb-evidence")
    hosted._hosted = True
    assert hosted.store_id() == "github:ku-sldg/pybb-evidence"
    with pytest.raises(LedgerError, match="not a git clone"):
        EvidenceRepo(bare.parent / "nowhere")


def test_bundles_state_their_remote_locations_at_commit(tmp_path, config):
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    _proto, r1, _r2 = _two_runs(ledger, config, tmp_path / "evidence")
    m = ledger.get(r1.bid)
    assert [l.store for l in m.blob.locations] == ["local", STORE]
    assert m.blob.locations[1].path == f"blobs/{m.blob.blob_sha256}.json.gz"
    a = ledger.get(r1.appraisal_bid)
    assert a.verdict.components_blob.locations[1] == Location(store=STORE, path=f"blobs/{a.verdict.components_blob.blob_sha256}.json.gz")
    assert len(stated_blobs(ledger, STORE)) == 6  # 2 runs x (measurement, appraisal, components)
    assert stated_blobs(ledger, "github:nobody/nothing") == []


def test_push_archive_mirrors_blobs_records_journal_state_and_writes_a_mirror_record(tmp_path, config, remote_and_clone):
    bare, clone = remote_and_clone
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    proto, r1, r2 = _two_runs(ledger, config, tmp_path / "evidence")
    repo = EvidenceRepo(clone)
    assert len(pending_blobs(ledger, repo)) == 6

    rep = push_archive(ledger, repo, config)
    assert rep.problems == [], rep.problems
    assert rep.committed and rep.pushed and len(rep.blobs) == 6 and rep.store == STORE
    assert rep.journal_from_tx == 1 and rep.journal_to_tx == 2 and rep.state_tx == 2
    assert rep.mirror_key == "mirror/git-pybb-evidence/000000000002"

    # layout
    assert sorted(p.name for p in (clone / "blobs").iterdir()) == sorted(f"{b}.json.gz" for b in rep.blobs)
    assert (clone / f"ledger/bundles/{r1.bid}.json").is_file()
    assert (clone / f"ledger/bundles/{r1.appraisal_bid}.json").is_file()
    assert (clone / f"ledger/judged_by/{r1.bid}/{r1.appraisal_bid}.json").is_file()
    journal = read_journal(clone)
    assert [l["tx"] for l in journal] == [1, 2] and all(len(l["keys"]) == 3 for l in journal)
    states = sorted((clone / "ledger/state").glob("*.json"))
    assert len(states) == 1 and json.loads(states[0].read_text())["tx_id"] == 2
    manifest = json.loads((clone / "runs/20261117-000000-abcd/manifest.json").read_text())
    assert set(manifest[proto.protocol_id]) >= {f"package:{r1.bid}", f"package:{r2.appraisal_bid}",
                                                f"components:{r2.appraisal_bid}"}
    # the remote has the commit
    remote_head = subprocess.run(["git", "-C", str(bare), "rev-parse", "main"], capture_output=True, text=True).stdout.strip()
    assert remote_head == rep.commit

    # the mirror record witnesses the push
    mir = ledger.latest_mirror(STORE)
    assert mir is not None and mir.commit == rep.commit and mir.state_tx == 2 and mir.blobs == 6
    assert mir.journal_from_tx == 1 and mir.journal_to_tx == 2 and mir.skipped == [] and mir.repo == "pybb-evidence"
    assert mir.state_hash == json.loads(states[0].read_text())["tx_hash_hex"]
    assert pending_blobs(ledger, repo) == []

    # a second push: nothing new but the mirror record's own tx, which is journaled
    rep2 = push_archive(ledger, repo, config)
    assert rep2.committed and rep2.blobs == [] and rep2.journal_from_tx == 3 and rep2.journal_to_tx == 3
    assert (clone / "ledger/mirror/git-pybb-evidence/000000000002.json").is_file()
    assert read_journal(clone)[-1]["tx"] == 3 and len(ledger) == 4  # the second mirror record

    # reconcile: nothing pending, remote blobs verify, live state consistent
    rec = reconcile(ledger, repo, verify_all=True)
    assert rec, rec.problems
    assert rec.verified_remote == 6 and rec.state_ok and rec.last_mirror.state_tx == 3  # the head at push 2


def test_remote_location_serves_when_local_archive_is_gone(tmp_path, config, remote_and_clone, monkeypatch):
    bare, clone = remote_and_clone
    monkeypatch.setenv("PYBB_EVIDENCE_REPO", str(clone))
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    proto, r1, _ = _two_runs(ledger, config, tmp_path / "evidence")
    push_archive(ledger, EvidenceRepo(clone), config)
    shutil.rmtree(tmp_path / "evidence")  # the local disk is lost
    fetched = fetch_bundle(ledger, r1.bid, config)
    assert fetched.location.store == STORE
    assert fetched.payload == CannedClient().raw["PAYLOAD"]
    # and a ledger-driven appraisal still works from the repo copy
    audit_pkg = json.loads(json.dumps(APPR))
    audit_pkg["PAYLOAD"][0]["RawEv"][1] = base64.b64encode(bytes([8]) * 32).decode()
    rep = appraise_bundle(CannedClient(appr=audit_pkg), proto, ledger, config, r1.bid)
    assert rep.error == "" and rep.location_used.store == STORE
    # a path the store does not have resolves to None, not garbage
    assert resolve_remote_location(Location(store=STORE, path="blobs/x.json.gz"), config) is None
    assert resolve_remote_location(Location(store="git:elsewhere", path="blobs/x.json.gz"), config) is None


def test_reconcile_flags_backlog_rollback_and_skipped_blobs(tmp_path, config, remote_and_clone):
    bare, clone = remote_and_clone
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    _proto, r1, _r2 = _two_runs(ledger, config, tmp_path / "evidence")
    repo = EvidenceRepo(clone)
    assert len(reconcile(ledger, repo).pending) == 6
    # a blob whose local bytes are gone is skipped and named in the mirror record
    Path(r1.components_ref).unlink()
    rep = push_archive(ledger, repo, config)
    assert len(rep.blobs) == 5 and len(rep.skipped) == 1 and rep.problems
    mir = ledger.latest_mirror(STORE)
    assert mir.blobs == 5 and mir.skipped[0]["reason"] == "local bytes missing"
    rec = reconcile(ledger, repo)
    assert len(rec.pending) == 1 and rec.pending[0].part == "components"
    # simulate a rolled-back ledger: a fresh, shorter ledger file
    rolled = FileLedger(tmp_path / "rolled.jsonl")
    rec = reconcile(rolled, repo)
    assert rec.state_ok is False and any("behind the mirrored" in p for p in rec.problems)


def test_restore_drill_verify_and_replay(tmp_path, config, remote_and_clone):
    bare, clone = remote_and_clone
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    proto, r1, r2 = _two_runs(ledger, config, tmp_path / "evidence")
    repo = EvidenceRepo(clone)
    push_archive(ledger, repo, config)
    push_archive(ledger, repo, config)  # journals the first mirror record too
    assert read_journal(clone)[-1]["tx"] == len(ledger) - 1

    mr = verify_mirror(clone)
    assert mr, mr.problems
    assert mr.txs == len(ledger) - 1 and mr.blobs_checked >= 6

    restored = FileLedger(tmp_path / "restored.jsonl")
    n = replay(clone, restored)
    assert n == len(ledger) - 1
    for r in (r1, r2):
        assert ledger.get(r.bid) == restored.get(r.bid)
        assert ledger.appraisals_of(r.bid) == restored.appraisals_of(r.bid)
    assert restored.latest_mirror(STORE).state_tx == 2
    rr = record_restore(restored, repo, "replay", source_last_state_tx=len(ledger), tx_count=n, config=config)
    assert rr.mode == "replay" and restored.exists(f"restore/{rr.created_at}")

    # tamper a mirrored record: verify refuses, replay refuses
    f = clone / f"ledger/bundles/{r1.appraisal_bid}.json"
    f.write_bytes(f.read_bytes().replace(b'"passed":true', b'"passed":false'))
    bad = verify_mirror(clone)
    assert not bad and any("bundle/" in p and "content_sha256" in p for p in bad.problems)
    with pytest.raises(LedgerError, match="does not verify"):
        replay(clone, FileLedger(tmp_path / "r2.jsonl"))


def test_legacy_provision_bundles_become_provision_bundles_and_push(tmp_path, config, remote_and_clone):
    bare, clone = remote_and_clone
    golden = REPO_ROOT / "golden"
    if not (golden / "_bundles/temp_control_aadl_slang_l1a/provision_bundle.json").is_file():
        pytest.skip("no l1a provision bundle in the checkout")
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    proto = ProtocolDir.load(str(L1A))
    keys = record_provision_bundles(ledger, golden, {proto.protocol_id: proto}, config)
    assert len(keys) == 1 and keys[0].startswith("bundle/sha256:")
    rec = ledger.get_record(keys[0])
    assert rec.role == "provision" and rec.assurance == "signed" and rec.freshness == "none"
    assert rec.bid is None and rec.nonce is None and rec.signature.present
    assert rec.rawev_count >= 2 and rec.provision.targets == 4 and rec.blob.encoding == "json"
    assert [l.store for l in rec.blob.locations] == ["local", STORE] and rec.blob.locations[1].path.endswith(".json")
    assert record_provision_bundles(ledger, golden, {proto.protocol_id: proto}, config) == []  # idempotent
    rep = push_archive(ledger, EvidenceRepo(clone), config)
    assert rep.problems == [] and len(rep.blobs) == 1
    assert (clone / rec.blob.locations[1].path).is_file()
    assert ledger.latest_mirror(STORE).blobs == 1
