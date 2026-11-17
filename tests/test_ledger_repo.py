"""Evidence repo: push, github locators, reconcile, verify, replay (plan H),
against a throwaway local bare git remote standing in for GitHub."""

import gzip
import json
import subprocess
from pathlib import Path

import pytest

from pybb.attestation import FileLedger, ProtocolDir
from pybb.attestation.ledger import LedgerConfig, LedgerError, Locator
from pybb.attestation.ledger_repo import (
    EvidenceRepo,
    commit_bundles,
    pending_blobs,
    push_archive,
    read_journal,
    reconcile,
    record_restore,
    replay,
    resolve_github_locator,
    verify_mirror,
)
from pybb.attestation.ledger_runs import appraise_record, attest_with_ledger, fetch_run

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
    r1 = attest_with_ledger(CannedClient(), proto, ledger, config, archive=archive)
    assert r1.error == "", r1.error
    # second run with distinct nonces: tweak the canned packages' nonce slots
    raw2 = json.loads(json.dumps(CannedClient().raw)); appr2 = json.loads(json.dumps(APPR))
    import base64
    raw2["PAYLOAD"][0]["RawEv"][1] = base64.b64encode(bytes([3]) * 32).decode()
    appr2["PAYLOAD"][0]["RawEv"][1] = base64.b64encode(bytes([4]) * 32).decode()
    r2 = attest_with_ledger(CannedClient(raw=raw2, appr=appr2), proto, ledger, config, archive=archive)
    assert r2.error == "", r2.error
    return proto, r1, r2


def test_slug_from_remote_url(remote_and_clone):
    bare, clone = remote_and_clone
    repo = EvidenceRepo(clone)
    assert repo.slug() == "pybb-evidence"
    assert EvidenceRepo(clone, slug="ku-sldg/pybb-evidence").slug() == "ku-sldg/pybb-evidence"
    with pytest.raises(LedgerError, match="not a git clone"):
        EvidenceRepo(bare.parent / "nowhere")


def test_push_archive_mirrors_blobs_records_journal_state_and_locators(tmp_path, config, remote_and_clone):
    bare, clone = remote_and_clone
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    proto, r1, r2 = _two_runs(ledger, config, tmp_path / "evidence")
    repo = EvidenceRepo(clone)
    assert len(pending_blobs(ledger)) == 6  # 2 runs x (evidence, appraisal, components)

    rep = push_archive(ledger, repo, config)
    assert rep.problems == [], rep.problems
    assert rep.committed and rep.pushed and len(rep.blobs) == 6 and rep.locators_appended == 6
    assert rep.journal_from_tx == 1 and rep.journal_to_tx == 2 and rep.state_tx == 2

    # layout
    assert sorted(p.name for p in (clone / "blobs").iterdir()) == sorted(f"{b}.json.gz" for b in rep.blobs)
    assert (clone / f"ledger/records/{r1.nonce_id}/evidence.json").is_file()
    assert (clone / f"ledger/records/{r1.nonce_id}/appraisal-1.json").is_file()
    assert (clone / f"ledger/records/{r1.nonce_id}/locator-1.json").is_file()
    journal = read_journal(clone)
    assert [l["tx"] for l in journal] == [1, 2] and all(len(l["keys"]) == 7 for l in journal)
    states = sorted((clone / "ledger/state").glob("*.json"))
    assert len(states) == 1 and json.loads(states[0].read_text())["tx_id"] == 2
    manifest = json.loads((clone / "runs/20261117-000000-abcd/manifest.json").read_text())
    assert set(manifest[proto.protocol_id]) >= {f"evidence:{r1.nonce_id}", f"appraisal:{r2.nonce_id}"}
    # the remote has the commit
    remote_head = subprocess.run(["git", "-C", str(bare), "rev-parse", "main"], capture_output=True, text=True).stdout.strip()
    assert remote_head == rep.commit

    # locators: github, verified, pointing at the committed blob
    run1 = ledger.get(r1.nonce_id)
    gh = [l for l in run1.locators if l.locator.kind == "github"]
    assert {l.target for l in gh} == {"evidence", "appraisal", "components"}
    ev_loc = next(l for l in gh if l.target == "evidence")
    assert ev_loc.verified and ev_loc.locator.repo == "pybb-evidence" and ev_loc.locator.commit == rep.commit
    assert ev_loc.locator.path == f"blobs/{run1.evidence.blob_sha256}.json.gz" and ev_loc.locator.git_blob_sha
    assert pending_blobs(ledger) == []

    # a second push with nothing new: no commit, journal only grows with the locator txs
    rep2 = push_archive(ledger, repo, config)
    assert rep2.committed and rep2.blobs == [] and rep2.locators_appended == 0
    assert read_journal(clone)[-1]["tx"] == len(ledger)

    # reconcile: nothing pending, remote blobs verify, live state consistent
    rec = reconcile(ledger, repo, verify_all=True)
    assert rec and rec.verified_remote == 6 and rec.state_ok


