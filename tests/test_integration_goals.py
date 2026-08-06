"""
Goal-directed encoding pilot end-to-end (temp-control-goals_Lean): the
administrator blesses abstract goal PROPERTIES (Props.lean, statements
only) plus the two-line obligation binding (Acceptance.lean); proofs,
the implementation, and intermediate lemmas are workflow-owned and
freely mutable. What these tests pin:

  - the invariant: a blessed statement cannot drift (attributed by prop
    name, repaired from golden, laundering refuted by the blessing);
  - the mutability: proof edits and new lemmas leave every structural
    measurement green — the room the goal-directed workflow needs;
  - the coverage: weakening spec_holds passes every file's own
    elaboration but fails the blessed Acceptance obligation;
  - the lint: a blessing containing proofs (or a non-canonical binding)
    is refused before anything is signed.

Hash/repair tests auto-skip unless the CVM binary and asp-libs are
present; toolchain tiers and the lint (which elaborates Props.lean) are
gated behind RUN_LEAN=1.
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
GOALS_ROOT = REPO / "targets" / "temp-control-goals"
PROPS = GOALS_ROOT / "TempControl" / "Props.lean"
PROOFS = GOALS_ROOT / "TempControl" / "Proofs.lean"
ACCEPTANCE = GOALS_ROOT / "TempControl" / "Acceptance.lean"
LAKE_WRAPPER = Path.home() / "Claude_workspace/bin/lake"
PREFIX = "temp_control_goals_lean"
PROTOCOL_IDS = (f"{PREFIX}_model", f"{PREFIX}_contracts")
TIER_IDS = (f"{PREFIX}_verification", f"{PREFIX}_executable")
BLESSED = [str(PROPS), str(ACCEPTANCE)]

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


def _goals_example():
    sys.path.insert(0, str(REPO / "examples"))
    import temp_control_goals_lean
    return temp_control_goals_lean


def test_committed_fixtures_derive_from_the_scoped_scan():
    """The syntax scan over the BLESSED FILES ONLY is the authority: the
    committed contracts map must equal it, and no mutable file (Proofs,
    Impl, Main) may appear in any structural target."""
    derived = derive_targets_from_lean(GOALS_ROOT, prefix=PREFIX, files=BLESSED)
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


def test_clean_attestation_of_goals_package():
    bb = _episode()
    entry = bb.get_entry(f"{PREFIX}:model")
    assert entry.good_standing and entry.result.protocol == f"{PREFIX}_model"
    # the blessing covers TWO files: readfile + hashfile each, plus sig
    assert len(entry.result.components) == 5
    assert "all attested components intact" in trust_summary(bb)


def test_blessed_prop_tamper_attributed_by_name_repaired_verified():
    """The invariant arc: corrupt a blessed goal statement; attribution
    names the prop, whole-file repair restores, episode 2 verifies."""
    snapshot = TargetSnapshot.load(_protocols(), GOLDEN_ROOT)
    targ = f"{PREFIX}_props_fanOn_when_hot_prop_targ"
    args = _protocols()[f"{PREFIX}_contracts"].asp_args["readfile_range"][targ]
    assert args["metadata"] == "TempControl.Props::fanOn_when_hot_prop"
    lines = PROPS.read_text().splitlines(keepends=True)
    lines[args["end_index"] - 1] = "  -- TAMPERED: blessed statement weakened\n"
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


def test_repair_reattested_clean_in_session_via_restart():
    """The restart-episode primitive against the real CVM: tamper a
    blessed statement, run ONE episode with a restart-terminated repair
    chain — the entry ends in GOOD STANDING (no 'pending next episode'
    escalation), and the pass provably came from a fresh measurement, not
    the memo: the history retains episode 1's failing model verdict."""
    snapshot = TargetSnapshot.load(_protocols(), GOLDEN_ROOT)
    targ = f"{PREFIX}_props_fanOn_when_hot_prop_targ"
    args = _protocols()[f"{PREFIX}_contracts"].asp_args["readfile_range"][targ]
    lines = PROPS.read_text().splitlines(keepends=True)
    lines[args["end_index"] - 1] = "  -- TAMPERED: blessed statement weakened\n"
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


MUTATION_LEMMA = """/-- Intermediate lemma introduced mid-workflow (test). -/
theorem tc_test_band_nonempty (sp : SetPoint) (hv : sp.valid) :
    sp.low ≤ sp.high := by
  obtain ⟨_, h, _⟩ := hv
  exact h

end TempControl"""


