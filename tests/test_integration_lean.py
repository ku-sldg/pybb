"""
Lean example end-to-end: the syntax scan is the authoritative source of
targets (lean_l1a/lean_l2 derive from targets/temp-control-lean, never
hand-curated); attestation runs against the vendored Lake package; a
tampered theorem slice is detected, attributed by declaration name,
whole-file repaired from golden, and verified clean by the next episode.

The semantic tiers are gated behind RUN_LEAN=1 (they invoke the Lean
toolchain via the workspace lake wrapper): lean_check re-elaborates the
specification (`lake lean TempControl/Spec.lean -- --json` — a sorry
exits 0 and only WARNS, so the appraiser's hasSorry handling is what
catches it), and lean_exec runs the built binary on one vector per GUMBO
case. Main imports only TempControl.Impl, so provability and behavior
are independent: a sorry fails proofs but not behavior, and a laundered
implementation change is refuted by BOTH tiers even though every hash
measurement blesses it.

Hash/repair tests auto-skip unless the CVM binary and asp-libs are
present (the vendored tree ships with the repo).
"""

import os
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
from pybb.attestation.targetmap import derive_targets_from_lean

REPO = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN_ROOT = REPO / "golden"
LEAN_ROOT = REPO / "targets" / "temp-control-lean"
IMPL = LEAN_ROOT / "TempControl" / "Impl.lean"
SPEC = LEAN_ROOT / "TempControl" / "Spec.lean"
LAKE_WRAPPER = Path.home() / "Claude_workspace/bin/lake"
PROTOCOL_IDS = ("lean_l1a", "lean_l2")
TIER_IDS = ("lean_check", "lean_exec")

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
    derived = derive_targets_from_lean(LEAN_ROOT)
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
    chain = [TierKS(protocol_id="lean_l2")]
    if repair:
        chain.append(WholeFileRestoreKS(golden_root=GOLDEN_ROOT,
                                        refined_by="lean_l2"))
    for ks in chain:
        ctl.add_ks(ks)
    ctl.blackboard.write_entry(key="lean:files", predicate="attestation",
                               measurement=attestation_request("lean_l1a"))
    ctl.route("lean:files", on_fail=chain)
    ctl.run()
    return ctl.blackboard


def test_clean_attestation_of_lean_package():
    bb = _episode()
    entry = bb.get_entry("lean:files")
    assert entry.good_standing and entry.result.protocol == "lean_l1a"
    # sources + lakefile.toml + lean-toolchain hashes, plus sig
    assert len(entry.result.components) == 7
    assert "all attested components intact" in trust_summary(bb)


def test_theorem_tamper_attributed_by_name_repaired_verified(live_snapshot):
    targ = "lean_spec_fanOn_when_hot_targ"
    args = _protocols()["lean_l2"].asp_args["readfile_range"][targ]
    assert args["metadata"] == "TempControl.Spec::fanOn_when_hot"
    lines = SPEC.read_text().splitlines(keepends=True)
    lines[args["end_index"] - 1] = "  -- TAMPERED: proof body removed\n"
    SPEC.write_text("".join(lines))

    bb1 = _episode()

    escalated = bb1.escalate["lean:files"]
    assert escalated.ks_history == {"tier:lean_l2": 1, "repair:whole-file": 1}
    l2v = next(e.result for k, e in bb1.get_history()
               if k == "lean:files" and e.result is not None
               and e.result.protocol == "lean_l2")
    assert targ in {c.targ_id for c in l2v.failing()}
    from pybb.attestation.snapshot import mirror_path
    assert SPEC.read_bytes() == mirror_path(GOLDEN_ROOT, SPEC).read_bytes()
    assert "repaired from golden — verification pending" in trust_summary(bb1)

    bb2 = _episode()
    assert bb2.entries["lean:files"].good_standing
    assert not bb2.escalate


# ── Lean toolchain tiers (RUN_LEAN=1) ─────────────────────────────────────────

def _tier_verdict(protocol_id: str):
    protocols = _protocols(*TIER_IDS)
    predicate = make_attestation_predicate(CvmSubprocessClient(), protocols)
    return predicate(attestation_request(protocol_id))


@needs_lean
def test_proofs_and_behavior_tiers_clean_with_woven_tools():
    check = _tier_verdict("lean_check")
    assert check.passed, check
    check_targs = {c.targ_id for c in check.components}
    assert "lean_spec_check_targ" in check_targs
    # the lean toolchain was measured in the same term, before the use
    tool_targs = {c.targ_id for c in check.components
                  if (c.args.get("metadata") or "").startswith("tool::lean")}
    assert len(tool_targs) == 6
    behavior = _tier_verdict("lean_exec")
    assert behavior.passed, behavior
    assert {"lean_exec_hot_targ", "lean_exec_cold_targ",
            "lean_exec_hold_targ"} <= {c.targ_id for c in behavior.components}


