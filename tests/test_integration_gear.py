"""
Landing-gear example end-to-end: the second Lean scenario, proving the
shared-driver claim — examples/landing_gear_lean.py is pure configuration
over examples/lean_workflow.py, and the whole workflow (scan-derived
targets, attestation, declaration-named attribution, repair, semantic
tiers, AM detection) runs unchanged against targets/landing-gear-lean.

The scenario: the classic avionics retraction interlock. The star safety
property is no_retract_on_ground (weight-on-wheels inhibits retraction);
the --tamper-semantic arc removes the interlock and is refuted by proof
(three theorems fail, `decide` refutes the on-ground case) and by
behavior (the ground vector answers Retract against expected Hold).

Hash/repair tests auto-skip unless the CVM binary and asp-libs are
present; toolchain tiers are gated behind RUN_LEAN=1.
"""

import os
import sys
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
    changed_decls,
    make_attestation_predicate,
    trust_summary,
)
from pybb.attestation.client import DEFAULT_ASP_BIN, DEFAULT_CVM_BINARY
from pybb.attestation.targetmap import derive_targets_from_lean

REPO = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN_ROOT = REPO / "golden"
GEAR_ROOT = REPO / "targets" / "landing-gear-lean"
IMPL = GEAR_ROOT / "LandingGear" / "Impl.lean"
SPEC = GEAR_ROOT / "LandingGear" / "Spec.lean"
LAKE_WRAPPER = Path.home() / "Claude_workspace/bin/lake"
PROTOCOL_IDS = ("landing_gear_lean_l1a", "landing_gear_lean_l2")
TIER_IDS = ("landing_gear_lean_check", "landing_gear_lean_exec")

pytestmark = [
    pytest.mark.cvm,
    pytest.mark.skipif(
        not (Path(DEFAULT_CVM_BINARY).is_file() and Path(DEFAULT_ASP_BIN).is_dir()),
        reason="requires local CVM binary and asp-libs binaries",
    ),
]

needs_lean = pytest.mark.skipif(
    os.environ.get("RUN_LEAN") != "1" or not LAKE_WRAPPER.is_file(),
    reason="set RUN_LEAN=1 (and install the workspace lake wrapper) "
           "to run the Lean toolchain tiers")


def _protocols(*extra: str) -> dict:
    return {pid: ProtocolDir.load(str(FIXTURES / pid))
            for pid in (*PROTOCOL_IDS, *extra)}


def test_committed_fixtures_derive_from_the_scan():
    """The syntax scan is the authority: committed target maps must equal it."""
    derived = derive_targets_from_lean(GEAR_ROOT, prefix="landing_gear_lean")
    for pid in PROTOCOL_IDS:
        committed = ProtocolDir.load(str(FIXTURES / pid)).asp_args
        for asp_id, targets in derived[pid].items():
            assert set(committed[asp_id]) == set(targets), pid
            for targ_id, args in targets.items():
                c = committed[asp_id][targ_id]
                for k, v in args.items():
                    assert c[k] == v, f"{pid}/{targ_id}/{k} diverged from scan"


def _episode(repair: bool = True):
    protocols = _protocols()
    ctl = BlackboardController()
    ctl.register_predicate(
        "attestation", make_attestation_predicate(CvmSubprocessClient(), protocols))
    chain = [TierKS(protocol_id="landing_gear_lean_l2")]
    if repair:
        chain.append(WholeFileRestoreKS(golden_root=GOLDEN_ROOT,
                                        refined_by="landing_gear_lean_l2"))
    for ks in chain:
        ctl.add_ks(ks)
    ctl.blackboard.write_entry(key="landing_gear_lean:files", predicate="attestation",
                               measurement=attestation_request("landing_gear_lean_l1a"))
    ctl.route("landing_gear_lean:files", on_fail=chain)
    ctl.run()
    return ctl.blackboard


def test_ctemp_control_lean_of_gear_package():
    bb = _episode()
    entry = bb.get_entry("landing_gear_lean:files")
    assert entry.good_standing and entry.result.protocol == "landing_gear_lean_l1a"
    # sources + lakefile.toml + lean-toolchain hashes, plus sig
    assert len(entry.result.components) == 7
    assert "all attested components intact" in trust_summary(bb)


