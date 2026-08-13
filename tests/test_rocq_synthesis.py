"""
Rocq phase-2 units and arcs: splicing, the tactic portfolio, the
audit-backed status/checklist join, the blessing lint, the LLM prompt
headers, and the synthesis/impl-first/repair arcs against the real
toolchain.

Layout mirrors the Lean split (test_synthesis / test_proof_status /
test_integration_goals): everything above the RUN_ROCQ line is ungated
(no CVM, no rocq/dune — the bless_lint refusal tests trip the STATIC
checks, which short-circuit before the standalone-elaboration compile);
the arcs below need RUN_ROCQ=1 plus the CVM stack, and anything that
would spend LLM tokens stays behind RUN_LLM (the stub-backend arcs here
need no keys).
"""

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pybb.attestation import (
    GoalContext,
    ImplContext,
    PackageContext,
    RepairContext,
    RocqLlmEngine,
    RocqOutOfBandRepairKS,
    RocqLlmImplEngine,
    RocqLlmPackageEngine,
    RocqPackageSynthesisKS,
    RocqTacticPortfolioEngine,
    splice_impl_rocq,
    splice_proof_rocq,
    stub_impl_axiom,
)
from pybb.attestation.rocq_synthesis import (
    _isolated_status,
    isolation_variant_text,
    parse_file_blocks,
)
from pybb.attestation.appraisal import ComponentResult
from pybb.attestation.knowledge_sources import Verdict
from pybb.attestation.proof_status import (
    FAILING,
    NO_WITNESS,
    PROVED,
    UNKNOWN,
    DeclStatus,
)
from pybb.attestation.rocq_status import (
    parse_audit_sections,
    parse_build_errors,
    rocq_audit_status,
    rocq_goal_checklist,
    rocq_spec_conjuncts,
)

REPO = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN_ROOT = REPO / "golden"
ROCQ_ROOT = REPO / "targets" / "temp-control-rocq"
PROPS = ROCQ_ROOT / "TempControl" / "Props.v"
PROOFS = ROCQ_ROOT / "TempControl" / "Proofs.v"
IMPL = ROCQ_ROOT / "TempControl" / "Impl.v"
ACCEPTANCE = ROCQ_ROOT / "TempControl" / "Acceptance.v"
ROCQ_WRAPPER = Path.home() / "Claude_workspace/bin/rocq"
DUNE_WRAPPER = Path.home() / "Claude_workspace/bin/dune"
PREFIX = "temp_control_rocq"


def _rocq_example():
    sys.path.insert(0, str(REPO / "examples"))
    import temp_control_rocq
    return temp_control_rocq


def _rocq_workflow():
    sys.path.insert(0, str(REPO / "examples"))
    import rocq_workflow
    return rocq_workflow


# ── splicing ──────────────────────────────────────────────────────────────────

ROCQ_TEXT = """From Stdlib Require Import ZArith.

Theorem alpha : alpha_prop computeFanCmd.
Proof.
  unfold alpha_prop.
  auto.
Qed.

Theorem two_line :
    beta_prop computeFanCmd.
Proof.
Admitted.

Definition term_style : nat := 3.
"""


def test_splice_proof_rocq_preserves_statement_and_reverts():
    spliced = splice_proof_rocq(ROCQ_TEXT, "alpha", "  lia.")
    assert ("Theorem alpha : alpha_prop computeFanCmd.\n"
            "Proof.\n  lia.\nQed.") in spliced
    assert "unfold alpha_prop" not in spliced
    # neighbors untouched, multi-line statements kept intact
    assert ("Theorem two_line :\n    beta_prop computeFanCmd.\n"
            "Proof.\nAdmitted.") in spliced
    spliced2 = splice_proof_rocq(ROCQ_TEXT, "two_line", "  trivial.")
    assert ("Theorem two_line :\n    beta_prop computeFanCmd.\n"
            "Proof.\n  trivial.\nQed.") in spliced2
    with pytest.raises(KeyError):
        splice_proof_rocq(ROCQ_TEXT, "no_such_decl", "  trivial.")


def test_splice_proof_rocq_strips_frames_and_admitted_terminates():
    # an LLM habitually wraps the inner script in the Proof./Qed. frame
    framed = splice_proof_rocq(ROCQ_TEXT, "alpha", "Proof.\n  lia.\nQed.")
    assert framed == splice_proof_rocq(ROCQ_TEXT, "alpha", "  lia.")
    defined = splice_proof_rocq(ROCQ_TEXT, "alpha", "Proof.\n  lia.\nDefined.")
    assert defined == framed
    # Admitted. is its own terminator: no Qed. is appended after it
    stubbed = splice_proof_rocq(ROCQ_TEXT, "alpha", "Admitted.")
    assert ("Theorem alpha : alpha_prop computeFanCmd.\n"
            "Proof.\nAdmitted.") in stubbed
    assert "Admitted.\nQed." not in stubbed


def test_splice_proof_rocq_refuses_term_style_proofs():
    with pytest.raises(KeyError, match="term-style"):
        splice_proof_rocq(ROCQ_TEXT, "term_style", "  trivial.")


IMPL_TEXT = """Require Export TempControl.Props.

Definition computeFanCmd (temp : Z) (sp : SetPoint) (latest : FanCmd)
    : FanCmd :=
  if high sp <? temp then On
  else latest.
"""


def test_stub_impl_axiom_and_splice_impl_roundtrip():
    stubbed = stub_impl_axiom(IMPL_TEXT, "computeFanCmd")
    assert ("Definition computeFanCmd (temp : Z) (sp : SetPoint) "
            "(latest : FanCmd)\n    : FanCmd.\nProof.\nAdmitted.") in stubbed
    assert "if high sp" not in stubbed
    # splice a term back into the stub form (the impl rung's move)
    filled = splice_impl_rocq(stubbed, "computeFanCmd", "latest")
    assert ": FanCmd :=\n  latest." in filled
    assert "Admitted" not in filled
    # and into the ordinary := form (a re-splice after rejection)
    refilled = splice_impl_rocq(IMPL_TEXT, "computeFanCmd", "On")
    assert ": FanCmd :=\n  On." in refilled
    with pytest.raises(KeyError):
        splice_impl_rocq(IMPL_TEXT, "no_such_decl", "On")
    with pytest.raises(KeyError):
        stub_impl_axiom("Parameter mystery : nat.\n", "mystery")


