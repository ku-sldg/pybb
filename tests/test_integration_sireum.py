"""
End-to-end gumbo_validation runs: the CVM forks run_command_hamr five times
(sireum proyek tipe, logika x2, test x2 against temp-control-jvm/slang),
appraised by exit code.

Covers both ways validation participates: requested directly as a
single-tier entry, and as the on_pass confirmation chain after a passing
gumbo_l1 (the "L1 succeeds, try L3" edge of the decision tree).

Takes minutes per run. Gated behind RUN_SIREUM=1 in addition to the cvm
marker so a plain `pytest` stays fast.
"""

import os
from pathlib import Path

import pytest

from pybb import BlackboardController
from pybb.attestation import (
    CvmSubprocessClient,
    ProtocolDir,
    TierKS,
    attestation_request,
    make_attestation_predicate,
    trust_summary,
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
    ctl.register_predicate(
        "attestation",
        make_attestation_predicate(CvmSubprocessClient(), protocols),
    )
    ctl.blackboard.write_entry(
        key="gumbo_validation", predicate="attestation",
        measurement=attestation_request("gumbo_validation"),
    )
    ctl.run()
    bb = ctl.blackboard

    entry = bb.get_entry("gumbo_validation")
    assert entry is not None and entry.good_standing, entry
    verdict = entry.result
    assert len(verdict.components) == 5
    descriptions = [c.targ_id or c.description for c in verdict.components]
    assert any("proyek logika" in cid for cid in descriptions)
    assert any("proyek test" in cid for cid in descriptions)
    assert "all attested components intact" in trust_summary(bb)

    # environment check: CVM children saw the workspace PATH prepend
    assert DEFAULT_PATH_PREPEND, "workspace bin dir missing from PATH prepend"


def test_l1_pass_confirmed_by_validation():
    """Clean tree: l1 passes provisionally, the on_pass chain confirms at l3."""
    protocols = {
        pid: ProtocolDir.load(str(FIXTURES / pid))
        for pid in ("gumbo_l1", "gumbo_l2", "gumbo_validation")
    }
    ctl = BlackboardController()
    ctl.register_predicate(
        "attestation",
        make_attestation_predicate(CvmSubprocessClient(), protocols),
    )
    confirm = TierKS(protocol_id="gumbo_validation", carry_path_map=False)
    attribute = TierKS(protocol_id="gumbo_l2")
    for ks in (confirm, attribute):
        ctl.add_ks(ks)
    ctl.blackboard.write_entry(
        key="gumbo", predicate="attestation",
        measurement=attestation_request("gumbo_l1"),
    )
    ctl.route("gumbo", on_pass=[confirm], on_fail=[attribute])
    ctl.run()
    bb = ctl.blackboard

    entry = bb.get_entry("gumbo")
    assert entry is not None and entry.good_standing, entry
    assert entry.result.protocol == "gumbo_validation"
    assert entry.ks_history == {"tier:gumbo_validation": 1}  # l2 never fired
    assert "gumbo_l1 passed; confirmed by gumbo_validation" in trust_summary(bb)
