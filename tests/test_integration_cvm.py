"""
End-to-end tests against the real CVM binary and asp-libs ASPs, driving the
provisioned gumbo_l1/gumbo_l2 protocols for temp-control-jvm on the routed
blackboard.

Decision tree under test: l1 pass = done (no confirmation tier configured
here — see test_integration_sireum for that); l1 fail -> l2 attribution;
l2 fail -> escalate with the l2 report.

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
        pid: ProtocolDir.load(str(FIXTURES / pid)) for pid in ("gumbo_l1", "gumbo_l2")
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
    protocols = _protocols()
    ctl = BlackboardController()
    ctl.register_predicate(
        "attestation",
        make_attestation_predicate(CvmSubprocessClient(), protocols),
    )
    rungs = [TierKS(protocol_id="gumbo_l2")]
    for ks in rungs:
        ctl.add_ks(ks)
    ctl.blackboard.write_entry(
        key="gumbo", predicate="attestation",
        measurement=attestation_request("gumbo_l1"),
    )
    ctl.route("gumbo", on_fail=rungs)
    ctl.run()
    return ctl.blackboard


def test_clean_run_passes_no_escalation():
    bb = _run()

    entry = bb.get_entry("gumbo")
    assert entry is not None and entry.good_standing
    assert entry.result.protocol == "gumbo_l1"
    assert len(entry.result.components) == 5  # 4 hashfile_appr + sig_appr
    assert entry.ks_history == {}  # l2 rung never fired
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
    assert "gumbo" not in bb.entries and "gumbo" in bb.escalate
    escalated = bb.escalate["gumbo"]
    assert escalated.ks_history == {"tier:gumbo_l2": 1}
    l2 = escalated.result
    assert l2.protocol == "gumbo_l2" and not l2.passed

    failing = {c.targ_id or c.description for c in l2.failing()}
    passing = {c.targ_id or c.description for c in l2.components if c.passed}
    assert any("tc_sys_aadl_305_308" in cid for cid in failing), failing
    # attribution, not blanket failure: untampered contracts still pass
    assert len(passing) > len(failing)

    summary = trust_summary(bb)
    assert "tc_sys_aadl_305_308" in summary
    assert "user intervention required" in summary