def test_driver_stubs_break_and_impl_as_axiom():
    """_stub_proofs admits every Theorem/Lemma (Examples only in the
    impl-first widening), _break_proof corrupts one body with the
    statement untouched, _stub_impl produces the impl-as-axiom form."""
    rocq, rw = _rocq_example(), _rocq_workflow()
    cfg = rocq.CONFIG
    committed_proofs, committed_impl = PROOFS.read_bytes(), IMPL.read_bytes()
    try:
        original = rw._stub_proofs(cfg)
        assert original == committed_proofs
        text = PROOFS.read_text()
        assert text.count("Proof.\nAdmitted.") == 6
        assert "reflexivity" in text  # Example vectors untouched by default
        PROOFS.write_bytes(committed_proofs)

        rw._stub_proofs(cfg, kinds=("Theorem", "Lemma", "Example"))
        assert PROOFS.read_text().count("Proof.\nAdmitted.") == 9
        PROOFS.write_bytes(committed_proofs)

        rw._break_proof(cfg)
        text = PROOFS.read_text()
        assert "Theorem fanHold_in_band : fanHold_in_band_prop computeFanCmd." \
            in text
        assert ("Proof.\n  intros. reflexivity.\nQed.") in text
        PROOFS.write_bytes(committed_proofs)

        rw._stub_impl(cfg)
        assert ": FanCmd.\nProof.\nAdmitted." in IMPL.read_text()
    finally:
        PROOFS.write_bytes(committed_proofs)
        IMPL.write_bytes(committed_impl)


# ── the audit -> status join ──────────────────────────────────────────────────

GOALS = ["helper", "hot_ok", "spec_holds", "acceptance"]

CLOSED = "Closed under the global context\n"


def _cmd(targ, passed, status=0, stdout="", stderr="", reason="", meta=""):
    ev = json.dumps({"status": status, "stdout": stdout, "stderr": stderr})
    return ComponentResult(
        appr_asp="run_command_rocq_appr", target_asp="run_command_rocq",
        targ_id=targ, passed=passed, reason=reason,
        args={"metadata": meta} if meta else {},
        measured_b64=base64.b64encode(ev.encode()).decode())


def _verdict(*components, error=""):
    return Verdict(protocol="stub", passed=all(c.passed for c in components),
                   components=list(components), error=error)


BUILD, AUDIT = "build_targ", "audit_targ"


def _witness_file(tmp_path):
    f = tmp_path / "Proofs.v"
    f.write_text("""Require Export TempControl.Impl.

Theorem helper : True.
Proof.
  auto.
Qed.

Theorem hot_ok : hot_prop step.
Proof.
  auto.
Qed.

Theorem spec_holds : Spec step.
Proof.
  auto.
Qed.
""")
    return f


def _audit_file(tmp_path):
    f = tmp_path / "Assumptions.v"
    f.write_text("Require Import TempControl.Proofs.\n\n"
                 + "".join(f"Print Assumptions {g}.\n" for g in GOALS))
    return f


def test_parse_audit_sections_mirrors_the_appraiser():
    stdout = (CLOSED
              + "Axioms:\nfanHold_in_band : fanHold_in_band_prop f\n"
              + "Axioms:\nconvenient :\n  some type that\n  wraps lines\n"
                "second_axiom : T\n"
              + CLOSED)
    sections = parse_audit_sections(stdout)
    assert sections == [None, ["fanHold_in_band"],
                        ["convenient", "second_axiom"], None]
    assert parse_build_errors(
        'File "./TempControl/Proofs.v", line 27, characters 10-21:\n'
        "Error: Cannot find a relation to rewrite.\n") == \
        [("./TempControl/Proofs.v", 27,
          "Error: Cannot find a relation to rewrite.")]


def test_audit_status_closed_admitted_and_foreign_axiom(tmp_path):
    w, a = _witness_file(tmp_path), _audit_file(tmp_path)
    stdout = (CLOSED + "Axioms:\nhot_ok : hot_prop step\n"
              + "Axioms:\nconvenient : hot_prop step\n" + CLOSED)
    v = _verdict(_cmd(BUILD, True), _cmd(AUDIT, False, stdout=stdout))
    st = rocq_audit_status(v, BUILD, AUDIT, GOALS, w, a)
    assert st["helper"].state == PROVED
    assert st["hot_ok"].state == FAILING
    assert st["hot_ok"].detail == "uses Admitted"
    assert st["spec_holds"].state == FAILING
    assert st["spec_holds"].detail == "depends on axiom: convenient"
    assert st["acceptance"].state == PROVED
    # the ASP's PASS is the word: no evidence needed to mark proved
    clean = _verdict(_cmd(BUILD, True),
                     _cmd(AUDIT, True, stdout=CLOSED * 4))
    assert {s.state for s in
            rocq_audit_status(clean, BUILD, AUDIT, GOALS, w, a).values()} \
        == {PROVED}


def test_audit_status_count_mismatch_fails_closed(tmp_path):
    w, a = _witness_file(tmp_path), _audit_file(tmp_path)
    v = _verdict(_cmd(BUILD, True), _cmd(AUDIT, False, stdout=CLOSED * 2))
    st = rocq_audit_status(v, BUILD, AUDIT, GOALS, w, a)
    assert {s.state for s in st.values()} == {UNKNOWN}
    assert "4 goals but 2" in st["helper"].detail


def test_audit_status_missing_witness_named_by_print_line(tmp_path):
    """Audit compile failure with the build green: the failing
    `Print Assumptions` line names the goal; sections already printed
    keep their verdicts; goals past the stop are unknown."""
    w, a = _witness_file(tmp_path), _audit_file(tmp_path)
    lines = a.read_text().splitlines()
    hot_line = next(i for i, l in enumerate(lines, 1)
                    if l == "Print Assumptions hot_ok.")
    stderr = (f'File "./Assumptions.v", line {hot_line}, characters 18-24:\n'
              "Error: The reference hot_ok was not found in the current\n"
              "environment.\n")
    v = _verdict(_cmd(BUILD, True),
                 _cmd(AUDIT, False, status=1, stdout=CLOSED, stderr=stderr))
    st = rocq_audit_status(v, BUILD, AUDIT, GOALS, w, a)
    assert st["helper"].state == PROVED          # its section printed
    assert st["hot_ok"].state == FAILING
    assert "witness missing" in st["hot_ok"].detail
    assert st["spec_holds"].state == UNKNOWN     # audit stopped first
    assert st["acceptance"].state == UNKNOWN


