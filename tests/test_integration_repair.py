"""
End-to-end repair against the real CVM: episode 1 detects, attributes, and
repairs from the golden directory, ending "repaired — verification
pending"; episode 2 (fresh predicates, fresh caches) provides the
verifying evidence. Repair unit = measurement unit: whole-file restore for
the l1a baseline tier, block splice for the l1b sentinel.

Auto-skipped unless the CVM binary, ASP binaries, temp-control-jvm, and
golden/ are present.
"""

from pathlib import Path

import pytest

from pybb import BlackboardController
from pybb.attestation import (
    CvmSubprocessClient,
    ProtocolDir,
    SliceRestoreKS,
    TargetSnapshot,
    TierKS,
    WholeFileRestoreKS,
    attestation_request,
    make_attestation_predicate,
    trust_summary,
)
from pybb.attestation.client import DEFAULT_ASP_BIN, DEFAULT_CVM_BINARY
from pybb.attestation.snapshot import mirror_path

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
            and GOLDEN_ROOT.is_dir()
        ),
        reason="requires CVM binary, asp-libs binaries, temp-control-jvm, "
               "and the golden directory",
    ),
]


def _protocols() -> dict:
    return {
        pid: ProtocolDir.load(str(FIXTURES / pid))
        for pid in ("gumbo_l1a", "gumbo_l1b", "gumbo_l2")
    }


@pytest.fixture
def live_snapshot():
    snapshot = TargetSnapshot.load(_protocols(), GOLDEN_ROOT)
    try:
        yield snapshot
    finally:
        snapshot.restore()


def _episode():
    """One workflow episode with repair rungs on both fail chains."""
    protocols = _protocols()
    ctl = BlackboardController()
    ctl.register_predicate(
        "attestation",
        make_attestation_predicate(CvmSubprocessClient(), protocols),
    )
    files_fail = [TierKS(protocol_id="gumbo_l2"),
                  WholeFileRestoreKS(golden_root=GOLDEN_ROOT)]
    contracts_fail = [SliceRestoreKS(golden_root=GOLDEN_ROOT)]
    for ks in [*files_fail, *contracts_fail]:
        ctl.add_ks(ks)
    ctl.blackboard.write_entry(
        key="gumbo:files", predicate="attestation",
        measurement=attestation_request("gumbo_l1a"),
    )
    ctl.blackboard.write_entry(
        key="gumbo:contracts", predicate="attestation",
        measurement=attestation_request("gumbo_l1b"),
    )
    ctl.route("gumbo:files", on_fail=files_fail)
    ctl.route("gumbo:contracts", on_fail=contracts_fail)
    ctl.run()
    return ctl.blackboard


def test_aadl_tamper_whole_file_repair_verified_next_episode(live_snapshot):
    aadl = TC_ROOT / "aadl/packages/TempControlSystem.aadl"
    golden_copy = mirror_path(GOLDEN_ROOT, aadl)
    lines = aadl.read_text().splitlines(keepends=True)
    lines[305] = "-- TAMPERED: invariant weakened\n"
    aadl.write_text("".join(lines))

    bb1 = _episode()

    # episode 1: attributed, repaired, escalated as repaired-pending
    escalated = bb1.escalate["gumbo:files"]
    assert escalated.ks_history == {"tier:gumbo_l2": 1, "repair:whole-file": 1}
    assert aadl.read_bytes() == golden_copy.read_bytes()  # converged to gold
    assert "repaired from golden — verification pending" in trust_summary(bb1)
    assert bb1.entries["gumbo:contracts"].good_standing

    # episode 2: fresh caches provide the verifying evidence
    bb2 = _episode()
    assert bb2.entries["gumbo:files"].good_standing
    assert bb2.entries["gumbo:files"].result.protocol == "gumbo_l1a"
    assert not bb2.escalate


def test_block_tamper_slice_repair_verified_next_episode(live_snapshot):
    comp = (TC_ROOT / "slang/src/main/component/tc/TempControlSoftwareSystem"
                     / "TempControlPeriodic_p_tcproc_tempControl.scala")
    golden_copy = mirror_path(GOLDEN_ROOT, comp)
    lines = comp.read_text().splitlines(keepends=True)
    begin = next(i for i, l in enumerate(lines)
                 if "BEGIN COMPUTE ENSURES timeTriggered" in l)
    lines[begin + 1] = "        // TAMPERED: ensures clause weakened\n"
    comp.write_text("".join(lines))

    bb1 = _episode()

    escalated = bb1.escalate["gumbo:contracts"]
    assert escalated.ks_history == {"repair:slice": 1}
    assert comp.read_bytes() == golden_copy.read_bytes()  # block spliced back
    assert "repaired from golden — verification pending" in trust_summary(bb1)
    assert bb1.entries["gumbo:files"].good_standing  # baseline never saw it

    bb2 = _episode()
    assert bb2.entries["gumbo:contracts"].good_standing
    assert not bb2.escalate
