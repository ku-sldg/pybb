"""
End-to-end tests against the real CVM binary and asp-libs ASPs, driving the
provisioned gumbo_l1a/gumbo_l1b/gumbo_l2 protocols for temp-control-jvm on
the routed blackboard.

Decision trees under test: l1a pass = done (no confirmation tier configured
here — see test_integration_sireum for that); l1a fail -> l2 refinement;
l2 fail -> escalate with the l2 report. And the l1b sentinel: a component
contract-block tamper is invisible to l1a (whole-file hashing cannot watch
safe-to-edit files) but fails the gumbo:contracts entry at block
granularity.

Protocols measure the live temp-control-jvm tree. The tampered test corrupts
a live file; the provisioned golden directory (<repo>/golden) reverts the
tree on teardown, so the setup ends every test run intact.

Auto-skipped unless the CVM binary, ASP binaries, and temp-control-jvm tree
are present. Deselect explicitly with: pytest -m "not cvm".
"""

from pathlib import Path

import pytest

from pybb import BlackboardController
from pybb.attestation import (
    CvmSubprocessClient,
    ProtocolDir,
    TargetSnapshot,
    TierKS,
    attestation_request,
    make_attestation_predicate,
    trust_summary,
)
from pybb.attestation.client import DEFAULT_ASP_BIN, DEFAULT_CVM_BINARY

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN_ROOT = Path(__file__).parent.parent / "golden"
TC_ROOT = Path("/Users/adampetz/Claude_workspace/temp-control-jvm")

pytestmark = [
    pytest.mark.cvm,
    pytest.mark.skipif(
        not (
            Path(DEFAULT_CVM_BINARY).is_file()
            and Path(DEFAULT_ASP_BIN).is_dir()
            and TC_ROOT.is_dir()
        ),
        reason="requires local CVM binary, asp-libs binaries, and temp-control-jvm",
    ),
]


def _protocols() -> dict:
    return {
        pid: ProtocolDir.load(str(FIXTURES / pid))
        for pid in ("gumbo_l1a", "gumbo_l1b", "gumbo_l2")
    }


@pytest.fixture
def live_snapshot():
    """Golden copies of the live targets; teardown reverts any tampering."""
    snapshot = TargetSnapshot.load(_protocols(), GOLDEN_ROOT)
    try:
        yield snapshot
    finally:
        snapshot.restore()


def _run():
    """Both trust questions: gumbo:files (l1a -> l2 on fail) and
    gumbo:contracts (l1b, block-granular, no deeper dive)."""
    protocols = _protocols()
    ctl = BlackboardController()
    ctl.register_predicate(
        "attestation",
        make_attestation_predicate(CvmSubprocessClient(), protocols),
    )
    refine = TierKS(protocol_id="gumbo_l2")
    ctl.add_ks(refine)
    ctl.blackboard.write_entry(
        key="gumbo:files", predicate="attestation",
        measurement=attestation_request("gumbo_l1a"),
    )
    ctl.blackboard.write_entry(
        key="gumbo:contracts", predicate="attestation",
        measurement=attestation_request("gumbo_l1b"),
    )
    ctl.route("gumbo:files", on_fail=[refine])
    ctl.route("gumbo:contracts", on_fail=[])
    ctl.run()
    return ctl.blackboard


def test_clean_run_passes_no_escalation():
    bb = _run()

    files = bb.get_entry("gumbo:files")
    assert files is not None and files.good_standing
    assert files.result.protocol == "gumbo_l1a"
    assert len(files.result.components) == 5  # 4 hashfile_appr + sig_appr
    assert files.ks_history == {}  # l2 rung never fired
    contracts = bb.get_entry("gumbo:contracts")
    assert contracts is not None and contracts.good_standing
    assert len(contracts.result.components) == 7  # 6 blocks + sig_appr
    assert "all attested components intact" in trust_summary(bb)


def test_tampered_contract_fails_l1_and_l2_attributes(live_snapshot):
    # corrupt one line inside the provisioned GUMBO contract range 305-308
    # of TempControlSystem.aadl (target tc_sys_aadl_305_308_targ); the
    # live_snapshot fixture reverts the live file on teardown
    aadl = TC_ROOT / "aadl/packages/TempControlSystem.aadl"
    lines = aadl.read_text().splitlines(keepends=True)
    lines[305] = "-- TAMPERED: invariant weakened\n"
    aadl.write_text("".join(lines))
    assert live_snapshot.dirty() == [aadl]

    bb = _run()

    # both tiers failed and no rung remains: escalate segment, with history
    assert "gumbo:files" not in bb.entries and "gumbo:files" in bb.escalate
    escalated = bb.escalate["gumbo:files"]
    assert escalated.ks_history == {"tier:gumbo_l2": 1}
    l2 = escalated.result
    assert l2.protocol == "gumbo_l2" and not l2.passed

    failing = {c.targ_id or c.description for c in l2.failing()}
    passing = {c.targ_id or c.description for c in l2.components if c.passed}
    assert any("tc_sys_aadl_305_308" in cid for cid in failing), failing
    # attribution, not blanket failure: untampered contracts still pass
    assert len(passing) > len(failing)
    # the contracts sentinel is untouched by AADL tamper
    assert bb.get_entry("gumbo:contracts").good_standing

    summary = trust_summary(bb)
    assert "tc_sys_aadl_305_308" in summary
    assert "user intervention required" in summary


def test_block_tamper_invisible_to_l1a_caught_by_l1b(live_snapshot):
    # corrupt a line inside the COMPUTE ENSURES contract block of the
    # developer-owned component file — the coverage gap the l1b sentinel
    # exists to close: whole-file hashing (l1a) cannot watch this file
    comp = (TC_ROOT / "slang/src/main/component/tc/TempControlSoftwareSystem"
                     / "TempControlPeriodic_p_tcproc_tempControl.scala")
    lines = comp.read_text().splitlines(keepends=True)
    begin = next(i for i, l in enumerate(lines)
                 if "BEGIN COMPUTE ENSURES timeTriggered" in l)
    lines[begin + 1] = "        // TAMPERED: ensures clause weakened\n"
    comp.write_text("".join(lines))
    assert live_snapshot.dirty() == [comp]

    bb = _run()

    # the baseline question is blind to this file — and passes honestly
    assert bb.get_entry("gumbo:files").good_standing

    # the contracts sentinel catches it at block granularity
    assert "gumbo:contracts" in bb.escalate
    l1b = bb.escalate["gumbo:contracts"].result
    assert l1b.protocol == "gumbo_l1b" and not l1b.passed
    failing = {c.targ_id or c.description for c in l1b.failing()}
    assert any("tc_comp_compute_ens" in cid for cid in failing), failing
    assert len([c for c in l1b.components if c.passed]) == 6  # 5 blocks + sig