def test_audit_status_build_failure_maps_stderr_else_poisons(tmp_path):
    w, a = _witness_file(tmp_path), _audit_file(tmp_path)
    stderr = ('File "./TempControl/Proofs.v", line 9, characters 2-6:\n'
              "Error: tactic failure.\n")
    v = _verdict(_cmd(BUILD, False, status=1, stderr=stderr),
                 _cmd(AUDIT, True, stdout=CLOSED * 4))
    st = rocq_audit_status(v, BUILD, AUDIT, GOALS, w, a)
    assert st["hot_ok"].state == FAILING         # line 9 is in hot_ok's span
    assert "tactic failure" in st["hot_ok"].detail
    # a green audit over a failed build upgrades NOTHING
    for goal in ("helper", "spec_holds", "acceptance"):
        assert st[goal].state == UNKNOWN
    unmappable = _verdict(
        _cmd(BUILD, False, status=1, stderr="dune: something exploded",
             reason="Rocq command failed (status 1)"),
        _cmd(AUDIT, True, stdout=CLOSED * 4))
    st = rocq_audit_status(unmappable, BUILD, AUDIT, GOALS, w, a)
    assert {s.state for s in st.values()} == {UNKNOWN}


def test_isolation_variant_text_admits_only_other_goals(tmp_path):
    text = _witness_file(tmp_path).read_text()
    variant = isolation_variant_text(text, "hot_ok", ["hot_ok", "spec_holds"])
    # the target's real body is kept
    assert "Theorem hot_ok : hot_prop step.\nProof.\n  auto.\nQed." in variant
    # the sibling is admitted, statement byte-identical
    assert "Theorem spec_holds : Spec step.\nProof.\nAdmitted." in variant
    # the helper is untouched (not in the admit set)
    assert "Theorem helper : True.\nProof.\n  auto.\nQed." in variant
    with pytest.raises(KeyError):
        isolation_variant_text(text, "hot_ok", ["missing_goal"])


def test_isolated_status_mapping():
    adm = {"hot_ok", "spec_holds"}
    assert _isolated_status("hot_ok", None, adm).state == PROVED
    st = _isolated_status("spec_holds", ["hot_ok"], adm)
    assert st.state == PROVED and "assumes hot_ok" in st.detail
    st = _isolated_status("hot_ok", ["convenient"], adm)
    assert st.state == FAILING and "convenient" in st.detail
    st = _isolated_status("hot_ok", ["hot_ok"], adm)
    assert st.state == FAILING and "uses Admitted" in st.detail
    assert _isolated_status("hot_ok", [], adm).state == UNKNOWN


def test_audit_status_isolation_refines_build_failure(tmp_path):
    w, a = _witness_file(tmp_path), _audit_file(tmp_path)
    stderr = ('File "./TempControl/Proofs.v", line 9, characters 2-6:\n'
              "Error: tactic failure.\n")
    v = _verdict(_cmd(BUILD, False, status=1, stderr=stderr),
                 _cmd(AUDIT, True, stdout=CLOSED * 4))
    refined = {
        "hot_ok": DeclStatus(state=FAILING, detail="isolated: tactic failure"),
        "helper": DeclStatus(state=PROVED, detail="isolated: proof intact"),
        "spec_holds": DeclStatus(
            state=PROVED, detail="isolated: script intact; assumes hot_ok "
                                 "(judged separately)"),
        "not_a_goal": DeclStatus(state=PROVED, detail="smuggled"),
    }
    st = rocq_audit_status(v, BUILD, AUDIT, GOALS, w, a,
                           isolate=lambda: refined)
    assert st["helper"].state == PROVED and "isolated" in st["helper"].detail
    assert st["hot_ok"].state == FAILING
    assert st["spec_holds"].state == PROVED
    # a goal the refinement did not judge keeps the coarse fallback
    assert st["acceptance"].state == UNKNOWN
    # the refinement can never ADD goals to the audited set
    assert "not_a_goal" not in st
    # a refusal (None) keeps the coarse fallback intact
    st = rocq_audit_status(v, BUILD, AUDIT, GOALS, w, a, isolate=lambda: None)
    assert st["hot_ok"].state == FAILING and st["helper"].state == UNKNOWN
    # isolation runs ONLY on build failure — a green build never calls it
    calls = []
    green = _verdict(_cmd(BUILD, True), _cmd(AUDIT, True, stdout=CLOSED * 4))
    rocq_audit_status(green, BUILD, AUDIT, GOALS, w, a,
                      isolate=lambda: calls.append(1) or {})
    assert not calls


def test_audit_status_tool_poisoning_and_protocol_error(tmp_path):
    w, a = _witness_file(tmp_path), _audit_file(tmp_path)
    poisoned = _verdict(
        _cmd(BUILD, True), _cmd(AUDIT, True, stdout=CLOSED * 4),
        ComponentResult(appr_asp="goldenbytes_appr", target_asp="hashfile",
                        targ_id="tool_rocq_rocq_targ", passed=False,
                        args={"metadata": "tool::rocq"}))
    assert {s.state for s in
            rocq_audit_status(poisoned, BUILD, AUDIT, GOALS, w, a).values()} \
        == {UNKNOWN}
    errored = Verdict(protocol="stub", passed=False, error="cvm died")
    assert {s.state for s in
            rocq_audit_status(errored, BUILD, AUDIT, GOALS, w, a).values()} \
        == {UNKNOWN}


# ── the goals checklist ───────────────────────────────────────────────────────

BLESSED = """Definition hot_prop (f : Step) : Prop := True.
Definition cold_prop (f : Step) : Prop := True.

Definition Spec (f : Step) : Prop :=
  hot_prop f /\\ cold_prop f.
"""

CHECK_GOALS = ["hot_ok", "acceptance"]