def test_interlock_tamper_attributed_by_name_repaired_verified():
    """Corrupt the star safety theorem's proof: attribution names
    no_retract_on_ground, whole-file repair restores, episode 2 verifies."""
    snapshot = TargetSnapshot.load(_protocols(), GOLDEN_ROOT)
    targ = "landing_gear_lean_spec_no_retract_on_ground_targ"
    args = _protocols()["landing_gear_lean_l2"].asp_args["readfile_range"][targ]
    assert args["metadata"] == "LandingGear.Spec::no_retract_on_ground"
    lines = SPEC.read_text().splitlines(keepends=True)
    lines[args["end_index"] - 1] = "  -- TAMPERED: proof body removed\n"
    SPEC.write_text("".join(lines))
    try:
        bb1 = _episode()
        escalated = bb1.escalate["landing_gear_lean:files"]
        assert escalated.ks_history == {"tier:landing_gear_lean_l2": 1, "repair:whole-file": 1}
        l2v = next(e.result for k, e in bb1.get_history()
                   if k == "landing_gear_lean:files" and e.result is not None
                   and e.result.protocol == "landing_gear_lean_l2")
        assert targ in {c.targ_id for c in l2v.failing()}
        from pybb.attestation.snapshot import mirror_path
        assert SPEC.read_bytes() == mirror_path(GOLDEN_ROOT, SPEC).read_bytes()
        bb2 = _episode()
        assert bb2.entries["landing_gear_lean:files"].good_standing
        assert not bb2.escalate
    finally:
        snapshot.restore()


def test_am_detection_and_expecteds_are_config_driven():
    """The shared driver's AM machinery works off the gear config: clean
    detection against the blessing, and the exec expecteds resolve from
    the config with --expect sanction."""
    protocols = _protocols("landing_gear_lean_props")
    assert not changed_decls(protocols["landing_gear_lean_l2"], GEAR_ROOT, prefix="landing_gear_lean",
                             props_protocol=protocols["landing_gear_lean_props"])
    sys.path.insert(0, str(REPO / "examples"))
    from landing_gear_lean import EXEC_KEYS, resolved_exec_targets, vector_failures
    targets = resolved_exec_targets()
    assert [targets[f"landing_gear_lean_exec_{k}_targ"]["expected"] for k in EXEC_KEYS] \
        == ["gearCmd=Hold", "gearCmd=Retract", "gearCmd=Extend"]
    # unsanctioned behavior change (the interlock flip): the ground vector
    # diverges and the gate refuses
    failures = vector_failures(
        targets, run_vector=lambda a: "gearCmd=Retract" if "wow" in
        a["exe_args"] else targets[f"landing_gear_lean_exec_airborne_targ"]["expected"]
        if a["exe_args"][-2] == "Up" else "gearCmd=Extend")
    assert failures == ["landing_gear_lean_exec_ground_targ: expected 'gearCmd=Hold', "
                        "got 'gearCmd=Retract'"]
    assert not vector_failures(
        resolved_exec_targets({"ground": "gearCmd=Retract"}),
        run_vector=lambda a: {"wow": "gearCmd=Retract"}.get(
            a["exe_args"][-1], "gearCmd=Retract"
            if a["exe_args"][-2] == "Up" else "gearCmd=Extend"))


# ── Lean toolchain tiers (RUN_LEAN=1) ─────────────────────────────────────────

def _tier_verdict(protocol_id: str):
    protocols = _protocols(*TIER_IDS)
    predicate = make_attestation_predicate(CvmSubprocessClient(), protocols)
    return predicate(attestation_request(protocol_id))


@needs_lean
def test_proofs_and_behavior_tiers_clean_with_woven_tools():
    check = _tier_verdict("landing_gear_lean_check")
    assert check.passed, check
    tool_targs = {c.targ_id for c in check.components
                  if (c.args.get("metadata") or "").startswith("tool::lean")}
    assert len(tool_targs) == 6
    behavior = _tier_verdict("landing_gear_lean_exec")
    assert behavior.passed, behavior
    assert {"landing_gear_lean_exec_ground_targ", "landing_gear_lean_exec_airborne_targ",
            "landing_gear_lean_exec_extend_targ"} <= {c.targ_id for c in behavior.components}


@needs_lean
def test_interlock_removal_refuted_by_proof_while_pinned_binary_stands():
    """Remove the weight-on-wheels interlock in the implementation. The
    proofs refute immediately (no_retract_on_ground checks against the
    LIVE Impl); the exec tier attests the PINNED binary — still the
    blessed artifact with the interlock intact, because episodes never
    rebuild. The behavioral refutation moves to the build event, as the
    --tamper-semantic laundering arc exercises."""
    orig = IMPL.read_text()
    broken = orig.replace("| .Up, true => .Hold", "| .Up, true => .Retract")
    assert broken != orig
    IMPL.write_text(broken)
    try:
        check = _tier_verdict("landing_gear_lean_check")
        assert not check.passed
        assert any("no_retract" in (c.reason or "") or "error" in
                   (c.reason or "") for c in check.failing())
        behavior = _tier_verdict("landing_gear_lean_exec")
        assert behavior.passed  # the pinned artifact is untouched
    finally:
        IMPL.write_text(orig)
