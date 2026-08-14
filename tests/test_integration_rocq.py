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


@needs_rocq
def test_immutable_model_policy_restores_and_reattests_in_session():
    """model_drift_policy="restore" (the driver's --immutable-model): a
    header-comment edit drifts the model file WITHOUT weakening any
    contract slice — the drift the escalate policy tolerates ("attested
    clean at finer granularity"). Under the immutable ruling the failed
    hash appraisal alone is the repair order: the file is restored from
    golden and the episode re-attests in-session, no refinement gating,
    no user."""
    from pybb.attestation.snapshot import mirror_path

    rocq, rw = _rocq_example(), _rocq_workflow()
    protocols = _protocols(VERIFICATION_ID)
    snapshot = TargetSnapshot.load(protocols, GOLDEN_ROOT)
    text = PROPS.read_text()
    marker = "The BLESSED statements file:"
    assert marker in text
    PROPS.write_text(text.replace(marker, marker + " (drifted header)"))
    try:
        ctl = rw.attest_episode(rocq.CONFIG, protocols, repair=False,
                                model_drift_policy="restore")
        bb = ctl.blackboard
        key = f"{PREFIX}:model"
        assert bb.entries[key].good_standing and not bb.escalate
        assert bb.restarts.get(key) == 1
        assert PROPS.read_bytes() == mirror_path(GOLDEN_ROOT, PROPS).read_bytes()
        assert "repaired and re-attested clean in-session" in trust_summary(bb)
    finally:
        snapshot.restore()


@needs_rocq
def test_isolation_variants_judge_goals_individually():
    """The checklist's build-failure refinement: break ONE proof; every
    goal is judged from its own derived isolation variant (proof
    opacity — siblings admitted, statements preserved): intact proofs
    PROVED, the broken goal FAILING with its own diagnostic, and the
    dependency chain (spec_holds, acceptance) intact-with-assumes."""
    from pybb.attestation.proof_status import FAILING, PROVED

    rocq, rw = _rocq_example(), _rocq_workflow()
    pristine = PROOFS.read_bytes()
    rw._break_proof(rocq.CONFIG)
    try:
        statuses = rw._isolation(rocq.CONFIG)()
        broken = statuses["fanHold_in_band"]
        assert broken.state == FAILING and "isolated" in broken.detail
        for goal in ("hot_means_not_cold", "fanOn_when_hot",
                     "fanOff_when_cold", "fanOn_only_if_hot_or_held"):
            assert statuses[goal].state == PROVED, (goal, statuses[goal])
        # spec_holds' own script is intact but leans on the (admitted)
        # broken sibling — named, not poisoned
        sh = statuses["spec_holds"]
        assert sh.state == PROVED and "fanHold_in_band" in sh.detail
        acc = statuses["acceptance"]
        assert acc.state == PROVED and "assumes spec_holds" in acc.detail
    finally:
        PROOFS.write_bytes(pristine)


def test_model_drift_policy_validated():
    rocq, rw = _rocq_example(), _rocq_workflow()
    with pytest.raises(ValueError, match="model_drift_policy"):
        rw.attest_episode(rocq.CONFIG, {}, repair=False,
                          model_drift_policy="tolerate")


def test_baseline_tamper_refuses_at_readiness():
    """The repair that must refuse: the trust state is attacked while the
    live tree stays pristine, and readiness stops attestation before it
    starts. Beat 1: one flipped byte of stored bundle evidence breaks the
    bundle signature. Beat 2: a hand-edited installed golden leaves the
    signature intact but fails the anchor to the signed evidence. No
    repair chain exists for either — re-blessing is out-of-band."""
    import json as _json
    from pybb.attestation import (CvmSubprocessClient,
                                  make_readiness_predicate,
                                  readiness_request)

    rocq, rw = _rocq_example(), _rocq_workflow()
    bundle = GOLDEN_ROOT / "_bundles" / f"{PREFIX}_model" / "provision_bundle.json"
    args_path = FIXTURES / f"{PREFIX}_model" / "asp_args.json"
    bundle_pristine = bundle.read_bytes()
    args_pristine = args_path.read_bytes()

    def report():
        protocols = rw.load_protocols(rocq.CONFIG)
        return make_readiness_predicate(
            protocols, baseline_root=GOLDEN_ROOT,
            client=CvmSubprocessClient())(readiness_request(list(protocols)))

    def flip(s, at=10):
        return s[:at] + ("A" if s[at] != "A" else "B") + s[at + 1:]

    try:
        d = _json.loads(bundle_pristine)
        raw = d[0][0]["RawEv"]
        i = max(range(1, len(raw)), key=lambda k: len(raw[k]))  # never the sig slot
        raw[i] = flip(raw[i])
        bundle.write_text(_json.dumps(d))
        r = report()
        assert not r
        assert any("signature verification FAILED" in p
                   for p in r.baseline_problems)
        bundle.write_bytes(bundle_pristine)

        a = _json.loads(args_pristine)
        targ = a["readfile"][f"{PREFIX}_model_props_targ"]
        targ["golden_b64"] = flip(targ["golden_b64"])
        args_path.write_text(_json.dumps(a, indent=2))
        r = report()
        assert not r
        assert any("Blessed-content appraisal failed" in p
                   for p in r.baseline_problems)
        # the bundle is authentic in this beat: only the anchor refutes
        assert not any("signature verification FAILED" in p
                       for p in r.baseline_problems)
    finally:
        bundle.write_bytes(bundle_pristine)
        args_path.write_bytes(args_pristine)