def test_rocq_spec_conjuncts_from_the_committed_blessing():
    assert rocq_spec_conjuncts(PROPS.read_text()) == [
        "fanOn_when_hot_prop", "fanOff_when_cold_prop",
        "fanHold_in_band_prop", "fanOn_only_if_hot_or_held_prop"]
    assert rocq_spec_conjuncts(BLESSED) == ["hot_prop", "cold_prop"]


def test_checklist_witness_matching_and_unaudited_downgrade(tmp_path):
    """Witnesses match on the STATEMENT part only (an `unfold cold_prop`
    inside a proof body is not a witness -> no-witness row), and a
    witness outside the audited goal set is UNKNOWN, never presumed
    proved."""
    f = tmp_path / "Proofs.v"
    f.write_text("""Theorem hot_ok : hot_prop step.
Proof.
  auto.
Qed.

Theorem cold_sneaky : True.
Proof.
  unfold cold_prop.
  auto.
Qed.

Theorem hot_extra : hot_prop step.
Proof.
  auto.
Qed.
""")
    v = _verdict(_cmd(BUILD, True), _cmd(AUDIT, True, stdout=CLOSED * 2))
    checklist = rocq_goal_checklist(BLESSED, v, BUILD, AUDIT, CHECK_GOALS,
                                    "acceptance", f)
    rows = {r.label: r for r in checklist.rows}
    assert rows["hot_prop"].witnesses == ["hot_ok", "hot_extra"]
    # hot_extra is live but unaudited: the row downgrades to unknown
    assert rows["hot_prop"].status.state == UNKNOWN
    assert "not in the audited goal set" in rows["hot_prop"].status.detail
    assert rows["cold_prop"].status.state == NO_WITNESS
    assert rows["Spec bound (acceptance)"].status.state == PROVED


def test_checklist_admitted_row_and_binding_from_audit(tmp_path):
    f = tmp_path / "Proofs.v"
    f.write_text("""Theorem hot_ok : hot_prop step.
Proof.
Admitted.
""")
    stdout = ("Axioms:\nhot_ok : hot_prop step\n"
              + "Axioms:\nhot_ok : hot_prop step\n")
    v = _verdict(_cmd(BUILD, True), _cmd(AUDIT, False, stdout=stdout))
    rows = {r.label: r for r in rocq_goal_checklist(
        BLESSED, v, BUILD, AUDIT, CHECK_GOALS, "acceptance", f).rows}
    assert rows["hot_prop"].status.state == FAILING
    assert rows["hot_prop"].status.detail == "uses Admitted"
    binding = rows["Spec bound (acceptance)"].status
    assert binding.state == FAILING
    assert binding.detail == "depends on axiom: hot_ok"


# ── engines ───────────────────────────────────────────────────────────────────

def test_tactic_portfolio_shapes():
    engine = RocqTacticPortfolioEngine()
    prop_cands = list(engine(GoalContext(
        name="w", statement="Theorem w : hot_prop computeFanCmd.",
        prop="hot_prop", helpers=["SetPoint_valid"],
        impl_name="computeFanCmd")))
    assert "unfold hot_prop, computeFanCmd" in prop_cands[0]
    assert any("SetPoint_valid" in c for c in prop_cands)
    # name-agnostic Z.ltb destruction, goal- and hypothesis-side
    assert any("|- context [?a <? ?b]" in c for c in prop_cands)
    assert any("H : context [?a <? ?b]" in c for c in prop_cands)
    assert all("Proof." not in c and "Qed." not in c for c in prop_cands)

    binding = list(engine(GoalContext(
        name="spec_holds", statement="Theorem spec_holds : Spec f.",
        binding=True, witnesses=["a", "b", "c", "d"])))
    assert binding == ["  exact (conj a (conj b (conj c d)))."]
    solo = list(engine(GoalContext(
        name="spec_holds", statement="", binding=True, witnesses=["a"])))
    assert solo == ["  exact a."]
    assert list(engine(GoalContext(
        name="spec_holds", statement="", binding=True))) == []

    helper_cands = list(engine(GoalContext(
        name="lemma1", statement="Lemma lemma1 : X.",
        helpers=["SetPoint_valid"])))
    assert "  unfold SetPoint_valid. intros. lia." in helper_cands
    assert "  unfold SetPoint_valid in *. intros. lia." in helper_cands
    assert helper_cands[-1] == "  intros. lia."


def test_rocq_llm_prompts_and_stub_seed():
    ctx = GoalContext(
        name="w", statement="Theorem w : hot_prop computeFanCmd.",
        blessed_statement="Definition hot_prop ...",
        detail="uses Admitted", seed="Admitted.",
        context_files={"TempControl/Props.v": "Definition hot_prop ..."})
    silent = RocqLlmEngine()  # no backend
    assert list(silent(ctx)) == []
    prompts = []

    def complete(prompt):
        prompts.append(prompt)
        return "  lia."

    armed = RocqLlmEngine(complete=complete, attempts=2)
    assert list(armed(ctx)) == ["lia.", "lia."]
    assert "Rocq" in prompts[0] and "tactic script" in prompts[0]
    assert "between `Proof.` and `Qed.`" in prompts[0]
    assert "TempControl/Props.v" in prompts[0]
    assert "uses Admitted" in prompts[0]
    # the Admitted stub is not guidance — never forwarded as an attempt
    assert "Previous attempt" not in prompts[0]
    # resumed => rejected: round 2 carries round 1's candidate
    assert "Rejected attempt 1" in prompts[1]
    seeded = ctx.model_copy(update={"seed": "  intros. reflexivity."})
    list(RocqLlmEngine(complete=complete, attempts=1)(seeded))
    assert "Previous attempt" in prompts[-1]

    impl_prompts = []
    impl = RocqLlmImplEngine(
        complete=lambda p: impl_prompts.append(p) or "latest", attempts=1)
    cands = list(impl(ImplContext(
        name="computeFanCmd",
        signature="Definition computeFanCmd ... : FanCmd",
        blessed_statement="Definition Spec ...",
        context_files={"TempControl/Props.v": "Definition Spec ..."})))
    assert cands == ["latest"]
    assert "ONLY the term" in impl_prompts[0] and "Rocq" in impl_prompts[0]
    assert "Definition Spec ..." in impl_prompts[0]


