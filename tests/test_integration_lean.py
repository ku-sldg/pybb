"""
Lean example end-to-end: the syntax scan is the authoritative source of
targets (temp_control_lean_l1a/temp_control_lean_l2 derive from targets/temp-control-lean, never
hand-curated); attestation runs against the vendored Lake package; a
tampered theorem slice is detected, attributed by declaration name,
whole-file repaired from golden, and verified clean by the next episode.

The semantic tiers are gated behind RUN_LEAN=1 (they invoke the Lean
toolchain via the workspace lake wrapper): temp_control_lean_check re-elaborates the
specification (`lake lean TempControl/Spec.lean -- --json` — a sorry
exits 0 and only WARNS, so the appraiser's hasSorry handling is what
catches it), and temp_control_lean_exec runs the built binary on one vector per GUMBO
case. Main imports only TempControl.Impl, so provability and behavior
are independent: a sorry fails proofs but not behavior, and a laundered
implementation change is refuted by BOTH tiers even though every hash
measurement blesses it.

Hash/repair tests auto-skip unless the CVM binary and asp-libs are
present (the vendored tree ships with the repo).
"""

import base64
import os
import shutil
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
    make_promotion_predicate,
    make_provision_predicate,
    make_readiness_predicate,
    promotion_request,
    readiness_request,
    request_provision,
    trust_summary,
)
from pybb.attestation.client import DEFAULT_ASP_BIN, DEFAULT_CVM_BINARY
from pybb.attestation.targetmap import derive_targets_from_lean

REPO = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN_ROOT = REPO / "golden"
LEAN_ROOT = REPO / "targets" / "temp-control-lean"
IMPL = LEAN_ROOT / "TempControl" / "Impl.lean"
SPEC = LEAN_ROOT / "TempControl" / "Spec.lean"
LAKE_WRAPPER = Path.home() / "Claude_workspace/bin/lake"
PROTOCOL_IDS = ("temp_control_lean_l1a", "temp_control_lean_l2")
TIER_IDS = ("temp_control_lean_check", "temp_control_lean_exec")

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
    derived = derive_targets_from_lean(LEAN_ROOT, prefix="temp_control_lean")
    for pid in PROTOCOL_IDS:
        committed = ProtocolDir.load(str(FIXTURES / pid)).asp_args
        for asp_id, targets in derived[pid].items():
            assert set(committed[asp_id]) == set(targets), pid
            for targ_id, args in targets.items():
                c = committed[asp_id][targ_id]
                for k, v in args.items():
                    assert c[k] == v, f"{pid}/{targ_id}/{k} diverged from scan"


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
    chain = [TierKS(protocol_id="temp_control_lean_l2")]
    if repair:
        chain.append(WholeFileRestoreKS(golden_root=GOLDEN_ROOT,
                                        refined_by="temp_control_lean_l2"))
    for ks in chain:
        ctl.add_ks(ks)
    ctl.blackboard.write_entry(key="temp_control_lean:files", predicate="attestation",
                               measurement=attestation_request("temp_control_lean_l1a"))
    ctl.route("temp_control_lean:files", on_fail=chain)
    ctl.run()
    return ctl.blackboard


def test_ctemp_control_lean_of_lean_package():
    bb = _episode()
    entry = bb.get_entry("temp_control_lean:files")
    assert entry.good_standing and entry.result.protocol == "temp_control_lean_l1a"
    # sources + lakefile.toml + lean-toolchain hashes, plus sig
    assert len(entry.result.components) == 7
    assert "all attested components intact" in trust_summary(bb)


