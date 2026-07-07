"""Repair loop: splice algorithm, golden-restore, and RepairKS dynamics."""

import base64
import json
import shutil
from pathlib import Path

import pytest

from pybb import BlackboardController
from pybb.attestation import (
    AppraisalKS,
    AttestationKS,
    ComponentResult,
    EscalationKS,
    GoldenRestoreRepairer,
    ProtocolDir,
    RepairAction,
    Repairer,
    RepairKS,
    TrustDecisionKS,
    request_key,
    verdict_key,
)
from pybb.attestation.repair import _splice_flattened, attempts_key

from test_knowledge_sources import FakeClient, _appr_response, _proto, _seed

FIXTURES = Path(__file__).parent / "fixtures"
TC_ROOT = Path("/Users/adampetz/Claude_workspace/temp-control-jvm")


# ── splice algorithm (pure) ───────────────────────────────────────────────────

def test_splice_within_line_restores():
    block = "alpha\nbeta TAMPERED gamma\ndelta\n"
    golden = "alphabeta gammadelta"
    assert _splice_flattened(block, golden) == "alpha\nbeta gamma\ndelta\n"


def test_splice_clean_block_is_noop():
    block = "alpha\nbeta\n"
    assert _splice_flattened(block, "alphabeta") == block


def test_splice_refuses_multiline_tamper():
    # both lines differ from the golden: no single-line repair exists
    block = "abX\nYcd\n"
    golden = "abcd"
    assert _splice_flattened(block, golden) is None


# ── GoldenRestoreRepairer against the real provisioned goldens ────────────────

needs_tc = pytest.mark.skipif(not TC_ROOT.is_dir(), reason="requires temp-control-jvm")


def _l2_protocols():
    return {"gumbo_l2": ProtocolDir.load(str(FIXTURES / "gumbo_l2"))}


def _component_for(targ_id: str, filepath: str) -> ComponentResult:
    asp_args = json.loads((FIXTURES / "gumbo_l2" / "asp_args.json").read_text())
    for asp_id, targets in asp_args.items():
        if targ_id in targets:
            args = {**targets[targ_id], "filepath": filepath}
            args.pop("golden_b64", None)
            return ComponentResult(
                appr_asp="goldenbytes_appr", target_asp=asp_id, targ_id=targ_id,
                passed=False, args=args, description=targ_id,
            )
    raise KeyError(targ_id)


@needs_tc
def test_golden_restore_range_byte_exact(tmp_path):
    src = TC_ROOT / "slang/src/main/bridge/tc/TempControlSoftwareSystem/TempControlPeriodic_p_tcproc_tempControl_GumboX.scala"
    work = tmp_path / src.name
    shutil.copy2(src, work)
    lines = work.read_text().splitlines(keepends=True)
    lines[118] = lines[118].replace("FanCmd.Off", "FanCmd.On")  # line 119, range 113-120
    work.write_text("".join(lines))

    repairer = GoldenRestoreRepairer(_l2_protocols())
    component = _component_for("tc_gumbox_113_120_targ", str(work))
    assert repairer.can_repair(component)
    action = repairer.repair(component)
    assert action.success, action.description
    assert work.read_bytes() == src.read_bytes()


@needs_tc
def test_golden_restore_marker_block_byte_exact(tmp_path):
    asp_args = json.loads((FIXTURES / "gumbo_l2" / "asp_args.json").read_text())
    targ = "tc_comp_state_vars_targ"
    src = Path(asp_args["readfile_marker_range"][targ]["filepath"])
    work = tmp_path / src.name
    shutil.copy2(src, work)
    text = work.read_text()
    begin = asp_args["readfile_marker_range"][targ]["begin_marker"]
    idx = text.index(begin)
    eol = text.index("\n", idx)
    tamper_at = text.index("\n", eol + 1)  # first line inside the block
    work.write_text(text[:tamper_at] + " // TAMPERED" + text[tamper_at:])

    repairer = GoldenRestoreRepairer(_l2_protocols())
    component = _component_for(targ, str(work))
    action = repairer.repair(component)
    assert action.success, action.description
    assert work.read_bytes() == src.read_bytes()