def test_cli_rejects_llm_flags_without_opt_in_chain():
    example = REPO / "examples" / "temp_control_rocq.py"
    for argv, expected in [
        (["--llm-only", "--synthesize"], "--llm-only requires --llm"),
        (["--llm", "openai"], "use it with --synthesize"),
        (["--llm-dry-run"], "tunes the armed LLM"),
        (["--synthesize-impl", "--break-proof", "--llm", "openai"],
         "different starting states"),
    ]:
        proc = subprocess.run(
            [sys.executable, str(example), *argv],
            capture_output=True, text=True, cwd=REPO)
        assert proc.returncode != 0
        assert expected in proc.stderr


def test_cli_package_arc_opt_in_and_exclusivity():
    example = REPO / "examples" / "temp_control_rocq.py"
    for argv, expected in [
        (["--synthesize-package"], "use it with --llm"),
        (["--synthesize-package", "--synthesize-impl",
          "--llm", "openai", "--llm-dry-run"], "different arcs"),
        (["--synthesize-package", "--break-proof",
          "--llm", "openai", "--llm-dry-run"], "different arcs"),
    ]:
        proc = subprocess.run(
            [sys.executable, str(example), *argv],
            capture_output=True, text=True, cwd=REPO)
        assert proc.returncode != 0
        assert expected in proc.stderr


# ── the whole-package rung (units — no toolchain) ─────────────────────────────

def test_parse_file_blocks_and_package_engine_protocol():
    reply = ("preamble the model was told not to write\n"
             "=== FILE: TempControl/Impl.v ===\n"
             "```coq\nDefinition computeFanCmd := On.\n```\n"
             "=== FILE: TempControl/Proofs.v ===\n"
             "Theorem a : True.\nProof. auto. Qed.\n")
    blocks = parse_file_blocks(reply)
    assert blocks["TempControl/Impl.v"] == "Definition computeFanCmd := On.\n"
    assert blocks["TempControl/Proofs.v"].startswith("Theorem a")
    assert parse_file_blocks("no headers here") == {}

    ctx = PackageContext(
        impl_rel="TempControl/Impl.v", proofs_rel="TempControl/Proofs.v",
        impl_name="computeFanCmd",
        blessed_statement="Definition Spec ...",
        context_files={"TempControl/Props.v": "Definition hot_prop ..."},
        files={"TempControl/Impl.v": "Definition computeFanCmd ... Admitted.",
               "TempControl/Proofs.v": "Theorem a : ... Admitted."},
        audit_goals=["a", "acceptance"], failing=["a", "acceptance"],
        detail="- a: uses Admitted")
    assert list(RocqLlmPackageEngine()(ctx)) == []  # no backend

    prompts = []
    replies = ["only prose, no file blocks", reply]

    def complete(prompt):
        prompts.append(prompt)
        return replies[len(prompts) - 1]

    armed = RocqLlmPackageEngine(complete=complete, attempts=2)
    candidates = list(armed(ctx))
    # reply 1 is self-rejected (no blocks) without reaching the judge
    assert len(candidates) == 1
    assert candidates[0]["TempControl/Impl.v"].startswith("Definition")
    assert ctx.rejections and "no `=== FILE:" in ctx.rejections[0]["errors"]
    assert "Rocq" in prompts[0] and "=== FILE:" in prompts[0]
    assert "TempControl/Props.v" in prompts[0]      # the blessed context
    assert "Currently open goals: a, acceptance" in prompts[0]
    assert "uses Admitted" in prompts[0]
    assert "Closed under the global context" in prompts[0]
    # round 2 carries round 1's self-rejection as feedback
    assert "Rejected attempt" in prompts[1]


class _ScriptedPackageKS(RocqPackageSynthesisKS):
    """The package rung with scripted senses: each _live_sections call
    pops the next (sections, err) — no toolchain involved."""

    script: list = []

    def _live_sections(self):
        return self.script.pop(0)


def test_package_ks_monotone_acceptance(tmp_path):
    impl = tmp_path / "Impl.v"
    proofs = tmp_path / "Proofs.v"
    impl.write_text("Definition impl : nat.\nProof.\nAdmitted.\n")
    proofs.write_text("Theorem a : True.\nProof.\nAdmitted.\n")
    goals = ["a", "b", "acceptance"]
    all_open = [["a"], ["b"], ["acceptance"]]

    cand = {n: {"Impl.v": f"(* impl {n} *)\nDefinition impl := 1.\n",
                "Proofs.v": f"(* proofs {n} *)\nTheorem a : True.\n"}
            for n in range(1, 5)}
    contexts = []

    def engine(ctx):
        contexts.append(ctx)
        yield cand[1]   # build breaks            -> rejected, reverted
        yield cand[2]   # closes 'a'              -> accepted, kept
        yield cand[3]   # reopens 'a'             -> rejected, reverted
        yield cand[4]   # closes everything       -> accepted, returns

    ks = _ScriptedPackageKS(
        engines=[engine], blessed=lambda: "Definition Spec := True.\n",
        package_root=str(tmp_path), impl_rel="Impl.v", proofs_rel="Proofs.v",
        impl_name="impl", audit_goals=goals,
        script=[
            (all_open, ""),                                # initial look
            (None, "Error: boom (universe inconsistency)"),  # cand 1
            ([None, ["b"], ["acceptance"]], ""),           # cand 2
            ([["a"], None, ["acceptance"]], ""),           # cand 3
            ([None, None, None], ""),                      # cand 4
        ])
    assert ks._synthesize(RepairContext(key="k", verdict=None)) is True
    assert ks.script == []
    # the accepted tree is the last candidate's
    assert impl.read_text() == cand[4]["Impl.v"]
    assert proofs.read_text() == cand[4]["Proofs.v"]
    # rejections carry the refuting text; accepted candidates none
    ctx = contexts[0]
    assert len(ctx.rejections) == 2
    assert "boom" in ctx.rejections[0]["errors"]
    assert "reopened previously-closed goals: a" in ctx.rejections[1]["errors"]
    assert "=== FILE: Impl.v ===" in ctx.rejections[1]["candidate"]
    # progress updated the engine's view after the first acceptance
    assert ctx.failing == []
    assert ctx.files == cand[4]
    # the initial context described the open goals
    assert "- a: uses Admitted" in ctx.detail

    # no-progress candidates are rejected too
    def flat_engine(ctx):
        contexts.append(ctx)
        yield cand[1]
    flat = _ScriptedPackageKS(
        engines=[flat_engine], blessed=lambda: "Definition Spec := True.\n",
        package_root=str(tmp_path), impl_rel="Impl.v", proofs_rel="Proofs.v",
        impl_name="impl", audit_goals=goals,
        script=[(all_open, ""), (all_open, "")])
    assert flat._synthesize(RepairContext(key="k", verdict=None)) is False
    assert "no progress" in contexts[-1].rejections[0]["errors"]

    # stale verdict over an already-clean tree: ask for the measurement
    clean = _ScriptedPackageKS(
        engines=[], blessed=lambda: "", package_root=str(tmp_path),
        impl_rel="Impl.v", proofs_rel="Proofs.v", audit_goals=goals,
        script=[([None, None, None], ""), ([None, None, None], "")])
    assert clean._synthesize(RepairContext(key="k", verdict=None)) is True
    assert clean._locally_clean() is True