def test_theorem_tamper_attributed_by_name_repaired_verified(live_snapshot):
    targ = "temp_control_lean_spec_fanOn_when_hot_targ"
    args = _protocols()["temp_control_lean_l2"].asp_args["readfile_range"][targ]
    assert args["metadata"] == "TempControl.Spec::fanOn_when_hot"
    lines = SPEC.read_text().splitlines(keepends=True)
    lines[args["end_index"] - 1] = "  -- TAMPERED: proof body removed\n"
    SPEC.write_text("".join(lines))

    bb1 = _episode()

    escalated = bb1.escalate["temp_control_lean:files"]
    assert escalated.ks_history == {"tier:temp_control_lean_l2": 1, "repair:whole-file": 1}
    l2v = next(e.result for k, e in bb1.get_history()
               if k == "temp_control_lean:files" and e.result is not None
               and e.result.protocol == "temp_control_lean_l2")
    assert targ in {c.targ_id for c in l2v.failing()}
    from pybb.attestation.snapshot import mirror_path
    assert SPEC.read_bytes() == mirror_path(GOLDEN_ROOT, SPEC).read_bytes()
    assert "repaired from golden — verification pending" in trust_summary(bb1)

    bb2 = _episode()
    assert bb2.entries["temp_control_lean:files"].good_standing
    assert not bb2.escalate


# ── Lean toolchain tiers (RUN_LEAN=1) ─────────────────────────────────────────

def _tier_verdict(protocol_id: str):
    protocols = _protocols(*TIER_IDS)
    predicate = make_attestation_predicate(CvmSubprocessClient(), protocols)
    return predicate(attestation_request(protocol_id))


@needs_lean
def test_proofs_and_behavior_tiers_clean_with_woven_tools():
    check = _tier_verdict("temp_control_lean_check")
    assert check.passed, check
    check_targs = {c.targ_id for c in check.components}
    assert "temp_control_lean_spec_check_targ" in check_targs
    # the lean toolchain was measured in the same term, before the use
    tool_targs = {c.targ_id for c in check.components
                  if (c.args.get("metadata") or "").startswith("tool::lean")}
    assert len(tool_targs) == 6
    behavior = _tier_verdict("temp_control_lean_exec")
    assert behavior.passed, behavior
    assert {"temp_control_lean_exec_hot_targ", "temp_control_lean_exec_cold_targ",
            "temp_control_lean_exec_hold_targ"} <= {c.targ_id for c in behavior.components}


@needs_lean
def test_tampered_tool_on_invocation_chain_fails_both_tiers():
    """Measure-then-use: a modified artifact on the lean invocation chain
    (the workspace wrapper) makes BOTH tier verdicts untrustworthy —
    attributed to the tool target, regardless of what the tool outputs."""
    orig = LAKE_WRAPPER.read_bytes()
    LAKE_WRAPPER.write_bytes(orig + b"\n# TAMPERED: altered after blessing\n")
    try:
        check = _tier_verdict("temp_control_lean_check")
        assert not check.passed
        assert {c.targ_id for c in check.failing()} == {"tool_lean_lake_targ"}
        behavior = _tier_verdict("temp_control_lean_exec")
        assert not behavior.passed
        assert {c.targ_id for c in behavior.failing()} == {"tool_lean_lake_targ"}
    finally:
        LAKE_WRAPPER.write_bytes(orig)
    assert _tier_verdict("temp_control_lean_check").passed


@needs_lean
def test_sorry_fails_proofs_but_not_behavior():
    """A sorry exits 0 and only warns — and does not change behavior: the
    check tier must refute it while the exec tier still passes."""
    orig = SPEC.read_text()
    broken = orig.replace("  simp [computeFanCmd, h]\n", "  sorry\n", 1)
    assert broken != orig
    SPEC.write_text(broken)
    try:
        check = _tier_verdict("temp_control_lean_check")
        assert not check.passed
        assert any("hasSorry" in c.reason for c in check.failing())
        assert _tier_verdict("temp_control_lean_exec").passed  # Main never elaborates Spec
    finally:
        SPEC.write_text(orig)


@needs_lean
def test_impl_change_refuted_by_proof_while_pinned_binary_stands():
    """Flip the hot branch of the implementation. The proofs refute
    immediately (theorems are checked against the LIVE Impl); the exec
    tier attests the PINNED binary — which is still the blessed artifact
    with the correct behavior, because episodes never rebuild. The
    behavioral refutation moves to the build event: laundering that
    re-runs the build produces a flipped binary that fails the hot vector
    (the --tamper-semantic arc exercises exactly that)."""
    orig = IMPL.read_text()
    broken = orig.replace("if temp > sp.high then .On",
                          "if temp > sp.high then .Off")
    assert broken != orig
    IMPL.write_text(broken)
    try:
        check = _tier_verdict("temp_control_lean_check")
        assert not check.passed
        behavior = _tier_verdict("temp_control_lean_exec")
        assert behavior.passed  # the pinned artifact is untouched
    finally:
        IMPL.write_text(orig)


