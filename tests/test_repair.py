"""
Repair KS behavior (no CVM needed): repair unit = measurement unit,
confirmed-violation scope, marker-block splice precision, unrepairable
paths never raise, and the full chain flow ending "repaired — pending".
"""

import pytest

import base64
from pathlib import Path

from pybb import BlackboardController
from pybb.attestation import (
    ProtocolDir,
    SliceRestoreKS,
    TierKS,
    Verdict,
    WholeFileRestoreKS,
    make_attestation_predicate,
    trust_summary,
)
from pybb.attestation.appraisal import ComponentResult
from pybb.attestation.client import AttestationClient
from pybb.attestation.snapshot import mirror_path
from pybb.blackboard import Blackboard

@pytest.fixture(autouse=True)
def _legacy_interpreter(monkeypatch):
    """These tests drive the predicate with FABRICATED responses via stub
    clients; the verified summarizer rightly refuses non-evidence, so the
    legacy parser is pinned explicitly here."""
    from pybb.attestation import summarizer
    monkeypatch.setattr(summarizer, "EVIDENCE_TOOLS_BIN", "/nonexistent")




def _component(passed: bool, args: dict, targ_id: str = "") -> ComponentResult:
    return ComponentResult(appr_asp="appr", target_asp="asp", targ_id=targ_id,
                           passed=passed, args=args)


def _verdict(protocol: str, components: list) -> Verdict:
    return Verdict(protocol=protocol,
                   passed=all(c.passed for c in components),
                   components=components)


def _tree(tmp_path, name: str, content: str) -> Path:
    live = tmp_path / "live" / name
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_text(content)
    golden = mirror_path(tmp_path / "golden", live)
    golden.parent.mkdir(parents=True, exist_ok=True)
    golden.write_text(content)
    return live


# ── WholeFileRestoreKS ────────────────────────────────────────────────────────

def _files_board(key, l1a_verdict, l2_verdict=None):
    bb = Blackboard()
    if l2_verdict is not None:
        bb.write_entry(key=key, predicate="attestation",
                       measurement={"protocol": "l2"}, result=l2_verdict)
    bb.write_entry(key=key, predicate="attestation",
                   measurement={"protocol": "l1a"}, result=l1a_verdict)
    return bb


def test_whole_file_restores_only_confirmed_violations(tmp_path):
    benign = _tree(tmp_path, "benign.aadl", "gold A")
    violated = _tree(tmp_path, "violated.aadl", "gold B")
    benign.write_text("benign developer edit")   # l1a fails, no l2 slice fails
    violated.write_text("TAMPERED contract")     # l1a fails, l2 slice fails

    l1a = _verdict("l1a", [_component(False, {"filepath": str(benign)}),
                           _component(False, {"filepath": str(violated)})])
    l2 = _verdict("gumbo_l2", [
        _component(True, {"filepath": str(benign), "start_index": 1, "end_index": 1}),
        _component(False, {"filepath": str(violated), "start_index": 1, "end_index": 1}),
    ])
    bb = _files_board("sys", l1a, l2)

    WholeFileRestoreKS(golden_root=tmp_path / "golden").execute(bb, ["sys"])

    assert violated.read_text() == "gold B"                 # confirmed -> restored
    assert benign.read_text() == "benign developer edit"    # tolerated -> untouched
    assert bb.get_entry("sys").result is None               # controller re-evaluates


def test_whole_file_falls_back_to_own_verdict_without_refinement(tmp_path):
    tampered = _tree(tmp_path, "a.aadl", "gold")
    tampered.write_text("TAMPERED")
    bb = _files_board("sys", _verdict("l1a", [_component(False, {"filepath": str(tampered)})]))

    WholeFileRestoreKS(golden_root=tmp_path / "golden").execute(bb, ["sys"])

    assert tampered.read_text() == "gold"


def test_whole_file_missing_golden_never_raises(tmp_path):
    orphan = tmp_path / "live" / "orphan.aadl"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("TAMPERED")
    bb = _files_board("sys", _verdict("l1a", [_component(False, {"filepath": str(orphan)})]))

    WholeFileRestoreKS(golden_root=tmp_path / "golden").execute(bb, ["sys"])

    assert orphan.read_text() == "TAMPERED"  # unrestorable, untouched, no crash


