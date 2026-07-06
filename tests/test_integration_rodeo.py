"""
End-to-end rodeo-transport run against the provisioned isolette attestation
root (INSPECTA-models sparse clone in the workspace).

Prerequisite (out-of-band provisioning, run once from a known-good tree):

    cd ~/Claude_workspace/rust-am-clients && ASP_BIN=~/Claude_workspace/asp-libs/target/release \\
    ./target/release/rust-rodeo-client \\
      --cvm-filepath ~/Claude_workspace/cvm/_build/default/theories/cvm \\
      --hamr-report-filepath $ROOT/aadl_attestation_report.json \\
      --manifest-filepath testing/manifests/Manifest_P0.json \\
      --session-filepath rodeo_configs/sessions/session_union.json \\
      --provisioned-evidence-filepath $ROOT/hamr_maestro_golden_evidence.json

Auto-skipped when the provisioned term or binaries are absent.
"""

from pathlib import Path

import pytest

from pybb import BlackboardController
from pybb.attestation import (
    AppraisalKS,
    AttestationKS,
    RodeoConfig,
    RodeoProtocol,
    RodeoSubprocessClient,
    TrustDecisionKS,
    request_key,
    verdict_key,
)

ISOLETTE_ROOT = Path.home() / (
    "Claude_workspace/INSPECTA-models/isolette/hamr/microkit/attestation"
)
RODEO_BIN = Path(RodeoConfig().rodeo_binary)

pytestmark = [
    pytest.mark.cvm,
    pytest.mark.skipif(
        not (RODEO_BIN.is_file() and (ISOLETTE_ROOT / "hamr_maestro_term.json").is_file()),
        reason="requires rodeo binary and provisioned isolette attestation root",
    ),
]


def _run_isolette():
    protocols = {"isolette": RodeoProtocol.load(str(ISOLETTE_ROOT), protocol_id="isolette")}
    ctl = BlackboardController()
    ctl.add_ks(AttestationKS(client=RodeoSubprocessClient(), protocols=protocols))
    ctl.add_ks(AppraisalKS(protocols=protocols))
    ctl.add_ks(TrustDecisionKS())
    ctl.blackboard.write(
        key=request_key("isolette"),
        value={"protocol": "isolette"},
        source="test",
        tags=["attestation", "request"],
    )
    return ctl.run()


def test_isolette_rodeo_tamper_fails_contract_slices():
    """Tamper a measured GUMBO contract slice; restore via git afterwards."""
    import subprocess

    repo = Path.home() / "Claude_workspace/INSPECTA-models"
    target = repo / "isolette/aadl/aadl/packages/Monitor.aadl"
    original = target.read_text()
    try:
        # line 192 is inside the measured slice for monitorStatusInitiallyInit
        lines = original.splitlines(keepends=True)
        lines[191] = lines[191].rstrip("\n") + " -- TAMPERED\n"
        target.write_text("".join(lines))
        assert target.read_text() != original, "tamper marker not applied"
        bb = _run_isolette()
        verdict = bb.read(verdict_key("isolette"))
        assert verdict["passed"] is False, verdict
        failing = [cid for cid, ok in verdict["components"].items() if not ok]
        assert any("readfile_range_many" in cid for cid in failing), verdict
        assert "integrity violation" in bb.hypothesis
    finally:
        target.write_text(original)
        subprocess.run(
            ["git", "-C", str(repo), "diff", "--quiet", "--", str(target)],
            check=True,
        )


def test_isolette_rodeo_appraisal_clean_pass():
    bb = _run_isolette()

    verdict = bb.read(verdict_key("isolette"))
    assert verdict is not None and verdict["passed"] is True, verdict
    # HAMR contract slices + signature, each appraised as one component
    assert len(verdict["components"]) == 2
    assert bb.hypothesis.startswith("All attested components intact")
