"""
End-to-end isolette attestation via the temp-control-style (cvm-mcp)
provisioning workflow: protocol dirs generated from the HAMR attestation
report (cvm-mcp/hamr_report_protocols.py), goldens provisioned by the
dashboard flow, attested here through the CVM transport with the full
ladder + repair machinery — full parity with the gumbo demos.

Runs against a temp copy of the 13 report-named files (path_map); the
INSPECTA-models clone is never modified.
"""

import json
import shutil
from pathlib import Path

import pytest

from pybb import BlackboardController
from pybb.attestation import (
    AppraisalKS,
    AttestationKS,
    CvmSubprocessClient,
    EscalationKS,
    GoldenRestoreRepairer,
    ProtocolDir,
    RepairKS,
    TrustDecisionKS,
    request_key,
    verdict_key,
)
from pybb.attestation.client import DEFAULT_ASP_BIN, DEFAULT_CVM_BINARY

FIXTURES = Path(__file__).parent / "fixtures"
ISOLETTE_ROOT = Path("/Users/adampetz/Claude_workspace/INSPECTA-models/isolette")

pytestmark = [
    pytest.mark.cvm,
    pytest.mark.skipif(
        not (
            Path(DEFAULT_CVM_BINARY).is_file()
            and Path(DEFAULT_ASP_BIN).is_dir()
            and ISOLETTE_ROOT.is_dir()
        ),
        reason="requires CVM binary, asp-libs, and workspace isolette clone",
    ),
]


def _watched_files() -> set[Path]:
    files = set()
    for pid in ("isolette_l1", "isolette_l2"):
        asp_args = json.loads((FIXTURES / pid / "asp_args.json").read_text())
        for targets in asp_args.values():
            for args in targets.values():
                if args.get("filepath"):
                    files.add(Path(args["filepath"]))
    return files


@pytest.fixture
def target_copy(tmp_path):
    root = tmp_path / "isolette"
    for f in _watched_files():
        dest = root / f.relative_to(ISOLETTE_ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
    return root


def _run(path_map, with_repair=False):
    protocols = {
        pid: ProtocolDir.load(str(FIXTURES / pid))
        for pid in ("isolette_l1", "isolette_l2")
    }
    ctl = BlackboardController()
    ctl.add_ks(AttestationKS(client=CvmSubprocessClient(), protocols=protocols))
    ctl.add_ks(AppraisalKS(protocols=protocols))
    ctl.add_ks(EscalationKS(
        on_fail="isolette_l1", escalate_to="isolette_l2", path_map=path_map,
    ))
    if with_repair:
        ctl.add_ks(RepairKS(
            repairers=[GoldenRestoreRepairer(protocols)],
            watch=["isolette_l2"],
            reattest=["isolette_l1", "isolette_l2"],
        ))
    ctl.add_ks(TrustDecisionKS())
    ctl.blackboard.write(
        key=request_key("isolette_l1"),
        value={"protocol": "isolette_l1", "path_map": path_map},
        source="test",
        tags=["attestation", "request"],
    )
    return ctl.run()


def test_isolette_ladder_clean_pass(target_copy):
    bb = _run({str(ISOLETTE_ROOT): str(target_copy)})

    verdict = bb.read(verdict_key("isolette_l1"))
    assert verdict is not None and verdict["passed"] is True, verdict
    assert len(verdict["components"]) == 14  # 13 hashfile + sig
    assert not bb.has(request_key("isolette_l2"))
    assert bb.hypothesis.startswith("All attested components intact")


def test_isolette_tamper_attributed_and_repaired(target_copy):
    # tamper inside the RegulatorStatusIsInitiallyInit guarantee clause
    # (Regulate.aadl lines 217-218, target isolette_regulate_217_218_targ)
    aadl = target_copy / "aadl/aadl/packages/Regulate.aadl"
    original = aadl.read_bytes()
    lines = aadl.read_text().splitlines(keepends=True)
    lines[217] = lines[217].replace("Init_Status", "On_Status")
    aadl.write_text("".join(lines))
    assert aadl.read_bytes() != original

    bb = _run({str(ISOLETTE_ROOT): str(target_copy)}, with_repair=True)

    # ladder attributed, repair restored byte-exactly, re-attestation clean
    assert aadl.read_bytes() == original
    l2_verdicts = [
        e.value for e in bb.history if e.key == verdict_key("isolette_l2")
    ]
    assert [v["passed"] for v in l2_verdicts] == [False, True]
    failing = {c for c, ok in l2_verdicts[0]["components"].items() if not ok}
    assert any("isolette_regulate_217_218" in c for c in failing), failing
    assert bb.read("repair.attempts/isolette_l2") == 1
    assert "detected and repaired (1 attempt)" in bb.hypothesis
