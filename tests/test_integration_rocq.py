"""
Rocq goal-directed encoding end-to-end (temp-control_Rocq): the
administrator blesses abstract goal PROPERTIES (Props.v, statements
only) plus the obligation binding (Acceptance.v); proofs, the
implementation, and intermediate lemmas are workflow-owned and freely
mutable. What these tests pin:

  - the invariant: a blessed statement cannot drift (attributed by prop
    name, repaired from golden, re-attested clean in-session);
  - the mutability: proof edits and new lemmas leave every structural
    measurement green — and still prove;
  - the toolchain gap this example exists for: `Admitted.` and `Axiom`
    ELABORATE CLEANLY in Rocq (exit 0, green build), so provability is
    judged by the assumptions audit, not the build — an admitted proof
    is refuted with its goal named, and a smuggled axiom discharging a
    goal is refuted with the axiom named.

The fixtures-consistency test runs ungated; everything touching the CVM
or the rocq/dune toolchain is gated behind RUN_ROCQ=1 (the verification
class always runs the toolchain — it is woven into every episode).
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
    make_attestation_predicate,
    trust_summary,
)
from pybb.attestation.client import DEFAULT_ASP_BIN, DEFAULT_CVM_BINARY
from pybb.attestation.targetmap import derive_targets_from_rocq

REPO = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN_ROOT = REPO / "golden"
ROCQ_ROOT = REPO / "targets" / "temp-control-rocq"
PROPS = ROCQ_ROOT / "TempControl" / "Props.v"
ACCEPTANCE = ROCQ_ROOT / "TempControl" / "Acceptance.v"
PROOFS = ROCQ_ROOT / "TempControl" / "Proofs.v"
ROCQ_WRAPPER = Path.home() / "Claude_workspace/bin/rocq"
DUNE_WRAPPER = Path.home() / "Claude_workspace/bin/dune"
PREFIX = "temp_control_rocq"
PROTOCOL_IDS = (f"{PREFIX}_model", f"{PREFIX}_contracts")
VERIFICATION_ID = f"{PREFIX}_verification"
BLESSED = [str(PROPS), str(ACCEPTANCE)]

pytestmark = [
    pytest.mark.cvm,
    pytest.mark.skipif(
        not (Path(DEFAULT_CVM_BINARY).is_file() and Path(DEFAULT_ASP_BIN).is_dir()),
        reason="requires local CVM binary and asp-libs binaries",
    ),
]

needs_rocq = pytest.mark.skipif(
    os.environ.get("RUN_ROCQ") != "1"
    or not (ROCQ_WRAPPER.is_file() and DUNE_WRAPPER.is_file()),
    reason="set RUN_ROCQ=1 (and install the workspace rocq/dune wrappers) "
           "to run the Rocq toolchain arcs")


def _protocols(*extra: str) -> dict:
    return {pid: ProtocolDir.load(str(FIXTURES / pid))
            for pid in (*PROTOCOL_IDS, *extra)}


def _rocq_example():
    sys.path.insert(0, str(REPO / "examples"))
    import temp_control_rocq
    return temp_control_rocq


def _rocq_workflow():
    sys.path.insert(0, str(REPO / "examples"))
    import rocq_workflow
    return rocq_workflow


def test_committed_fixtures_derive_from_the_scoped_scan():
    """The syntax scan over the BLESSED FILES ONLY is the authority: the
    committed contracts map must equal it, and no mutable file (Proofs,
    Impl, Assumptions) may appear in any structural target."""
    derived = derive_targets_from_rocq(ROCQ_ROOT, prefix=PREFIX, files=BLESSED)
    for pid, groups in derived.items():
        committed = ProtocolDir.load(str(FIXTURES / pid)).asp_args
        for asp_id, targets in groups.items():
            assert set(committed[asp_id]) == set(targets), pid
            for targ_id, args in targets.items():
                c = committed[asp_id][targ_id]
                for k, v in args.items():
                    assert c[k] == v, f"{pid}/{targ_id}/{k} diverged from scan"
    for pid in PROTOCOL_IDS:
        for targets in ProtocolDir.load(str(FIXTURES / pid)).asp_args.values():
            for args in targets.values():
                assert args["filepath"] in BLESSED, \
                    f"mutable file measured structurally: {args['filepath']}"


def _episode(repair: bool = True, restart_budget: int = 0):
    from pybb.attestation import RestartEpisodeKS

    protocols = _protocols()
    ctl = BlackboardController()
    ctl.register_predicate(
        "attestation", make_attestation_predicate(CvmSubprocessClient(), protocols))
    chain = [TierKS(protocol_id=f"{PREFIX}_contracts")]
    if repair:
        chain.append(WholeFileRestoreKS(golden_root=GOLDEN_ROOT,
                                        refined_by=f"{PREFIX}_contracts"))
    if restart_budget:
        chain.append(RestartEpisodeKS(budget=restart_budget))
    for ks in chain:
        ctl.add_ks(ks)
    ctl.blackboard.write_entry(key=f"{PREFIX}:model", predicate="attestation",
                               measurement=attestation_request(f"{PREFIX}_model"))
    ctl.route(f"{PREFIX}:model", on_fail=chain)
    ctl.run()
    return ctl.blackboard


@needs_rocq
def test_clean_attestation_of_rocq_package():
    bb = _episode()
    entry = bb.get_entry(f"{PREFIX}:model")
    assert entry.good_standing and entry.result.protocol == f"{PREFIX}_model"
    # the blessing covers TWO files: readfile + hashfile each, plus sig
    assert len(entry.result.components) == 5
    assert "all attested components intact" in trust_summary(bb)


@needs_rocq
def test_blessed_prop_tamper_attributed_by_name_repaired_verified():
    """The invariant arc: corrupt a blessed goal statement; attribution
    names the prop, whole-file repair restores, episode 2 verifies."""
    snapshot = TargetSnapshot.load(_protocols(), GOLDEN_ROOT)
    targ = f"{PREFIX}_props_fanOn_when_hot_prop_targ"
    args = _protocols()[f"{PREFIX}_contracts"].asp_args["readfile_range"][targ]
    assert args["metadata"] == "TempControl.Props::fanOn_when_hot_prop"
    lines = PROPS.read_text().splitlines(keepends=True)
    lines[args["end_index"] - 1] = "  (* TAMPERED: blessed statement weakened *)\n"
    PROPS.write_text("".join(lines))
    try:
        bb1 = _episode()
        escalated = bb1.escalate[f"{PREFIX}:model"]
        assert escalated.ks_history == {f"tier:{PREFIX}_contracts": 1,
                                        "repair:whole-file": 1}
        l2v = next(e.result for k, e in bb1.get_history()
                   if k == f"{PREFIX}:model" and e.result is not None
                   and e.result.protocol == f"{PREFIX}_contracts")
        assert targ in {c.targ_id for c in l2v.failing()}
        from pybb.attestation.snapshot import mirror_path
        assert PROPS.read_bytes() == mirror_path(GOLDEN_ROOT, PROPS).read_bytes()
        bb2 = _episode()
        assert bb2.entries[f"{PREFIX}:model"].good_standing
        assert not bb2.escalate
    finally:
        snapshot.restore()


@needs_rocq
def test_repair_reattested_clean_in_session_via_restart():
    """The restart-episode primitive against the real CVM: tamper a
    blessed statement, run ONE episode with a restart-terminated repair
    chain — the entry ends in GOOD STANDING, and the pass provably came
    from a fresh measurement: the history retains episode 1's failing
    model verdict."""
    snapshot = TargetSnapshot.load(_protocols(), GOLDEN_ROOT)
    targ = f"{PREFIX}_props_fanOn_when_hot_prop_targ"
    args = _protocols()[f"{PREFIX}_contracts"].asp_args["readfile_range"][targ]
    lines = PROPS.read_text().splitlines(keepends=True)
    lines[args["end_index"] - 1] = "  (* TAMPERED: blessed statement weakened *)\n"
    PROPS.write_text("".join(lines))
    try:
        bb = _episode(repair=True, restart_budget=1)
        entry = bb.entries[f"{PREFIX}:model"]
        assert entry.good_standing and not bb.escalate
        assert bb.restarts == {f"{PREFIX}:model": 1}
        verdicts = [e.result for k, e in bb.get_history()
                    if k == f"{PREFIX}:model" and e.result is not None
                    and e.result.protocol == f"{PREFIX}_model"]
        outcomes = [bool(v) for v in verdicts]  # one per evaluation cycle
        assert not outcomes[0] and outcomes[-1], \
            "episode 1 failed, the restarted episode re-measured and passed"
        assert "repaired and re-attested clean in-session (episode 2)" \
            in trust_summary(bb)
    finally:
        snapshot.restore()


# ── the Rocq toolchain tier (always-run in episodes; judged here alone) ───────

def _tier_verdict():
    protocols = _protocols(VERIFICATION_ID)
    predicate = make_attestation_predicate(CvmSubprocessClient(), protocols)
    return predicate(attestation_request(VERIFICATION_ID))


@needs_rocq
def test_build_and_audit_tier_clean_with_woven_tools():
    check = _tier_verdict()
    assert check.passed, check
    assert {f"{PREFIX}_build_verification_targ",
            f"{PREFIX}_assumptions_verification_targ"} <= \
        {c.targ_id for c in check.components}
    tool_targs = {c.targ_id for c in check.components
                  if (c.args.get("metadata") or "").startswith("tool::rocq")}
    assert len(tool_targs) == 4


MUTATION_LEMMA = """
(* Intermediate lemma introduced mid-workflow (test). *)
Lemma tc_test_band_nonempty : forall sp : SetPoint,
    SetPoint_valid sp -> low sp <= high sp.