def test_github_locator_serves_when_local_archive_is_gone(tmp_path, config, remote_and_clone, monkeypatch):
    bare, clone = remote_and_clone
    monkeypatch.setenv("PYBB_EVIDENCE_REPO", str(clone))
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    proto, r1, _ = _two_runs(ledger, config, tmp_path / "evidence")
    push_archive(ledger, EvidenceRepo(clone), config)
    import shutil
    shutil.rmtree(tmp_path / "evidence")  # the local disk is lost
    fetched = fetch_run(ledger, r1.nonce_id)
    assert fetched.locator.kind == "github"
    assert fetched.payload == CannedClient().raw["PAYLOAD"]
    # and a ledger-driven re-appraisal still works from the repo copy
    import base64
    audit_pkg = json.loads(json.dumps(APPR))
    audit_pkg["PAYLOAD"][0]["RawEv"][1] = base64.b64encode(bytes([8]) * 32).decode()
    rep = appraise_record(CannedClient(appr=audit_pkg), proto, ledger, config, r1.nonce_id)
    assert rep.error == "" and rep.locator_used.kind == "github"
    # an unknown commit on a clone that cannot fetch it resolves to None, not garbage
    assert resolve_github_locator(Locator(kind="github", path="blobs/x", repo="pybb-evidence", commit="0" * 40)) is None


def test_reconcile_flags_backlog_and_rollback(tmp_path, config, remote_and_clone):
    bare, clone = remote_and_clone
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    _two_runs(ledger, config, tmp_path / "evidence")
    repo = EvidenceRepo(clone)
    assert len(reconcile(ledger, repo).pending) == 6
    push_archive(ledger, repo, config)
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
    push_archive(ledger, repo, config)  # journals the locator txs too
    assert read_journal(clone)[-1]["tx"] == len(ledger)

    mr = verify_mirror(clone)
    assert mr, mr.problems
    assert mr.txs == len(ledger) and mr.blobs_checked >= 6

    restored = FileLedger(tmp_path / "restored.jsonl")
    n = replay(clone, restored)
    assert n == len(ledger)
    for nid in (r1.nonce_id, r2.nonce_id):
        a, b = ledger.get(nid), restored.get(nid)
        assert a.evidence == b.evidence and a.verdict == b.verdict and a.appraisals == b.appraisals
        assert {l.locator.kind for l in b.locators} == {"local", "github"}
    assert {k for _t, k, _r in ledger.history()} == {k for _t, k, _r in restored.history()}
    rr = record_restore(restored, repo, "replay", source_last_state_tx=len(ledger), tx_count=n, config=config)
    assert rr.mode == "replay" and restored.exists(f"restore/{rr.created_at}")

    # tamper a mirrored record: verify refuses, replay refuses
    f = clone / f"ledger/records/{r1.nonce_id}/verdict.json"
    f.write_bytes(f.read_bytes().replace(b'"passed":true', b'"passed":false'))
    bad = verify_mirror(clone)
    assert not bad and any("verdict/" in p and "content_sha256" in p for p in bad.problems)
    with pytest.raises(LedgerError, match="does not verify"):
        replay(clone, FileLedger(tmp_path / "r2.jsonl"))


def test_legacy_bundles_become_bundle_records_and_push(tmp_path, config, remote_and_clone):
    bare, clone = remote_and_clone
    golden = REPO_ROOT / "golden"
    if not (golden / "_bundles/temp_control_aadl_slang_l1a/provision_bundle.json").is_file():
        pytest.skip("no l1a provision bundle in the checkout")
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    proto = ProtocolDir.load(str(L1A))
    keys = commit_bundles(ledger, golden, {proto.protocol_id: proto}, config)
    assert len(keys) == 1 and keys[0].startswith("bundle/sha256:")
    rec = ledger.get_record(keys[0])
    assert rec.assurance == "signed" and rec.nid is None and rec.nonce is None and rec.signature.present
    assert rec.rawev_count >= 2 and rec.targets == 4
    assert commit_bundles(ledger, golden, {proto.protocol_id: proto}, config) == []  # idempotent
    rep = push_archive(ledger, EvidenceRepo(clone), config)
    assert rep.problems == [] and len(rep.blobs) == 1 and rep.locators_appended == 1
    loc = next(r for _t, _k, r in ledger.history() if r.kind == "locator")
    assert loc.target == "bundle" and loc.nid == keys[0].split("/", 1)[1] and loc.verified