# ── SliceRestoreKS ────────────────────────────────────────────────────────────

_BLOCK_FILE = """\
// developer header
// BEGIN CONTRACT
gold contract line
// END CONTRACT
// developer footer
"""


def test_slice_restores_block_and_preserves_developer_edits(tmp_path):
    live = _tree(tmp_path, "comp.scala", _BLOCK_FILE)
    live.write_text(_BLOCK_FILE
                    .replace("gold contract line", "TAMPERED contract line")
                    .replace("// developer footer", "// legit developer edit"))

    verdict = _verdict("l1b", [_component(False, {
        "filepath": str(live),
        "begin_marker": "BEGIN CONTRACT", "end_marker": "END CONTRACT",
    }, targ_id="block_targ")])
    bb = _files_board("sys", verdict)

    SliceRestoreKS(golden_root=tmp_path / "golden").execute(bb, ["sys"])

    text = live.read_text()
    assert "gold contract line" in text          # block spliced back
    assert "// legit developer edit" in text     # outside-block edit preserved


def test_slice_missing_markers_never_raises(tmp_path):
    live = _tree(tmp_path, "comp.scala", _BLOCK_FILE)
    live.write_text("// markers deleted entirely\n")

    verdict = _verdict("l1b", [_component(False, {
        "filepath": str(live),
        "begin_marker": "BEGIN CONTRACT", "end_marker": "END CONTRACT",
    })])
    bb = _files_board("sys", verdict)

    SliceRestoreKS(golden_root=tmp_path / "golden").execute(bb, ["sys"])

    assert live.read_text() == "// markers deleted entirely\n"  # unrestorable


# ── full chain flow: l1a fail -> l2 fail -> repair -> repaired-pending ───────

def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def _response(filepath: str, ok: bool) -> dict:
    et = {"EvidenceT_CONSTRUCTOR": "asp_evt", "EvidenceT_BODY": [
        "P0", {"ASP_ID": "x_appr", "ASP_ARGS": {"filepath": filepath}},
        {"EvidenceT_CONSTRUCTOR": "mt_evt"}]}
    return {"TYPE": "RESPONSE", "ACTION": "RUN", "SUCCESS": True,
            "PAYLOAD": [{"RawEv": [_b64("" if ok else "mismatch")]}, et]}


def test_chain_flow_ends_repaired_pending(tmp_path):
    live = _tree(tmp_path, "a.aadl", "gold")
    live.write_text("TAMPERED")

    protocols = {
        pid: ProtocolDir(protocol_id=pid, path="/nowhere", term={},
                         session={"Session_Plc": "P0"}, manifest={"ASPS": []})
        for pid in ("l1a", "gumbo_l2")
    }

    class Client(AttestationClient):
        def run_protocol(self, protocol):
            # both tiers fail while the live file is tampered
            return _response(str(live), ok=live.read_text() == "gold")

    ctl = BlackboardController()
    ctl.register_predicate("attestation",
                           make_attestation_predicate(Client(), protocols))
    chain = [TierKS(protocol_id="gumbo_l2"),
             WholeFileRestoreKS(golden_root=tmp_path / "golden")]
    for ks in chain:
        ctl.add_ks(ks)
    ctl.blackboard.write_entry(key="sys", predicate="attestation",
                               measurement={"protocol": "l1a"})
    ctl.route("sys", on_fail=chain)
    bb = ctl.run()

    # repair fired and converged the live file to gold...
    assert live.read_text() == "gold"
    # ...but repair cannot mint trust: escalated, with the repair on record
    assert "sys" in bb.escalate
    history = bb.escalate["sys"].ks_history
    assert history == {"tier:gumbo_l2": 1, "repair:whole-file": 1}
    summary = trust_summary(bb)
    assert "repaired from golden — verification pending next episode" in summary
    assert "user intervention required" not in summary
