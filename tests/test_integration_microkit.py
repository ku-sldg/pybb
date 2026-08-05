"""
Microkit/Rust example end-to-end: the HAMR attestation report is the
authoritative source of targets and golden slices (tcmk_l1a/tcmk_l2 are
generated from it, never hand-curated); attestation runs against the
vendored targets/temp-control-microkit tree; a tampered Verus contract
slice is detected, attributed, whole-file repaired from golden, and
verified clean by the next episode.

Auto-skipped unless the CVM binary and asp-libs are present (the vendored
tree and report ship with the repo).
"""

from pathlib import Path

import pytest

from pybb import BlackboardController
from pybb.attestation import (
    CvmSubprocessClient,
    ProtocolDir,
    TargetSnapshot,
    TierKS,
    WholeFileRestoreKS,
    attestation_request,
    make_attestation_predicate,
    trust_summary,
)
from pybb.attestation.client import DEFAULT_ASP_BIN, DEFAULT_CVM_BINARY
from pybb.attestation.targetmap import derive_targets_from_report

REPO = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN_ROOT = REPO / "golden"
REPORT = (REPO / "targets" / "temp-control-microkit" / "hamr" / "microkit"
          / "attestation" / "aadl_attestation_report.json")
PROTOCOL_IDS = ("tcmk_l1a", "tcmk_l2")

pytestmark = [
    pytest.mark.cvm,
    pytest.mark.skipif(
        not (Path(DEFAULT_CVM_BINARY).is_file() and Path(DEFAULT_ASP_BIN).is_dir()),
        reason="requires local CVM binary and asp-libs binaries",
    ),
]


def _protocols() -> dict:
    return {pid: ProtocolDir.load(str(FIXTURES / pid)) for pid in PROTOCOL_IDS}


def test_committed_fixtures_derive_from_the_report():
    """The report is the authority: committed target maps must equal it."""
    derived = derive_targets_from_report(REPORT, prefix="tcmk")
    for pid in PROTOCOL_IDS:
        committed = ProtocolDir.load(str(FIXTURES / pid)).asp_args
        for asp_id, targets in derived[pid].items():
            for targ_id, args in targets.items():
                c = committed[asp_id][targ_id]
                for k, v in args.items():
                    assert c[k] == v, f"{pid}/{targ_id}/{k} diverged from report"


@pytest.fixture
def live_snapshot():
    snapshot = TargetSnapshot.load(_protocols(), GOLDEN_ROOT)
    try:
        yield snapshot
    finally:
        snapshot.restore()


def _episode(repair: bool = True):
    protocols = _protocols()
    ctl = BlackboardController()
    ctl.register_predicate(
        "attestation", make_attestation_predicate(CvmSubprocessClient(), protocols))
    chain = [TierKS(protocol_id="tcmk_l2")]
    if repair:
        chain.append(WholeFileRestoreKS(golden_root=GOLDEN_ROOT,
                                        refined_by="tcmk_l2"))
    for ks in chain:
        ctl.add_ks(ks)
    ctl.blackboard.write_entry(key="tcmk:files", predicate="attestation",
                               measurement=attestation_request("tcmk_l1a"))
    ctl.route("tcmk:files", on_fail=chain)
    ctl.run()
    return ctl.blackboard


def test_ctemp_control_lean_of_rust_artifacts():
    bb = _episode()
    entry = bb.get_entry("tcmk:files")
    assert entry.good_standing and entry.result.protocol == "tcmk_l1a"
    assert len(entry.result.components) == 5  # 4 hashfile + sig
    assert "all attested components intact" in trust_summary(bb)


def test_verus_slice_tamper_attributed_repaired_verified(live_snapshot):
    l2 = _protocols()["tcmk_l2"].asp_args["readfile_range"]
    targ, args = next((t, a) for t, a in sorted(l2.items())
                      if a["filepath"].endswith("tcproc_tempControl_app.rs"))
    rs = Path(args["filepath"])
    lines = rs.read_text().splitlines(keepends=True)
    lines[args["start_index"] - 1] = "// TAMPERED: verus contract weakened\n"
    rs.write_text("".join(lines))

    bb1 = _episode()

    escalated = bb1.escalate["tcmk:files"]
    assert escalated.ks_history == {"tier:tcmk_l2": 1, "repair:whole-file": 1}
    l2v = next(e.result for k, e in bb1.get_history()
               if k == "tcmk:files" and e.result is not None
               and e.result.protocol == "tcmk_l2")
    assert targ in {c.targ_id for c in l2v.failing()}
    from pybb.attestation.snapshot import mirror_path
    assert rs.read_bytes() == mirror_path(GOLDEN_ROOT, rs).read_bytes()
    assert "repaired from golden — verification pending" in trust_summary(bb1)

    bb2 = _episode()
    assert bb2.entries["tcmk:files"].good_standing
    assert not bb2.escalate
