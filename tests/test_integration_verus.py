"""
Semantic tier for the Microkit/Rust pipeline: cargo-verus verification of
the generated Verus contracts, run as a CVM protocol (run_command_cargo_verus
ASP, appraised by run_command_verus_appr on the JSON error count) and
routed as the on_pass confirmation of the tcmk:files entry.

Also the scenario only this tier can catch: a behavior change laundered
through re-provisioning — attestation sees matching gold, Verus proves the
implementation no longer meets its contracts.

Gated behind RUN_VERUS=1 (multi-minute); also needs the Verus toolchain
wrapper, cargo, and the CVM stack.
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
from pybb.attestation.client import DEFAULT_CVM_BINARY

FIXTURES = Path(__file__).parent / "fixtures"
REPO = Path(__file__).parent.parent
CARGO_VERUS_WRAPPER = Path.home() / "Claude_workspace/bin/cargo-verus"
APP_RS = (REPO / "targets/temp-control-microkit/hamr/microkit/crates"
          / "tcproc_tempControl/src/component/tcproc_tempControl_app.rs")

pytestmark = [
    pytest.mark.cvm,
    pytest.mark.sireum,  # reuse the "slow, gated" marker family
    pytest.mark.skipif(os.environ.get("RUN_VERUS") != "1",
                       reason="set RUN_VERUS=1 to run multi-minute Verus tier"),
    pytest.mark.skipif(
        not (Path(DEFAULT_CVM_BINARY).is_file() and CARGO_VERUS_WRAPPER.is_file()),
        reason="requires CVM binary and workspace cargo-verus wrapper",
    ),
]


def _protocols() -> dict:
    return {pid: ProtocolDir.load(str(FIXTURES / pid))
            for pid in ("tcmk_l1a", "tcmk_l2", "tcmk_verus")}


def test_l1a_pass_confirmed_by_verus():
    protocols = _protocols()
    ctl = BlackboardController()
    ctl.register_predicate(
        "attestation", make_attestation_predicate(CvmSubprocessClient(), protocols))
    confirm = TierKS(protocol_id="tcmk_verus")
    ctl.add_ks(confirm)
    ctl.blackboard.write_entry(key="tcmk:files", predicate="attestation",
                               measurement=attestation_request("tcmk_l1a"))
    ctl.route("tcmk:files", on_pass=[confirm])
    bb = ctl.run()

    entry = bb.get_entry("tcmk:files")
    assert entry is not None and entry.good_standing, entry
    assert entry.result.protocol == "tcmk_verus"
    assert {c.targ_id for c in entry.result.components} == \
        {"tc_verus_targ", "ts_verus_targ"}
    assert "tcmk_l1a passed; confirmed by tcmk_verus" in \
        trust_summary(bb, semantic=["tcmk_verus"])


def test_laundered_behavior_change_refuted_by_verus():
    orig = APP_RS.read_text()
    broken = orig.replace(
        "self.latestFanCmd = newCmd;\n      api.put_fanCmd(newCmd);",
        "self.latestFanCmd = newCmd;\n      api.put_fanCmd(CoolingFan::FanCmd::On);")
    assert broken != orig
    APP_RS.write_text(broken)
    try:
        protocols = _protocols()
        verdict = make_attestation_predicate(CvmSubprocessClient(), protocols)(
            attestation_request("tcmk_verus"))
        assert not verdict.passed
        assert "tc_verus_targ" in {c.targ_id for c in verdict.failing()}
    finally:
        APP_RS.write_text(orig)