def _mutate_proofs() -> str:
    """Write a proof-body replacement plus a new intermediate lemma into
    Proofs.lean; returns the original text for restore. Both replacements
    elaborate (the RUN_LEAN tier test proves it live)."""
    orig = PROOFS.read_text()
    mutated = orig.replace("  next hn => exact absurd h hn",
                           "  next hn => exact (hn h).elim")
    mutated = mutated.replace("end TempControl", MUTATION_LEMMA)
    assert mutated != orig
    PROOFS.write_text(mutated)
    return orig


def test_proof_mutation_leaves_structural_measurements_green():
    """The mutability arc (the encoding's core claim): rewriting a seed
    proof and introducing an intermediate lemma is INVISIBLE to the
    model and contracts classes — mutable files carry no structural
    goldens, so the workflow may iterate freely on proofs."""
    orig = _mutate_proofs()
    try:
        bb = _episode()
        assert bb.entries[f"{PREFIX}:model"].good_standing
        assert not bb.escalate
    finally:
        PROOFS.write_text(orig)


def test_laundered_prop_refuted_by_blessing():
    """Tamper a goal statement in the GOLDEN tree and re-provision the
    contracts class: its baseline re-signs self-consistently — only the
    administrator's blessing (never re-provisioned by the ordinary flow)
    refutes the laundered goldens, and attestation never starts."""
    from pybb.attestation import (make_provision_predicate,
                                  make_readiness_predicate, readiness_request,
                                  request_provision)

    pids = list(PROTOCOL_IDS)
    protocols = _protocols()
    client = CvmSubprocessClient()
    args = protocols[f"{PREFIX}_contracts"].asp_args["readfile_range"][
        f"{PREFIX}_props_fanOn_when_hot_prop_targ"]
    gold = Path("golden" + args["filepath"])
    orig = gold.read_bytes()

    def reprovision():
        ctl = BlackboardController()
        sub = {p: protocols[p] for p in (f"{PREFIX}_contracts",)}
        ctl.register_predicate("provision",
                               make_provision_predicate(client, sub, GOLDEN_ROOT))
        for p in sub:
            request_provision(ctl.blackboard, p)
        bb = ctl.run()
        assert not bb.get_escalate(), bb.get_escalate()

    lines = gold.read_text().splitlines(keepends=True)
    lines[args["end_index"] - 1] = "    sp.high < temp → f temp sp latest = .Off\n"
    gold.write_text("".join(lines))
    try:
        reprovision()
        report = make_readiness_predicate(
            protocols, baseline_root=GOLDEN_ROOT,
            client=CvmSubprocessClient())(readiness_request(pids))
        assert not report
        assert report.baseline_verified == [f"{PREFIX}_contracts"]
        assert any(f"{PREFIX}_model" in p
                   and "not extractable from blessed content" in p
                   for p in report.baseline_problems)
    finally:
        gold.write_bytes(orig)
        reprovision()
    report = make_readiness_predicate(
        protocols, baseline_root=GOLDEN_ROOT,
        client=CvmSubprocessClient())(readiness_request(pids))
    assert report, (report.problems, report.baseline_problems)


def test_am_detection_scoped_to_blessed_files():
    """--check diffs the BLESSED files only: proof/lemma churn in mutable
    files is not a sanctioning question, while a live edit to a blessed
    statement is named precisely."""
    protocols = _protocols()
    kwargs = dict(prefix=PREFIX, props_protocol=protocols[f"{PREFIX}_model"],
                  files=BLESSED)
    assert not changed_decls(protocols[f"{PREFIX}_contracts"], GOALS_ROOT, **kwargs)

    orig_proofs = _mutate_proofs()
    try:
        assert not changed_decls(protocols[f"{PREFIX}_contracts"], GOALS_ROOT,
                                 **kwargs), \
            "mutable-file churn must not read as a model change"
    finally:
        PROOFS.write_text(orig_proofs)

    orig_props = PROPS.read_text()
    PROPS.write_text(orig_props.replace(
        "sp.high < temp → f temp sp latest = .On",
        "sp.high < temp → f temp sp latest = .Off"))
    try:
        diff = changed_decls(protocols[f"{PREFIX}_contracts"], GOALS_ROOT, **kwargs)
        assert diff.modified == ["TempControl.Props::fanOn_when_hot_prop"]
    finally:
        PROPS.write_text(orig_props)

    # exec expecteds resolve from the config (AM-owned)
    goals = _goals_example()
    targets = goals.resolved_exec_targets()
    assert [targets[f"{PREFIX}_executable_{k}_targ"]["expected"]
            for k in goals.EXEC_KEYS] == ["fanCmd=On", "fanCmd=Off", "fanCmd=On"]


# ── Lean toolchain tiers (RUN_LEAN=1) ─────────────────────────────────────────

def _tier_verdict(protocol_id: str):
    protocols = _protocols(*TIER_IDS)
    predicate = make_attestation_predicate(CvmSubprocessClient(), protocols)
    return predicate(attestation_request(protocol_id))


