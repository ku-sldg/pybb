"""
proof_status unit tests — the per-declaration status model and the goals
checklist join, against stub verdicts (no CVM, no Lean). What is pinned:

  - diagnostics parsing tolerates pollution (the cold-build lesson);
  - the downgrade-only rules: proved requires the ASP's PASS, a FAIL is
    only refined (mapped diagnostics -> failing; everything unmappable
    fails closed to unknown);
  - column poisoning: a failed tool:: hash, or a protocol error, makes
    every cell unknown;
  - staleness: the position join holds only while the tree still is the
    tree that was measured (measured_files digests), and a stale PASS
    must not read as proved;
  - checklist rows come from the blessed Spec conjuncts; witnesses are
    matched on statement text only (an `unfold <prop>` in a proof body
    must not create a witness); no witness is its own state.
"""

import base64
import json
from pathlib import Path

from pybb.attestation.appraisal import ComponentResult, digest_file
from pybb.attestation.knowledge_sources import Verdict
from pybb.attestation.proof_status import (
    FAILING,
    NO_WITNESS,
    PROVED,
    UNKNOWN,
    decl_status,
    goal_checklist,
    parse_diagnostics,
    render_checklist,
    spec_conjuncts,
)

REPO = Path(__file__).parent.parent
PROPS = REPO / "targets" / "temp-control-goals" / "TempControl" / "Props.lean"

TARG = "proofs_targ"
BINDING = "binding_targ"


def _diag(file: Path, line: int, severity="error", kind="", data="boom"):
    return {"fileName": str(file), "pos": {"line": line, "column": 0},
            "severity": severity, "kind": kind, "data": data}


def _component(passed: bool, diags=None, targ=TARG, reason="", meta=""):
    measured = ""
    if diags is not None:
        measured = base64.b64encode(
            "\n".join(json.dumps(d) for d in diags).encode()).decode()
    return ComponentResult(
        appr_asp="run_command_lean_appr", target_asp="run_command_lean",
        targ_id=targ, passed=passed, reason=reason,
        args={"metadata": meta} if meta else {}, measured_b64=measured)


def _verdict(*components, error=""):
    return Verdict(protocol="stub", passed=all(c.passed for c in components),
                   components=list(components), error=error)


def test_parse_diagnostics_tolerates_pollution():
    raw = b"\n".join([
        b"Building TempControl.Impl ...",          # build chatter
        json.dumps(_diag(Path("f"), 1)).encode(),  # a diagnostic
        b'{"not": "a diagnostic"}',                # JSON, not a diagnostic
        b"{broken json",                           # not JSON at all
        json.dumps(_diag(Path("f"), 2, severity="warning",
                         kind="hasSorry")).encode(),
    ])
    diags = parse_diagnostics(raw)
    assert [d["pos"]["line"] for d in diags] == [1, 2]


def _write_lean(tmp_path: Path) -> Path:
    f = tmp_path / "Stub.lean"
    f.write_text("""theorem alpha : True := by
  trivial

theorem beta : True := by
  trivial

theorem gamma : True := by
  trivial
""")
    return f


def test_pass_is_the_asps_word(tmp_path):
    f = _write_lean(tmp_path)
    statuses = decl_status(_verdict(_component(True)), TARG, f)
    assert {s.state for s in statuses.values()} == {PROVED}


def test_fail_refined_by_mapped_diagnostics(tmp_path):
    f = _write_lean(tmp_path)
    # beta errors, gamma has a sorry; alpha undiagnosed -> proved (derived)
    v = _verdict(_component(False, [
        _diag(f, 4, data="unsolved goals\nfoo"),
        _diag(f, 7, severity="warning", kind="hasSorry", data=""),
    ]))
    statuses = decl_status(v, TARG, f)
    assert statuses["alpha"].state == PROVED
    assert statuses["beta"].state == FAILING
    assert statuses["beta"].detail == "unsolved goals"  # first line only
    assert statuses["gamma"].state == FAILING
    assert "sorry" in statuses["gamma"].detail


def test_unmappable_diagnostic_fails_closed(tmp_path):
    f = _write_lean(tmp_path)
    # one mapped refutation + one in a DIFFERENT file: the undiagnosed
    # declarations may be the unmapped one's victims -> unknown
    v = _verdict(_component(False, [
        _diag(f, 4),
        _diag(f.with_name("Other.lean"), 1),
    ]))
    statuses = decl_status(v, TARG, f)
    assert statuses["beta"].state == FAILING
    assert statuses["alpha"].state == UNKNOWN
    assert statuses["gamma"].state == UNKNOWN


def test_fail_without_diagnostics_is_all_unknown(tmp_path):
    f = _write_lean(tmp_path)
    statuses = decl_status(
        _verdict(_component(False, [], reason="exit status 1")), TARG, f)
    assert {s.state for s in statuses.values()} == {UNKNOWN}


def test_tool_poisoning_and_protocol_error(tmp_path):
    f = _write_lean(tmp_path)
    poisoned = _verdict(
        _component(True),
        ComponentResult(appr_asp="goldenbytes_appr", target_asp="hashfile",
                        targ_id="tool_lean_lean_targ", passed=False,
                        args={"metadata": "tool::lean"}))
    assert {s.state for s in decl_status(poisoned, TARG, f).values()} \
        == {UNKNOWN}
    errored = Verdict(protocol="stub", passed=False, error="cvm died")
    assert {s.state for s in decl_status(errored, TARG, f).values()} \
        == {UNKNOWN}