@needs_lean
def test_swapped_binary_fails_behavior_tier_before_its_output_matters():
    """Hash-then-run: a replaced executable fails the behavior tier at the
    binary target — its hash cannot match the build-anchored golden —
    regardless of what the replacement prints."""
    BIN = LEAN_ROOT / ".lake" / "build" / "bin" / "temp-control"
    orig = BIN.read_bytes()
    BIN.write_bytes(b"#!/bin/sh\necho fanCmd=On\n")
    BIN.chmod(0o755)
    try:
        behavior = _tier_verdict("temp_control_lean_exec")
        assert not behavior.passed
        assert "temp_control_lean_bin_temp_control_targ" in \
            {c.targ_id for c in behavior.failing()}
    finally:
        BIN.write_bytes(orig)
        BIN.chmod(0o755)
    assert _tier_verdict("temp_control_lean_exec").passed


# ── signed golden spec (props): the administrator-blessed Spec.lean ───────────

def test_props_blesses_the_spec_and_anchors_are_not_vacuous():
    from pybb.attestation import verify_bundle
    from pybb.attestation.baseline import _build_anchors

    protocols = _protocols("temp_control_lean_props")
    committed = protocols["temp_control_lean_props"].asp_args["readfile"]
    assert [a["filepath"] for a in committed.values()] == [str(SPEC)]
    assert all(a.get("golden_b64") for a in committed.values())
    # the blessed spec anchors its hash golden AND every declaration slice
    # temp_control_lean_l2 installs for Spec.lean (theorems, invariant, examples)
    anchors = _build_anchors(protocols)
    assert anchors[str(SPEC)].get("hash_golden_b64")
    assert len(anchors[str(SPEC)]["slices"]) == 8
    report = verify_bundle(CvmSubprocessClient(), protocols["temp_control_lean_props"],
                           GOLDEN_ROOT, anchor_protocols=protocols)
    assert report, report.problems
    assert report.anchored == ["temp_control_lean_props_spec_targ"]


def test_laundered_theorem_refuted_by_blessing():
    """Tamper a theorem in the GOLDEN tree and re-provision the measurement
    protocols: their baselines re-sign self-consistently and verify — only
    the administrator's blessing of Spec.lean (not re-provisioned) refutes
    the laundered goldens."""
    from pybb import BlackboardController
    from pybb.attestation import (make_provision_predicate,
                                  make_readiness_predicate, readiness_request,
                                  request_provision)

    pids = ["temp_control_lean_l1a", "temp_control_lean_l2", "temp_control_lean_props"]
    protocols = {p: ProtocolDir.load(str(FIXTURES / p)) for p in pids}
    client = CvmSubprocessClient()
    args = protocols["temp_control_lean_l2"].asp_args["readfile_range"][
        "temp_control_lean_spec_fanOn_when_hot_targ"]
    gold = Path("golden" + args["filepath"])
    orig = gold.read_bytes()

    def reprovision():
        ctl = BlackboardController()
        sub = {p: protocols[p] for p in ("temp_control_lean_l1a", "temp_control_lean_l2")}
        ctl.register_predicate("provision",
                               make_provision_predicate(client, sub, GOLDEN_ROOT))
        for p in sub:
            request_provision(ctl.blackboard, p)
        bb = ctl.run()
        assert not bb.get_escalate(), bb.get_escalate()

    lines = gold.read_text().splitlines(keepends=True)
    lines[args["start_index"]] = "    computeFanCmd temp sp latest = .Off := by\n"
    gold.write_text("".join(lines))
    try:
        reprovision()
        report = make_readiness_predicate(
            protocols, baseline_root=GOLDEN_ROOT,
            client=CvmSubprocessClient())(readiness_request(pids))
        assert not report
        assert report.baseline_verified == ["temp_control_lean_l1a", "temp_control_lean_l2"]
        assert any("temp_control_lean_props" in p and "not derivable from blessed content" in p
                   for p in report.baseline_problems)
    finally:
        gold.write_bytes(orig)
        reprovision()
    report = make_readiness_predicate(
        protocols, baseline_root=GOLDEN_ROOT,
        client=CvmSubprocessClient())(readiness_request(pids))
    assert report, (report.problems, report.baseline_problems)