@needs_lean
def test_tampered_tool_on_invocation_chain_fails_both_tiers():
    """Measure-then-use: a modified artifact on the lean invocation chain
    (the workspace wrapper) makes BOTH tier verdicts untrustworthy —
    attributed to the tool target, regardless of what the tool outputs."""
    orig = LAKE_WRAPPER.read_bytes()
    LAKE_WRAPPER.write_bytes(orig + b"\n# TAMPERED: altered after blessing\n")
    try:
        check = _tier_verdict("lean_check")
        assert not check.passed
        assert {c.targ_id for c in check.failing()} == {"tool_lean_lake_targ"}
        behavior = _tier_verdict("lean_exec")
        assert not behavior.passed
        assert {c.targ_id for c in behavior.failing()} == {"tool_lean_lake_targ"}
    finally:
        LAKE_WRAPPER.write_bytes(orig)
    assert _tier_verdict("lean_check").passed


@needs_lean
def test_sorry_fails_proofs_but_not_behavior():
    """A sorry exits 0 and only warns — and does not change behavior: the
    check tier must refute it while the exec tier still passes."""
    orig = SPEC.read_text()
    broken = orig.replace("  simp [computeFanCmd, h]\n", "  sorry\n", 1)
    assert broken != orig
    SPEC.write_text(broken)
    try:
        check = _tier_verdict("lean_check")
        assert not check.passed
        assert any("hasSorry" in c.reason for c in check.failing())
        assert _tier_verdict("lean_exec").passed  # Main never elaborates Spec
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
        check = _tier_verdict("lean_check")
        assert not check.passed
        behavior = _tier_verdict("lean_exec")
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
        behavior = _tier_verdict("lean_exec")
        assert not behavior.passed
        assert "lean_bin_temp_control_targ" in \
            {c.targ_id for c in behavior.failing()}
    finally:
        BIN.write_bytes(orig)
        BIN.chmod(0o755)
    assert _tier_verdict("lean_exec").passed


# ── signed golden spec (props): the administrator-blessed Spec.lean ───────────

def test_props_blesses_the_spec_and_anchors_are_not_vacuous():
    from pybb.attestation import verify_bundle
    from pybb.attestation.baseline import _build_anchors

    protocols = _protocols("lean_props")
    committed = protocols["lean_props"].asp_args["readfile"]
    assert [a["filepath"] for a in committed.values()] == [str(SPEC)]
    assert all(a.get("golden_b64") for a in committed.values())
    # the blessed spec anchors its hash golden AND every declaration slice
    # lean_l2 installs for Spec.lean (theorems, invariant, examples)
    anchors = _build_anchors(protocols)
    assert anchors[str(SPEC)].get("hash_golden_b64")
    assert len(anchors[str(SPEC)]["slices"]) == 8
    report = verify_bundle(CvmSubprocessClient(), protocols["lean_props"],
                           GOLDEN_ROOT, anchor_protocols=protocols)
    assert report, report.problems
    assert report.anchored == ["lean_props_spec_targ"]


def test_laundered_theorem_refuted_by_blessing():
    """Tamper a theorem in the GOLDEN tree and re-provision the measurement
    protocols: their baselines re-sign self-consistently and verify — only
    the administrator's blessing of Spec.lean (not re-provisioned) refutes
    the laundered goldens."""
    from pybb import BlackboardController
    from pybb.attestation import (make_provision_predicate,
                                  make_readiness_predicate, readiness_request,
                                  request_provision)

    pids = ["lean_l1a", "lean_l2", "lean_props"]
    protocols = {p: ProtocolDir.load(str(FIXTURES / p)) for p in pids}
    client = CvmSubprocessClient()
    args = protocols["lean_l2"].asp_args["readfile_range"][
        "lean_spec_fanOn_when_hot_targ"]
    gold = Path("golden" + args["filepath"])
    orig = gold.read_bytes()

    def reprovision():
        ctl = BlackboardController()
        sub = {p: protocols[p] for p in ("lean_l1a", "lean_l2")}
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
        assert report.baseline_verified == ["lean_l1a", "lean_l2"]
        assert any("lean_props" in p and "not derivable from blessed content" in p
                   for p in report.baseline_problems)
    finally:
        gold.write_bytes(orig)
        reprovision()
    report = make_readiness_predicate(
        protocols, baseline_root=GOLDEN_ROOT,
        client=CvmSubprocessClient())(readiness_request(pids))
    assert report, (report.problems, report.baseline_problems)