@needs_tc
def test_golden_restore_refuses_line_count_change(tmp_path):
    src = TC_ROOT / "aadl/packages/TempControlSystem.aadl"
    work = tmp_path / src.name
    shutil.copy2(src, work)
    lines = work.read_text().splitlines(keepends=True)
    del lines[305]  # remove a line inside range 305-308
    work.write_text("".join(lines))

    repairer = GoldenRestoreRepairer(_l2_protocols())
    component = _component_for("tc_sys_aadl_305_308_targ", str(work))
    action = repairer.repair(component)
    assert not action.success
    # file untouched by the refused repair
    text = work.read_text()
    assert "TAMPERED" not in text and len(text.splitlines()) == len(lines)


# ── RepairKS dynamics (fake client, fake repairer) ────────────────────────────

class FakeRepairer(Repairer):
    def __init__(self, fixes: bool = True):
        self.fixes = fixes
        self.repaired: list[str] = []

    def can_repair(self, component: ComponentResult) -> bool:
        return "unrepairable" not in component.description

    def repair(self, component: ComponentResult) -> RepairAction:
        self.repaired.append(component.description)
        return RepairAction(
            component=component.description, success=self.fixes,
            description="fake repair",
        )


def _repair_controller(client, repairer, max_attempts=3):
    protocols = {p: _proto(p) for p in ("l1", "l2", "val")}
    ctl = BlackboardController()
    ctl.add_ks(AttestationKS(client=client, protocols=protocols))
    ctl.add_ks(AppraisalKS(protocols=protocols))
    ctl.add_ks(RepairKS(
        repairers=[repairer], watch=["l2"], reattest=["l1", "l2"],
        max_attempts=max_attempts,
    ))
    ctl.add_ks(EscalationKS(name="esc_l1_l2", on_fail="l1", escalate_to="l2"))
    ctl.add_ks(EscalationKS(name="esc_l2_val", on_fail="l2", escalate_to="val"))
    ctl.add_ks(TrustDecisionKS(semantic=["val"]))
    return ctl


def test_repair_success_loop_tier3_never_runs():
    client = FakeClient({
        "l1": [_appr_response({"a": False}), _appr_response({"a": True})],
        "l2": [_appr_response({"bad.range": False}), _appr_response({"bad.range": True})],
        "val": _appr_response({"logika": True}),
    })
    repairer = FakeRepairer()
    ctl = _repair_controller(client, repairer)
    _seed(ctl)
    bb = ctl.run()

    assert client.calls == ["l1", "l2", "l1", "l2"]
    assert "val" not in client.calls  # repair preempted the semantic tier
    assert repairer.repaired == ["bad.range"]
    assert bb.read(attempts_key("l2")) == 1
    assert bb.read(verdict_key("l2"))["passed"] is True
    assert "detected and repaired (1 attempt)" in bb.hypothesis
    assert "re-attested clean" in bb.hypothesis
    assert bb.entries["attestation.hypothesis"].confidence == 1.0


def test_repair_exhaustion_falls_through_to_semantic_tier():
    client = FakeClient({
        "l1": _appr_response({"a": False}),
        "l2": _appr_response({"bad.range": False}),
        "val": _appr_response({"logika": True}),
    })
    repairer = FakeRepairer(fixes=True)  # lies: nothing actually changes
    ctl = _repair_controller(client, repairer, max_attempts=2)
    _seed(ctl)
    bb = ctl.run()

    assert bb.read(attempts_key("l2")) == 2
    assert "val" in client.calls  # escalation fired after attempts exhausted
    assert "repair attempted (2 attempts) without success" in bb.hypothesis
    assert "still verifies" in bb.hypothesis  # semantic tier passed
    assert bb.entries["attestation.hypothesis"].confidence == 0.0


def test_unrepairable_burns_no_attempts():
    client = FakeClient({
        "l1": _appr_response({"a": False}),
        "l2": _appr_response({"unrepairable.hash": False}),
        "val": _appr_response({"logika": True}),
    })
    repairer = FakeRepairer()
    ctl = _repair_controller(client, repairer)
    _seed(ctl)
    bb = ctl.run()

    assert repairer.repaired == []
    assert not bb.has(attempts_key("l2"))
    assert "val" in client.calls  # straight to the semantic tier
    assert "repair attempted" not in bb.hypothesis