@needs_lean
def test_proofs_and_acceptance_tiers_clean_with_woven_tools():
    check = _tier_verdict(f"{PREFIX}_verification")
    assert check.passed, check
    assert {f"{PREFIX}_proofs_verification_targ",
            f"{PREFIX}_acceptance_verification_targ"} <= \
        {c.targ_id for c in check.components}
    tool_targs = {c.targ_id for c in check.components
                  if (c.args.get("metadata") or "").startswith("tool::lean")}
    assert len(tool_targs) == 6
    behavior = _tier_verdict(f"{PREFIX}_executable")
    assert behavior.passed, behavior
    assert {f"{PREFIX}_executable_hot_targ", f"{PREFIX}_executable_cold_targ",
            f"{PREFIX}_executable_hold_targ"} <= \
        {c.targ_id for c in behavior.components}


@needs_lean
def test_mutated_proofs_still_prove_and_attest_green():
    """The mutability arc, semantically complete: the replaced proof and
    the intermediate lemma ELABORATE — structure green (above) and
    provability green, with the blessed statements untouched."""
    orig = _mutate_proofs()
    try:
        check = _tier_verdict(f"{PREFIX}_verification")
        assert check.passed, check
    finally:
        PROOFS.write_text(orig)


@needs_lean
def test_weakened_spec_holds_refuted_by_acceptance_obligation():
    """The coverage arc: retype spec_holds to True. Proofs.lean still
    elaborates cleanly — every file is individually valid — but the
    blessed obligation binding fails to elaborate, attributed to the
    acceptance target."""
    orig = PROOFS.read_text()
    weakened = orig.replace(
        "theorem spec_holds : Spec computeFanCmd := by",
        "theorem spec_holds : True := trivial\n\n"
        "theorem spec_holds_unbound : Spec computeFanCmd := by")
    assert weakened != orig
    PROOFS.write_text(weakened)
    try:
        check = _tier_verdict(f"{PREFIX}_verification")
        assert not check.passed
        failing = {c.targ_id for c in check.failing()}
        assert f"{PREFIX}_acceptance_verification_targ" in failing
        assert f"{PREFIX}_proofs_verification_targ" not in failing, \
            "Proofs.lean itself is valid — only the obligation is unmet"
    finally:
        PROOFS.write_text(orig)


@needs_lean
def test_sorry_fails_proofs_but_not_behavior():
    """A sorried seed proof refutes the verification class (hasSorry —
    sorry exits 0) while the executable class attests the PINNED binary,
    which still stands: provability and behavior stay independent."""
    orig = PROOFS.read_text()
    sorried = orig.replace(
        "  have hnl : ¬ (temp < sp.low) := by omega\n"
        "  simp [computeFanCmd, hnh, hnl]",
        "  sorry")
    assert sorried != orig
    PROOFS.write_text(sorried)
    try:
        check = _tier_verdict(f"{PREFIX}_verification")
        assert not check.passed
        assert any("sorry" in (c.reason or "").lower() for c in check.failing())
        behavior = _tier_verdict(f"{PREFIX}_executable")
        assert behavior.passed, behavior
    finally:
        PROOFS.write_text(orig)


# ── the progress view (step 2: per-declaration proof status) ──────────────────

def _checklist():
    """The goals checklist exactly as status_flow assembles it: rows from
    the BLESSED Spec bytes (model fixture golden), cells from a live
    verification verdict."""
    import base64

    from pybb.attestation.proof_status import goal_checklist

    model = ProtocolDir.load(str(FIXTURES / f"{PREFIX}_model"))
    blessed = next(
        base64.b64decode(a["golden_b64"]).decode()
        for a in model.asp_args["readfile"].values()
        if a["filepath"] == str(PROPS) and a.get("golden_b64"))
    verdict = _tier_verdict(f"{PREFIX}_verification")
    return goal_checklist(
        blessed, verdict,
        f"{PREFIX}_proofs_verification_targ",
        f"{PREFIX}_acceptance_verification_targ", PROOFS)


@needs_lean
def test_status_clean_tree_all_goals_proved_with_witnesses():
    rows = {r.label: r for r in _checklist().rows}
    assert rows["fanOn_when_hot_prop"].witnesses == ["fanOn_when_hot"]
    assert rows["fanHold_in_band_prop"].witnesses == ["fanHold_in_band"]
    assert all(r.status.state == "proved" for r in rows.values()), rows


