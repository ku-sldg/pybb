"""
End-to-end tests against the real CVM binary and asp-libs ASPs, driving the
provisioned gumbo_l1/gumbo_l2 protocols for temp-control-jvm.

Never mutates the provisioned setup: all runs (clean and tampered) execute
against a temporary copy of the watched files via path_map re-rooting.

Auto-skipped unless the CVM binary, ASP binaries, and temp-control-jvm tree
are present. Deselect explicitly with: pytest -m "not cvm".
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
    ProtocolDir,
    TrustDecisionKS,
    request_key,
    verdict_key,
)
from pybb.attestation.client import DEFAULT_ASP_BIN, DEFAULT_CVM_BINARY

FIXTURES = Path(__file__).parent / "fixtures"
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


def _watched_files() -> set[Path]:
    """Every file referenced by gumbo_l1/gumbo_l2 asp_args."""
    files = set()
    for pid in ("gumbo_l1", "gumbo_l2"):
        asp_args = json.loads((FIXTURES / pid / "asp_args.json").read_text())
        for targets in asp_args.values():
            for args in targets.values():
                fp = args.get("filepath")
                if fp:
                    files.add(Path(fp))
    return files


@pytest.fixture
def target_copy(tmp_path):
    """Copy of the watched temp-control-jvm files under a temp root."""
    root = tmp_path / "temp-control-jvm"
    for f in _watched_files():
        dest = root / f.relative_to(TC_ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
    return root


def _run(path_map):
    protocols = {
        pid: ProtocolDir.load(str(FIXTURES / pid)) for pid in ("gumbo_l1", "gumbo_l2")
    }
    ctl = BlackboardController()
    ctl.add_ks(AttestationKS(client=CvmSubprocessClient(), protocols=protocols))
    ctl.add_ks(AppraisalKS(protocols=protocols))
    ctl.add_ks(
        EscalationKS(on_fail="gumbo_l1", escalate_to="gumbo_l2", path_map=path_map)
    )
    ctl.add_ks(TrustDecisionKS())
    ctl.blackboard.write(
        key=request_key("gumbo_l1"),
        value={"protocol": "gumbo_l1", "path_map": path_map},
        source="test",
        tags=["attestation", "request"],
    )
    return ctl.run()


def test_clean_run_passes_no_escalation(target_copy):
    bb = _run({str(TC_ROOT): str(target_copy)})

    verdict = bb.read(verdict_key("gumbo_l1"))
    assert verdict is not None and verdict["passed"] is True
    assert len(verdict["components"]) == 5  # 4 hashfile_appr + sig_appr
    assert not bb.has(request_key("gumbo_l2"))
    assert bb.hypothesis.startswith("All attested components intact")


def test_tampered_contract_fails_l1_and_l2_attributes(target_copy):
    # corrupt one line inside the provisioned GUMBO contract range 305-308
    # of TempControlSystem.aadl (target tc_sys_aadl_305_308_targ)
    aadl = target_copy / "aadl/packages/TempControlSystem.aadl"
    lines = aadl.read_text().splitlines(keepends=True)
    lines[305] = "-- TAMPERED: invariant weakened\n"
    aadl.write_text("".join(lines))

    bb = _run({str(TC_ROOT): str(target_copy)})

    assert bb.read(verdict_key("gumbo_l1"))["passed"] is False
    l2 = bb.read(verdict_key("gumbo_l2"))
    assert l2 is not None, "escalation to gumbo_l2 did not run"
    assert l2["passed"] is False

    failing = {cid for cid, ok in l2["components"].items() if not ok}
    passing = {cid for cid, ok in l2["components"].items() if ok}
    assert any("tc_sys_aadl_305_308" in cid for cid in failing), failing
    # attribution, not blanket failure: untampered contracts still pass
    assert len(passing) > len(failing)
    assert "tc_sys_aadl_305_308" in (bb.hypothesis or "")
