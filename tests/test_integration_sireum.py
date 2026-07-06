"""
End-to-end gumbo_validation run: the CVM forks run_command_hamr five times
(sireum proyek tipe, logika x2, test x2 against temp-control-jvm/slang),
appraised by exit code.

Takes minutes. Gated behind RUN_SIREUM=1 in addition to the cvm marker so a
plain `pytest` stays fast.
"""

import os
from pathlib import Path

import pytest

from pybb import BlackboardController
from pybb.attestation import (
    AppraisalKS,
    AttestationKS,
    CvmSubprocessClient,
    ProtocolDir,
    TrustDecisionKS,
    request_key,
    verdict_key,
)
from pybb.attestation.client import DEFAULT_CVM_BINARY, DEFAULT_PATH_PREPEND

FIXTURES = Path(__file__).parent / "fixtures"
SIREUM_WRAPPER = Path.home() / "Claude_workspace/bin/sireum"

pytestmark = [
    pytest.mark.cvm,
    pytest.mark.sireum,
    pytest.mark.skipif(
        os.environ.get("RUN_SIREUM") != "1",
        reason="set RUN_SIREUM=1 to run multi-minute Sireum validation",
    ),
    pytest.mark.skipif(
        not (Path(DEFAULT_CVM_BINARY).is_file() and SIREUM_WRAPPER.is_file()),
        reason="requires CVM binary and workspace sireum wrapper",
    ),
]


def test_gumbo_validation_clean_pass():
    protocols = {
        "gumbo_validation": ProtocolDir.load(str(FIXTURES / "gumbo_validation"))
    }
    ctl = BlackboardController()
    ctl.add_ks(AttestationKS(client=CvmSubprocessClient(), protocols=protocols))
    ctl.add_ks(AppraisalKS(protocols=protocols))
    ctl.add_ks(TrustDecisionKS(semantic=["gumbo_validation"]))
    ctl.blackboard.write(
        key=request_key("gumbo_validation"),
        value={"protocol": "gumbo_validation"},
        source="test",
        tags=["attestation", "request"],
    )
    bb = ctl.run()

    verdict = bb.read(verdict_key("gumbo_validation"))
    assert verdict is not None and verdict["passed"] is True, verdict
    assert len(verdict["components"]) == 5
    assert any("proyek logika" in cid for cid in verdict["components"])
    assert any("proyek test" in cid for cid in verdict["components"])
    assert bb.hypothesis.startswith("All attested components intact")

    # environment check: CVM children saw the workspace PATH prepend
    assert DEFAULT_PATH_PREPEND, "workspace bin dir missing from PATH prepend"