# ── sanctioned change: --check / --promote (the out-of-band AM) ───────────────

SANCTIONED_THEOREM = '''\
/-- Safety: the fan is only ever Off because the temperature permits it
    or because it was already Off. -/
theorem fanOff_only_if_cold_or_held (temp : Int) (sp : SetPoint) (latest : FanCmd) :
    computeFanCmd temp sp latest = .Off → temp < sp.low ∨ latest = .Off := by
  unfold computeFanCmd
  split
  next => exact fun h => FanCmd.noConfusion h
  next =>
    split
    next hcold => exact fun _ => Or.inl hcold
    next => exact fun h => Or.inr h

'''
_ANCHOR = "-- Executable sanity checks (kernel-evaluated)."


@pytest.fixture
def sanctioned_edit():
    """Add the dual safety theorem to the live spec; restore after."""
    orig = SPEC.read_text()
    SPEC.write_text(orig.replace(_ANCHOR, SANCTIONED_THEOREM + _ANCHOR, 1))
    try:
        yield
    finally:
        SPEC.write_text(orig)


def test_changed_decls_clean_tree_reports_nothing():
    protocols = _protocols("temp_control_lean_props")
    diff = changed_decls(protocols["temp_control_lean_l2"], LEAN_ROOT,
                         props_protocol=protocols["temp_control_lean_props"])
    assert not diff, diff


def test_changed_decls_names_the_added_theorem_and_moves(sanctioned_edit):
    protocols = _protocols("temp_control_lean_props")
    diff = changed_decls(protocols["temp_control_lean_l2"], LEAN_ROOT,
                         props_protocol=protocols["temp_control_lean_props"])
    assert diff.added == ["TempControl.Spec::fanOff_only_if_cold_or_held"]
    # the three examples below the insertion shifted: moved, not changed
    assert len(diff.moved) == 3 and all("example" in m for m in diff.moved)
    assert not diff.modified and not diff.removed


def test_check_sees_through_laundered_l2_goldens(sanctioned_edit):
    """Re-provisioning over an unsanctioned edit re-blesses the l2 golden
    slices — against those alone the diff vanishes. The blessed spec bytes
    (temp_control_lean_props) are not launderable, so detection against the blessing
    still names the change."""
    from pybb.attestation.targetmap import derive_targets_from_lean

    protocols = _protocols("temp_control_lean_props")
    live = derive_targets_from_lean(LEAN_ROOT, prefix="temp_control_lean")["temp_control_lean_l2"]["readfile_range"]
    for args in live.values():
        lines = Path(args["filepath"]).read_text().splitlines()
        flat = "".join(lines[args["start_index"] - 1:args["end_index"]])
        args["golden_b64"] = base64.b64encode(flat.encode()).decode()
    laundered = protocols["temp_control_lean_l2"].model_copy(deep=True)
    laundered.asp_args = {"readfile_range": live}

    assert not changed_decls(laundered, LEAN_ROOT, prefix="temp_control_lean")  # the laundering "works"...
    diff = changed_decls(laundered, LEAN_ROOT,
                         props_protocol=protocols["temp_control_lean_props"])
    assert diff.added == ["TempControl.Spec::fanOff_only_if_cold_or_held"]