class _ScriptedOobKS(RocqOutOfBandRepairKS):
    """The Rocq pause rung with scripted senses (no toolchain)."""

    script: list = []

    def _live_sections(self):
        return self.script.pop(0)


def test_rocq_pause_rung_free_local_iteration():
    """The audit-aware pause rung: each attempt's work order carries the
    LIVE audit state, and 'r' while the audit is dirty spends nothing —
    only a locally-clean tree buys the restart."""
    from pybb.blackboard import Blackboard
    dirty = ([["a"], None], "")            # 'a' open, 'b' closed
    clean = ([None, None], "")
    broken = (None, "Error: boom")
    orders = []
    ks = _ScriptedOobKS(
        gate=lambda order: orders.append(order) or True,
        audit_goals=["a", "b"],
        script=[broken,   # attempt 1 work order: tree not auditable
                dirty,    # attempt 1 local_check: still dirty -> no restart
                dirty,    # attempt 2 work order: 'a' still open
                clean])   # attempt 2 local_check: clean -> restart
    bb = Blackboard()
    bb.write_entry(key="k", predicate="attestation", measurement={})
    ks.execute(bb, ["k"])
    assert bb.restart_requests == {}       # claimed, but locally dirty
    ks.execute(bb, ["k"])
    assert "k" in bb.restart_requests      # locally clean: judged next
    assert ks.script == []
    assert "tree not auditable" in orders[0] and "boom" in orders[0]
    assert "still open (live audit):" in orders[1]
    assert "- a: uses Admitted" in orders[1]
    assert "b" not in orders[1].split("still open")[1].splitlines()[1]


# ── the blessing lint (static refusals — no toolchain) ────────────────────────

def test_bless_lint_refuses_smuggled_proofs_postulates_and_imports():
    rocq = _rocq_example()
    cfg = rocq.CONFIG
    orig_props = PROPS.read_text()

    PROPS.write_text(orig_props + "\nTheorem sneaky : True.\n"
                                  "Proof.\n  auto.\nQed.\n")
    try:
        with pytest.raises(SystemExit, match="admits only"):
            rocq.bless_lint(cfg)
    finally:
        PROPS.write_text(orig_props)

    PROPS.write_text(orig_props + "\nAxiom convenient : forall P : Prop, P.\n")
    try:
        with pytest.raises(SystemExit, match="admits only"):
            rocq.bless_lint(cfg)
    finally:
        PROPS.write_text(orig_props)

    PROPS.write_text("From Corelib Require Import Ltac.\n" + orig_props)
    try:
        with pytest.raises(SystemExit, match="only Stdlib"):
            rocq.bless_lint(cfg)
    finally:
        PROPS.write_text(orig_props)

    orig_acc = ACCEPTANCE.read_text()
    ACCEPTANCE.write_text(orig_acc.replace(
        "Spec computeFanCmd", "True"))
    try:
        with pytest.raises(SystemExit, match="canonical obligation binding"):
            rocq.bless_lint(cfg)
    finally:
        ACCEPTANCE.write_text(orig_acc)


# ── RUN_ROCQ arcs (real toolchain + CVM) ──────────────────────────────────────

from pybb.attestation.client import DEFAULT_ASP_BIN, DEFAULT_CVM_BINARY

needs_rocq = pytest.mark.skipif(
    os.environ.get("RUN_ROCQ") != "1"
    or not (ROCQ_WRAPPER.is_file() and DUNE_WRAPPER.is_file())
    or not (Path(DEFAULT_CVM_BINARY).is_file()
            and Path(DEFAULT_ASP_BIN).is_dir()),
    reason="set RUN_ROCQ=1 (with the workspace rocq/dune wrappers and the "
           "local CVM stack) to run the Rocq synthesis arcs")


@needs_rocq
def test_bless_lint_accepts_the_committed_blessing():
    rocq = _rocq_example()
    rocq.bless_lint(rocq.CONFIG)  # clean tree re-blesses fine


def _live_checklist():
    rocq, rw = _rocq_example(), _rocq_workflow()
    from pybb.attestation import (CvmSubprocessClient, attestation_request,
                                  make_attestation_predicate)
    cfg = rocq.CONFIG
    protocols = rw.load_protocols(cfg)
    verdict = make_attestation_predicate(CvmSubprocessClient(), protocols)(
        attestation_request(cfg.verification_id))
    return rw._checklist(cfg, protocols, verdict)


@needs_rocq
def test_status_clean_tree_all_goals_proved_with_witnesses():
    rows = {r.label: r for r in _live_checklist().rows}
    assert rows["fanOn_when_hot_prop"].witnesses == ["fanOn_when_hot"]
    assert rows["fanHold_in_band_prop"].witnesses == ["fanHold_in_band"]
    assert all(r.status.state == PROVED for r in rows.values()), rows