def _stamped(comp, *files):
    """The component as `_attest` would leave it: input digests taken at
    the run."""
    comp.measured_files = {str(Path(f).resolve()): digest_file(Path(f))
                           for f in files}
    return comp


def test_stale_tree_fails_closed(tmp_path):
    """The staleness guard: a verdict outlives the tree it measured, and
    the position join is only meaningful while it hasn't. Reproduces the
    synthesis case — the run measured a fully-stubbed file, a proof was
    accepted afterwards, and the old diagnostics' lines now point at the
    wrong declarations."""
    f = _write_lean(tmp_path)
    v = _verdict(_stamped(_component(False, [_diag(f, 4)]), f))
    assert decl_status(v, TARG, f)["beta"].state == FAILING  # fresh: refined

    f.write_text("-- a line the run never saw\n" + f.read_text())
    statuses = decl_status(v, TARG, f)
    assert {s.state for s in statuses.values()} == {UNKNOWN}
    assert "changed since the run" in statuses["beta"].detail


def test_stale_pass_is_not_read_as_proved(tmp_path):
    """The dangerous direction: a PASS component marks every declaration
    proved. Against a tree the run never saw that is an upgrade off
    stale evidence, so staleness is checked before the pass/fail split."""
    f = _write_lean(tmp_path)
    v = _verdict(_stamped(_component(True), f))
    assert {s.state for s in decl_status(v, TARG, f).values()} == {PROVED}

    f.write_text(f.read_text() + "\ntheorem delta : True := by sorry\n")
    assert {s.state for s in decl_status(v, TARG, f).values()} == {UNKNOWN}


def test_unstamped_verdict_reads_as_before(tmp_path):
    """No digests is not evidence of staleness — an unstamped verdict
    keeps its pre-existing reading rather than poisoning every cell."""
    f = _write_lean(tmp_path)
    v = _verdict(_component(False, [_diag(f, 4)]))
    f.write_text(f.read_text() + "\ntheorem delta : True := by trivial\n")
    assert decl_status(v, TARG, f)["beta"].state == FAILING


def test_stale_binding_row_is_unknown(tmp_path):
    """The acceptance row is stamped on its own file, so it goes unknown
    when THAT file moves — independently of the witness file."""
    witness = tmp_path / "W.lean"
    witness.write_text(WITNESS_FILE)
    acceptance = tmp_path / "Acceptance.lean"
    acceptance.write_text("theorem spec_holds : Spec step := by trivial\n")
    binding = _stamped(_component(True, targ=BINDING), acceptance)
    v = _verdict(_component(True), binding)

    rows = {r.label: r.status
            for r in goal_checklist(BLESSED, v, TARG, BINDING, witness).rows}
    assert rows["Spec bound (acceptance)"].state == PROVED

    acceptance.write_text("theorem spec_holds : Spec step := by sorry\n")
    rows = {r.label: r.status
            for r in goal_checklist(BLESSED, v, TARG, BINDING, witness).rows}
    assert rows["Spec bound (acceptance)"].state == UNKNOWN


def test_spec_conjuncts_from_the_committed_blessing():
    assert spec_conjuncts(PROPS.read_text()) == [
        "fanOn_when_hot_prop", "fanOff_when_cold_prop",
        "fanHold_in_band_prop", "fanOn_only_if_hot_or_held_prop"]


WITNESS_FILE = """theorem hot_ok : hot_prop step := by
  unfold hot_prop
  trivial

theorem cold_helper : True := by
  -- mentions cold_prop only in its proof body:
  unfold cold_prop
  trivial

theorem spec_holds : Spec step := by
  trivial
"""

BLESSED = """def hot_prop (f : Nat) : Prop := True
def cold_prop (f : Nat) : Prop := True
def Spec (f : Nat) : Prop :=
  hot_prop f ∧ cold_prop f
"""


def test_checklist_join_witness_matching_and_no_witness(tmp_path):
    f = tmp_path / "Proofs.lean"
    f.write_text(WITNESS_FILE)
    v = _verdict(_component(True), _component(True, targ=BINDING))
    checklist = goal_checklist(BLESSED, v, TARG, BINDING, f)
    by_label = {r.label: r for r in checklist.rows}
    assert by_label["hot_prop"].status.state == PROVED
    assert by_label["hot_prop"].witnesses == ["hot_ok"]
    # cold_prop appears ONLY inside a proof body -> not a witness
    assert by_label["cold_prop"].status.state == NO_WITNESS
    assert by_label["Spec bound (acceptance)"].status.state == PROVED
    rendered = render_checklist(checklist)
    assert "witness: hot_ok" in rendered and "quick" in rendered


def test_checklist_binding_failure_and_poison(tmp_path):
    f = tmp_path / "Proofs.lean"
    f.write_text(WITNESS_FILE)
    v = _verdict(_component(True),
                 _component(False, targ=BINDING,
                            reason="Type mismatch\n  spec_holds"))
    checklist = goal_checklist(BLESSED, v, TARG, BINDING, f)
    binding = checklist.rows[-1].status
    assert binding.state == FAILING and binding.detail == "Type mismatch"
    poisoned = checklist.poison("readiness failed: stale blessing")
    assert {r.status.state for r in poisoned.rows} == {UNKNOWN}
    assert "BASELINES NOT TRUSTED" in render_checklist(poisoned)