Proof. unfold SetPoint_valid. intros sp Hv. lia. Qed.
"""


def _mutate_proofs() -> str:
    """Write a proof-body variation plus a new intermediate lemma into
    Proofs.v; returns the original text for restore. Both changes prove
    (the tier test below judges them live)."""
    orig = PROOFS.read_text()
    mutated = orig.replace(
        "  unfold SetPoint_valid. intros temp sp Hv Hh. lia.",
        "  unfold SetPoint_valid. intros t sp Hvalid Hhot. lia.")
    assert mutated != orig
    mutated = mutated + MUTATION_LEMMA
    PROOFS.write_text(mutated)
    return orig


@needs_rocq
def test_proof_mutation_leaves_structural_measurements_green_and_proves():
    """The mutability arc (the encoding's core claim): rewriting a seed
    proof and introducing an intermediate lemma is INVISIBLE to the
    model and contracts classes — and the tier still proves: the audit
    judges provability, not proof text."""
    orig = _mutate_proofs()
    try:
        bb = _episode()
        assert bb.entries[f"{PREFIX}:model"].good_standing
        assert not bb.escalate
        check = _tier_verdict()
        assert check.passed, check
    finally:
        PROOFS.write_text(orig)


@needs_rocq
def test_admitted_proof_passes_build_refuted_by_audit_naming_the_goal():
    """The toolchain gap: `Admitted.` compiles with exit 0 — the build
    target PASSES — and only the assumptions audit refutes it, naming
    the admitted goal (and everything downstream of it)."""
    rocq, rw = _rocq_example(), _rocq_workflow()
    original = rw.tamper_admitted(rocq.CONFIG)
    try:
        check = _tier_verdict()
        assert not check.passed
        failing = {c.targ_id: c for c in check.failing()}
        assert f"{PREFIX}_build_verification_targ" not in failing, \
            "Admitted elaborates cleanly — the build must stay green"
        audit = failing[f"{PREFIX}_assumptions_verification_targ"]
        assert "fanHold_in_band depends on axioms" in audit.reason
    finally:
        PROOFS.write_bytes(original)


@needs_rocq
def test_smuggled_axiom_refuted_by_audit_naming_the_axiom():
    """THE HEADLINE: an Axiom asserting exactly the goal, and a proof by
    it — every file elaborates cleanly, nothing structural moves (model
    and contracts stay green), and the audit still refutes the goal,
    naming the smuggled axiom."""
    rocq, rw = _rocq_example(), _rocq_workflow()
    original = rw.tamper_axiom(rocq.CONFIG)
    try:
        bb = _episode()
        assert bb.entries[f"{PREFIX}:model"].good_standing, \
            "structural classes must not see the smuggled axiom"
        assert not bb.escalate
        check = _tier_verdict()
        assert not check.passed
        failing = {c.targ_id: c for c in check.failing()}
        assert f"{PREFIX}_build_verification_targ" not in failing, \
            "the smuggled axiom elaborates cleanly — the build must stay green"
        audit = failing[f"{PREFIX}_assumptions_verification_targ"]
        assert "fanHold_in_band depends on axioms: convenient" in audit.reason
    finally:
        PROOFS.write_bytes(original)