@needs_rocq
def test_status_admitted_refines_to_exactly_that_goal():
    """The progress signal: an Admitted witness marks ITS goal failing
    ("uses Admitted" — the goal lists itself as an axiom); the other
    prop rows stay proved; the binding row fails NAMING the admitted
    goal it depends on."""
    rocq, rw = _rocq_example(), _rocq_workflow()
    original = rw.tamper_admitted(rocq.CONFIG)
    try:
        rows = {r.label: r for r in _live_checklist().rows}
        assert rows["fanHold_in_band_prop"].status.state == FAILING
        assert rows["fanHold_in_band_prop"].status.detail == "uses Admitted"
        for label in ("fanOn_when_hot_prop", "fanOff_when_cold_prop",
                      "fanOn_only_if_hot_or_held_prop"):
            assert rows[label].status.state == PROVED, label
        binding = rows["Spec bound (acceptance)"].status
        assert binding.state == FAILING
        assert "fanHold_in_band" in binding.detail
    finally:
        PROOFS.write_bytes(original)


@needs_rocq
def test_status_smuggled_axiom_row_names_the_axiom():
    rocq, rw = _rocq_example(), _rocq_workflow()
    original = rw.tamper_axiom(rocq.CONFIG)
    try:
        rows = {r.label: r for r in _live_checklist().rows}
        status = rows["fanHold_in_band_prop"].status
        assert status.state == FAILING
        assert "convenient" in status.detail and "Admitted" not in status.detail
    finally:
        PROOFS.write_bytes(original)


@needs_rocq
def test_synthesis_proves_all_goals_from_admits():
    """THE HEADLINE: stub every seed proof to Admitted (goals blessed,
    nothing proved — and the build GREEN, which is exactly why the audit
    exists) and let the workflow take over — the tactic portfolio closes
    every goal, the locally-clean state is judged by fresh measurement
    (restart), and the run ends in good standing with the checklist all
    proved. The portfolio-adequacy contract."""
    rocq, rw = _rocq_example(), _rocq_workflow()
    committed = PROOFS.read_bytes()
    cfg = rocq.CONFIG
    ctl = rw.synthesize_flow(cfg, rw.load_protocols(cfg), keep=False)
    entry = ctl.blackboard.entries[f"{PREFIX}:verification"]
    assert entry.good_standing and not ctl.blackboard.escalate
    assert ctl.blackboard.restarts.get(f"{PREFIX}:verification", 0) >= 1
    assert PROOFS.read_bytes() == committed  # seeds restored (no --keep)


@needs_rocq
def test_synthesis_without_engines_escalates_as_the_human_rung():
    """No engine can act: the verification entry escalates with its
    failing verdict — the audit refutes the stubs while the build stays
    green — and no restart was ever spent."""
    rocq, rw = _rocq_example(), _rocq_workflow()
    committed = PROOFS.read_bytes()
    cfg = rocq.CONFIG
    ctl = rw.synthesize_flow(cfg, rw.load_protocols(cfg), keep=False,
                             engines=[])
    assert f"{PREFIX}:verification" in ctl.blackboard.escalate
    entry = ctl.blackboard.escalate[f"{PREFIX}:verification"]
    assert not entry.result.passed
    failing = {c.targ_id for c in entry.result.failing()}
    assert f"{PREFIX}_assumptions_verification_targ" in failing
    assert f"{PREFIX}_build_verification_targ" not in failing, \
        "Admitted stubs elaborate cleanly — only the audit refutes them"
    assert ctl.blackboard.restarts == {}
    assert PROOFS.read_bytes() == committed


@needs_rocq
def test_break_proof_repaired_by_the_portfolio():
    """The repair arc: one seed proof corrupted with a wrong tactic (the
    BUILD fails, with a real error position) — the portfolio replaces
    it, the restart re-attests, good standing."""
    rocq, rw = _rocq_example(), _rocq_workflow()
    committed = PROOFS.read_bytes()
    cfg = rocq.CONFIG
    ctl = rw.synthesize_flow(cfg, rw.load_protocols(cfg), keep=False,
                             stub="break")
    entry = ctl.blackboard.entries[f"{PREFIX}:verification"]
    assert entry.good_standing and not ctl.blackboard.escalate
    assert ctl.blackboard.restarts.get(f"{PREFIX}:verification", 0) >= 1
    assert PROOFS.read_bytes() == committed


@needs_rocq
def test_impl_first_without_engines_escalates():
    """--synthesize-impl with an empty engine ladder: the impl stays an
    admitted axiom, nothing can close, the entry escalates as the human
    rung — and both stub files are restored."""
    rocq, rw = _rocq_example(), _rocq_workflow()
    committed_proofs, committed_impl = PROOFS.read_bytes(), IMPL.read_bytes()
    cfg = rocq.CONFIG
    ctl = rw.synthesize_flow(cfg, rw.load_protocols(cfg), keep=False,
                             engines=[], stub="impl", impl_engines=[])
    assert f"{PREFIX}:verification" in ctl.blackboard.escalate
    assert ctl.blackboard.restarts == {}
    assert PROOFS.read_bytes() == committed_proofs
    assert IMPL.read_bytes() == committed_impl


IMPL_TERM = """if high sp <? temp then On
else if temp <? low sp then Off
else latest"""


@needs_rocq
def test_impl_first_full_arc_with_stub_backend():
    """The impl-first arc end-to-end with a STUB backend (no keys, no
    network): the impl rung derives the implementation from the blessed
    properties alone (its prompt carries Props.v and nothing of the
    proofs), the proof rung closes every goal over it, and the run ends
    in good standing under fresh measurement."""
    rocq, rw = _rocq_example(), _rocq_workflow()
    committed_proofs, committed_impl = PROOFS.read_bytes(), IMPL.read_bytes()
    cfg = rocq.CONFIG
    prompts = []

    def complete(prompt):
        prompts.append(prompt)
        return IMPL_TERM

    ctl = rw.synthesize_flow(
        cfg, rw.load_protocols(cfg), keep=False,
        engines=[RocqTacticPortfolioEngine()], stub="impl",
        impl_engines=[RocqLlmImplEngine(complete=complete, attempts=1)])
    entry = ctl.blackboard.entries[f"{PREFIX}:verification"]
    assert entry.good_standing and not ctl.blackboard.escalate
    assert ctl.blackboard.restarts.get(f"{PREFIX}:verification", 0) >= 2
    assert prompts, "the impl engine was never invoked"
    assert "fanOn_when_hot_prop" in prompts[0]      # the blessed properties
    assert "Z.ltb_spec" not in prompts[0], \
        "the proofs file must not leak into the impl-first context"
    assert PROOFS.read_bytes() == committed_proofs
    assert IMPL.read_bytes() == committed_impl