def _apply_breaking_restatement():
    """The 'commands' restatement: the model elaborates and bless_lint
    passes, but the seed proof of fanOn_when_hot no longer proves it."""
    text = PROPS.read_text()
    helper = ("Definition commands (f : Step) (t : Z) (sp : SetPoint)\n"
              "                    (l c : FanCmd) : Prop :=\n"
              "  f t sp l = c.\n\n")
    marker = "(* Goal: currentTemp above the band commands the fan On. *)"
    text = text.replace(marker, helper + marker)
    text = text.replace("    high sp < temp -> f temp sp latest = On.",
                        "    high sp < temp -> commands f temp sp latest On.")
    PROPS.write_text(text)


@needs_rocq
def test_spec_first_blessing_keeps_baseline_coherent():
    """Blessing sanctions the SPEC: a model change whose proofs do not
    yet verify blesses fine. The verification tier's tool-hash bundle is
    NOT re-provisioned (its goldens are spec-independent), so readiness
    still verifies every signed baseline and the unproved obligation
    surfaces as episode measurement — verification escalates while model
    and contracts attest clean against the new blessing."""
    rocq, rw = _rocq_example(), _rocq_workflow()
    cfg = rocq.CONFIG
    props_pristine = PROPS.read_bytes()
    proofs_pristine = PROOFS.read_bytes()
    ver_bundle = (GOLDEN_ROOT / "_bundles" / cfg.verification_id
                  / "provision_bundle.json")
    bundle_before = ver_bundle.read_bytes()
    _apply_breaking_restatement()
    try:
        rw.provision_flow(cfg, rw.build_protocol_dirs(cfg), bless_model=True)
        assert ver_bundle.read_bytes() == bundle_before, \
            "blessing must not re-sign the verification tier"
        ctl = rw.attest_episode(cfg, rw.load_protocols(cfg), repair=False)
        bb = ctl.blackboard
        assert bb.entries[f"{PREFIX}:model"].good_standing
        assert bb.entries[f"{PREFIX}:contracts"].good_standing
        assert f"{PREFIX}:verification" in bb.escalate
    finally:
        PROPS.write_bytes(props_pristine)
        PROOFS.write_bytes(proofs_pristine)
        rw.provision_flow(cfg, rw.build_protocol_dirs(cfg), bless_model=True)


@needs_rocq
def test_repair_proofs_adapts_to_proposed_model_change():
    """synthesize_flow stub='none' (--repair-proofs): a sanctioned model
    RESTATEMENT (a new blessed helper relation wrapping a conclusion)
    elaborates but refutes the seed proof; the live-tree synthesis
    episode re-proves the goal against the PROPOSED statements (guidance
    from the live spec, not the old blessing) and re-attests in-session."""
    rocq, rw = _rocq_example(), _rocq_workflow()
    cfg = rocq.CONFIG
    props_pristine = PROPS.read_bytes()
    proofs_pristine = PROOFS.read_bytes()
    _apply_breaking_restatement()
    try:
        ctl = rw.synthesize_flow(cfg, rw.load_protocols(cfg), keep=False,
                                 stub="none")
        bb = ctl.blackboard
        key = f"{PREFIX}:verification"
        assert bb.entries[key].good_standing, "verification must recover"
        assert bb.restarts.get(key) == 1, "standing from fresh measurement"
        assert "repaired and re-attested clean in-session" \
            in trust_summary(bb, semantic=[cfg.verification_id])
        # the drift entries stay escalated: blessing is a separate act
        assert f"{PREFIX}:model" in bb.escalate
    finally:
        PROPS.write_bytes(props_pristine)
        PROOFS.write_bytes(proofs_pristine)