def test_exec_expecteds_are_am_config_with_promote_time_sanction():
    """The behavior gate compares against AM-owned expecteds; --expect is
    the only way to sanction a behavior change."""
    sys.path.insert(0, str(REPO / "examples"))
    from temp_control_lean import (EXEC_KEYS, resolved_exec_targets,
                                  vector_failures)

    targets = resolved_exec_targets()
    assert [targets[f"temp_control_lean_exec_{k}_targ"]["expected"] for k in EXEC_KEYS] \
        == ["fanCmd=On", "fanCmd=Off", "fanCmd=On"]
    # unsanctioned behavior change: the gate names every diverging vector
    failures = vector_failures(targets, run_vector=lambda a: "fanCmd=Off")
    assert len(failures) == 2
    assert all("expected 'fanCmd=On', got 'fanCmd=Off'" in f for f in failures)
    # the sanctioning knob
    sanctioned = resolved_exec_targets({"hot": "fanCmd=Off",
                                        "hold": "fanCmd=Off"})
    assert not vector_failures(sanctioned, run_vector=lambda a: "fanCmd=Off")
    with pytest.raises(SystemExit):
        resolved_exec_targets({"tepid": "fanCmd=On"})


@needs_lean
def test_sanctioned_spec_change_promoted_and_reblessed(tmp_path, sanctioned_edit):
    """The full sanctioning arc on scratch copies: gates (build + vectors,
    proofs) -> gold moves -> l2 gains the theorem-named target -> the props
    re-blessing -> baseline verifies -> detection and attestation clean
    against the new baseline."""
    from pybb.attestation.props import write_props_protocol_dir
    from pybb.attestation.targetmap import derive_targets_from_lean

    sys.path.insert(0, str(REPO / "examples"))
    from temp_control_lean import make_codegen_fn, resolved_exec_targets

    golden_tmp = tmp_path / "golden"
    shutil.copytree(GOLDEN_ROOT, golden_tmp)
    protocols = {}
    for pid in ("temp_control_lean_l1a", "temp_control_lean_l2", "temp_control_lean_props", "temp_control_lean_check"):
        shutil.copytree(FIXTURES / pid, tmp_path / pid)
        protocols[pid] = ProtocolDir.load(str(tmp_path / pid))
    client = CvmSubprocessClient()

    predicate = make_promotion_predicate(
        protocols, golden_tmp,
        targets_fn=lambda: derive_targets_from_lean(LEAN_ROOT, prefix="temp_control_lean"),
        codegen_fn=make_codegen_fn(resolved_exec_targets()),
        client=client, validate_with="temp_control_lean_check")
    outcome = predicate(promotion_request("lean"))
    assert outcome, outcome.error
    assert outcome.validated is True
    assert outcome.targets == {"temp_control_lean_l1a": 6, "temp_control_lean_l2": 16}
    assert "temp_control_lean_spec_fanOff_only_if_cold_or_held_targ" \
        in protocols["temp_control_lean_l2"].asp_args["readfile_range"]

    # the re-blessing: props definition regenerated over the sanctioned
    # spec, then provisioned (measure + sign on the moved gold)
    write_props_protocol_dir(tmp_path / "temp_control_lean_props", "lean", [str(SPEC)],
                             "test blessing")
    protocols["temp_control_lean_props"] = ProtocolDir.load(str(tmp_path / "temp_control_lean_props"))
    measured = {p: protocols[p] for p in ("temp_control_lean_l1a", "temp_control_lean_l2", "temp_control_lean_props")}
    ctl = BlackboardController()
    ctl.register_predicate("provision",
                           make_provision_predicate(client, measured, golden_tmp))
    for p in measured:
        request_provision(ctl.blackboard, p)
    bb = ctl.run()
    assert not bb.get_escalate(), bb.get_escalate()

    report = make_readiness_predicate(
        measured, baseline_root=golden_tmp,
        client=client)(readiness_request(list(measured)))
    assert report, (report.problems, report.baseline_problems)
    assert not changed_decls(protocols["temp_control_lean_l2"], LEAN_ROOT,
                             props_protocol=protocols["temp_control_lean_props"])
    verdict = make_attestation_predicate(client, protocols)(
        attestation_request("temp_control_lean_l1a"))
    assert verdict.passed, verdict