@needs_rocq
def test_package_arc_with_stub_backend():
    """The whole-package arc end-to-end with a STUB backend (no keys, no
    network): impl and proofs stubbed to admits, ONE rung asks its
    engine for both files together, the oracle replies with the
    committed pair, and the run ends in good standing under fresh
    measurement — a single restart, no impl-then-proofs chain."""
    rocq, rw = _rocq_example(), _rocq_workflow()
    committed_proofs, committed_impl = PROOFS.read_bytes(), IMPL.read_bytes()
    cfg = rocq.CONFIG
    reply = (f"=== FILE: {cfg.impl_rel} ===\n{committed_impl.decode()}"
             f"=== FILE: {cfg.proofs_rel} ===\n{committed_proofs.decode()}")
    prompts = []

    def complete(prompt):
        prompts.append(prompt)
        return reply

    ctl = rw.synthesize_flow(
        cfg, rw.load_protocols(cfg), keep=False, stub="package",
        package_engines=[RocqLlmPackageEngine(complete=complete, attempts=1)])
    entry = ctl.blackboard.entries[f"{PREFIX}:verification"]
    assert entry.good_standing and not ctl.blackboard.escalate
    assert ctl.blackboard.restarts.get(f"{PREFIX}:verification", 0) >= 1
    assert prompts, "the package engine was never invoked"
    assert "fanOn_when_hot_prop" in prompts[0]     # the blessed properties
    assert cfg.impl_rel in prompts[0] and cfg.proofs_rel in prompts[0]
    assert PROOFS.read_bytes() == committed_proofs
    assert IMPL.read_bytes() == committed_impl


@needs_rocq
def test_package_arc_without_engines_escalates():
    """--synthesize-package with an empty ladder: nothing can act, the
    verification entry escalates as the human rung, no restart is ever
    spent, and both stub files are restored."""
    rocq, rw = _rocq_example(), _rocq_workflow()
    committed_proofs, committed_impl = PROOFS.read_bytes(), IMPL.read_bytes()
    cfg = rocq.CONFIG
    ctl = rw.synthesize_flow(cfg, rw.load_protocols(cfg), keep=False,
                             stub="package", package_engines=[])
    assert f"{PREFIX}:verification" in ctl.blackboard.escalate
    assert ctl.blackboard.restarts == {}
    assert PROOFS.read_bytes() == committed_proofs
    assert IMPL.read_bytes() == committed_impl


@needs_rocq
def test_pause_arc_operator_fix_judged_by_fresh_measurement():
    """--break-proof --pause with no engines: the synthesis rung can do
    nothing, the pause rung blocks, the scripted gate performs the
    out-of-band fix (the 'interactive agent session'), and the run ends
    in good standing via the restart's fresh measurement."""
    rocq, rw = _rocq_example(), _rocq_workflow()
    committed = PROOFS.read_bytes()
    cfg = rocq.CONFIG
    orders = []

    def gate(order):
        orders.append(order)
        PROOFS.write_bytes(committed)   # the out-of-band repair
        return True

    ctl = rw.synthesize_flow(cfg, rw.load_protocols(cfg), keep=False,
                             engines=[], stub="break", pause=True, gate=gate)
    entry = ctl.blackboard.entries[f"{PREFIX}:verification"]
    assert entry.good_standing and not ctl.blackboard.escalate
    assert ctl.blackboard.restarts.get(f"{PREFIX}:verification", 0) >= 1
    assert orders and "paused for out-of-band repair" in orders[0]
    assert "tree not auditable" in orders[0]   # break-proof: build fails
    assert PROOFS.read_bytes() == committed


@needs_rocq
def test_pause_skip_falls_through_to_automatic_repair():
    """--tamper --repair --pause with a gate that always declines: the
    pause rungs step aside and the automatic chain (golden restore +
    cross-entry restart) still ends all three entries in good standing."""
    from pybb.attestation import TargetSnapshot

    rocq, rw = _rocq_example(), _rocq_workflow()
    cfg = rocq.CONFIG
    protocols = rw.load_protocols(cfg)
    snapshot = TargetSnapshot.load(
        {pid: protocols[pid] for pid in cfg.protocol_ids}, GOLDEN_ROOT)
    orders = []
    rw.tamper(cfg, protocols)
    try:
        ctl = rw.attest_episode(cfg, protocols, repair=True, pause=True,
                                gate=lambda o: orders.append(o) or False)
        bb = ctl.blackboard
        assert not bb.escalate, bb.escalate
        for question in ("model", "contracts", "verification"):
            assert bb.entries[cfg.entry(question)].good_standing, question
        assert orders, "the pause rung never offered the work order"
    finally:
        snapshot.restore()


@needs_rocq
def test_tamper_repair_ends_all_three_entries_good_standing():
    """The cross-entry restart: a blessed-file tamper fails ALL THREE
    always-run entries; the repair chain restores the file and its
    restart rung carries the verification entry along (revived from
    escalate), so episode 2 ends with model, contracts AND verification
    in good standing — no dead verdict left as the session's word."""
    from pybb.attestation import ProtocolDir, TargetSnapshot

    rocq, rw = _rocq_example(), _rocq_workflow()
    cfg = rocq.CONFIG
    protocols = rw.load_protocols(cfg)
    snapshot = TargetSnapshot.load(
        {pid: protocols[pid] for pid in cfg.protocol_ids}, GOLDEN_ROOT)
    rw.tamper(cfg, protocols)
    try:
        ctl = rw.attest_episode(cfg, protocols, repair=True)
        bb = ctl.blackboard
        assert not bb.escalate, bb.escalate
        for question in ("model", "contracts", "verification"):
            entry = bb.entries[cfg.entry(question)]
            assert entry.good_standing, question
        assert bb.restarts.get(cfg.entry("verification"), 0) == 1
    finally:
        snapshot.restore()