def test_escalation_detail_renders_failing_contracts():
    """The terminal detail behind the summary one-liners: contract name,
    file:line slice, first reason line — deduped across the escalated
    entries that share a verdict."""
    from pybb.blackboard import Blackboard
    from pybb.attestation.appraisal import ComponentResult
    from pybb.attestation.knowledge_sources import Verdict

    rw = _rocq_workflow()
    comp = ComponentResult(
        appr_asp="model_slices_appr", target_asp="readfile_range",
        targ_id="slice_targ", passed=False,
        reason="Evidence bytes do not match golden\nsecond line",
        args={"metadata": "TempControl.Props::SetPoint_valid",
              "filepath": "/x/Props.v", "start_index": 23, "end_index": 24})
    verdict = Verdict(protocol="contracts_p", passed=False,
                      components=[comp])
    bb = Blackboard()
    for key in ("a:model", "a:contracts"):
        bb.write_entry(key=key, predicate="attestation", measurement={},
                       result=verdict)
        bb.escalate[key] = bb.entries.pop(key)
    detail = rw._escalation_detail(bb)
    assert "failed attestation results (contracts_p):" in detail
    assert "TempControl.Props::SetPoint_valid" in detail
    assert "Props.v:23-24" in detail
    assert "Evidence bytes do not match golden" in detail
    assert detail.count("SetPoint_valid") == 1   # deduped across entries
    assert "second line" not in detail           # first reason line only
    assert rw._escalation_detail(Blackboard()) == ""


def test_escalation_detail_moved_vs_modified(tmp_path):
    """The display-layer refinement of position-based slice failures: a
    failing slice whose declaration relocates BY NAME to unchanged
    content is 'moved', changed content is 'modified', an absent name is
    'missing' — annotation only, the position-based verdict stands."""
    import base64
    from pybb.blackboard import Blackboard
    from pybb.attestation.appraisal import ComponentResult
    from pybb.attestation.knowledge_sources import Verdict

    rw = _rocq_workflow()
    live = tmp_path / "Props.v"
    live.write_text(
        "(* an insertion shifted everything below *)\n"
        "Definition extra : Prop := True.\n"
        "\n"
        "Definition alpha (x : Z) : Prop :=\n"
        "  0 <= x.\n"
        "\n"
        "Definition beta (x : Z) : Prop :=\n"
        "  x <= 99.\n")

    def comp(name, golden):
        return ComponentResult(
            appr_asp="model_slices_appr", target_asp="readfile_range",
            targ_id=f"{name}_targ", passed=False,
            reason="Evidence bytes do not match golden",
            args={"metadata": f"T.Props::{name}", "filepath": str(live),
                  "start_index": 1, "end_index": 2,
                  "golden_b64": base64.b64encode(golden.encode()).decode()})

    v = Verdict(protocol="p", passed=False, components=[
        comp("alpha", "Definition alpha (x : Z) : Prop :=  0 <= x."),
        comp("beta", "Definition beta (x : Z) : Prop :=  x <= 42."),
        comp("gamma", "anything")])
    bb = Blackboard()
    bb.write_entry(key="k", predicate="attestation", measurement={}, result=v)
    bb.escalate["k"] = bb.entries.pop("k")
    detail = rw._escalation_detail(bb)
    lines = {l.split("::", 1)[1].split()[0]: l
             for l in detail.splitlines() if "::" in l}
    # a moved-but-unchanged slice reads ✓ (disposition mark, not the
    # appraisal's) and drops the raw range-mismatch reason; real changes
    # keep ✗ and the reason
    assert "✓" in lines["alpha"] and "moved (content unchanged)" in lines["alpha"]
    assert "✗" in lines["beta"] and "modified" in lines["beta"]
    assert "✗" in lines["gamma"] and "missing from the live file" in lines["gamma"]
    # the raw appraiser reason survives under ✗ (beta, gamma) but is
    # dropped under a ✓-moved line, where it would only re-confuse
    assert detail.count("Evidence bytes do not match golden") == 2


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