@needs_lean
def test_status_sorried_proof_refines_to_exactly_that_goal():
    """The progress signal: a sorried witness marks ITS goal failing
    (hasSorry mapped into the declaration span); the other goals stay
    proved (every diagnostic mapped -> derived ✓), and the binding still
    elaborates through the sorry axiom."""
    orig = PROOFS.read_text()
    sorried = orig.replace(
        "  have hnl : ¬ (temp < sp.low) := by omega\n"
        "  simp [computeFanCmd, hnh, hnl]",
        "  sorry")
    assert sorried != orig
    PROOFS.write_text(sorried)
    try:
        rows = {r.label: r for r in _checklist().rows}
        assert rows["fanHold_in_band_prop"].status.state == "failing"
        assert "sorry" in rows["fanHold_in_band_prop"].status.detail
        for label in ("fanOn_when_hot_prop", "fanOff_when_cold_prop",
                      "fanOn_only_if_hot_or_held_prop",
                      "Spec bound (acceptance)"):
            assert rows[label].status.state == "proved", label
    finally:
        PROOFS.write_text(orig)


@needs_lean
def test_status_weakened_binding_fails_only_the_spec_row():
    orig = PROOFS.read_text()
    weakened = orig.replace(
        "theorem spec_holds : Spec computeFanCmd := by",
        "theorem spec_holds : True := trivial\n\n"
        "theorem spec_holds_unbound : Spec computeFanCmd := by")
    assert weakened != orig
    PROOFS.write_text(weakened)
    try:
        rows = {r.label: r for r in _checklist().rows}
        assert rows["Spec bound (acceptance)"].status.state == "failing"
        assert all(rows[p].status.state == "proved"
                   for p in rows if p != "Spec bound (acceptance)")
    finally:
        PROOFS.write_text(orig)


# ── goal-directed synthesis (step 4) ──────────────────────────────────────────

def _lean_workflow():
    sys.path.insert(0, str(REPO / "examples"))
    import lean_workflow
    return lean_workflow


@needs_lean
def test_synthesis_proves_all_goals_from_sorries():
    """THE HEADLINE: stub every seed proof to sorry (goals blessed,
    nothing proved) and let the workflow take over — the tactic
    portfolio proves every goal, each locally-clean state is judged by
    fresh measurement (restart), and the run ends in good standing with
    the checklist all proved. The portfolio-adequacy contract."""
    goals, lw = _goals_example(), _lean_workflow()
    committed = PROOFS.read_bytes()
    protocols = lw.load_protocols(goals.CONFIG, validate=True)
    ctl = lw.synthesize_flow(goals.CONFIG, protocols, keep=False)
    entry = ctl.blackboard.entries[f"{PREFIX}:verification"]
    assert entry.good_standing and not ctl.blackboard.escalate
    assert ctl.blackboard.restarts.get(f"{PREFIX}:verification", 0) >= 1
    assert PROOFS.read_bytes() == committed  # seeds restored (no --keep)


@needs_lean
def test_synthesis_without_engines_escalates_as_the_human_rung():
    """No engine can act: the verification entry escalates with its
    failing verdict (every sorried goal refuted) — the human handoff —
    and no restart was ever spent."""
    import dataclasses

    goals, lw = _goals_example(), _lean_workflow()
    committed = PROOFS.read_bytes()
    cfg = dataclasses.replace(goals.CONFIG, synthesis_engines=[])
    protocols = lw.load_protocols(cfg, validate=True)
    ctl = lw.synthesize_flow(cfg, protocols, keep=False)
    assert f"{PREFIX}:verification" in ctl.blackboard.escalate
    entry = ctl.blackboard.escalate[f"{PREFIX}:verification"]
    assert not entry.result.passed
    failing = {c.targ_id for c in entry.result.failing()}
    assert f"{PREFIX}_proofs_verification_targ" in failing
    assert ctl.blackboard.restarts == {}
    assert PROOFS.read_bytes() == committed


@needs_lean
def test_bless_lint_refuses_proofs_and_noncanonical_binding():
    """The blessing gate: a statements file containing a theorem, and an
    obligation binding that differs from the canonical form, are both
    refused before anything is signed."""
    goals = _goals_example()

    orig_props = PROPS.read_text()
    PROPS.write_text(orig_props.replace(
        "end TempControl",
        "theorem sneaky : True := trivial\n\nend TempControl"))
    try:
        with pytest.raises(SystemExit, match="admits only"):
            goals.bless_lint(goals.CONFIG)
    finally:
        PROPS.write_text(orig_props)

    orig_acc = ACCEPTANCE.read_text()
    ACCEPTANCE.write_text(orig_acc.replace(
        "TempControl.Spec TempControl.computeFanCmd", "True"))
    try:
        with pytest.raises(SystemExit, match="canonical obligation binding"):
            goals.bless_lint(goals.CONFIG)
    finally:
        ACCEPTANCE.write_text(orig_acc)

    goals.bless_lint(goals.CONFIG)  # clean tree re-blesses fine
