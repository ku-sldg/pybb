"""
End-to-end tests against the real CVM binary and asp-libs ASPs, driving the
provisioned gumbo_l1/gumbo_l2 protocols for temp-control-jvm on the routed
blackboard.

Decision tree under test: l1 pass = done (no confirmation tier configured
here — see test_integration_sireum for that); l1 fail -> l2 attribution;
l2 fail -> escalate with the l2 report.

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
    CvmSubprocessClient,
    ProtocolDir,
    TierKS,
    attestation_request,
    make_attestation_predicate,
    trust_summary,
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
    ctl.register_predicate(
        "attestation",
        make_attestation_predicate(CvmSubprocessClient(), protocols),
    )
    rungs = [TierKS(protocol_id="gumbo_l2")]
    for ks in rungs:
        ctl.add_ks(ks)
    ctl.blackboard.write_entry(
        key="gumbo", predicate="attestation",
        measurement=attestation_request("gumbo_l1", path_map=path_map),
    )
    ctl.route("gumbo", on_fail=rungs)
    ctl.run()
    return ctl.blackboard


def test_clean_run_passes_no_escalation(target_copy):
    bb = _run({str(TC_ROOT): str(target_copy)})

    entry = bb.get_entry("gumbo")
    assert entry is not None and entry.good_standing
    assert entry.result.protocol == "gumbo_l1"
    assert len(entry.result.components) == 5  # 4 hashfile_appr + sig_appr
    assert entry.ks_history == {}  # l2 rung never fired
    assert "all attested components intact" in trust_summary(bb)


def test_tampered_contract_fails_l1_and_l2_attributes(target_copy):
    # corrupt one line inside the provisioned GUMBO contract range 305-308
    # of TempControlSystem.aadl (target tc_sys_aadl_305_308_targ)
    aadl = target_copy / "aadl/packages/TempControlSystem.aadl"
    lines = aadl.read_text().splitlines(keepends=True)
    lines[305] = "-- TAMPERED: invariant weakened\n"
    aadl.write_text("".join(lines))

    bb = _run({str(TC_ROOT): str(target_copy)})

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
