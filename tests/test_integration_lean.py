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
def test_proofs_and_behavior_tiers_clean():
    check = _tier_verdict("lean_check")
    assert check.passed, check
    assert {c.targ_id for c in check.components} == {"lean_spec_check_targ"}
    behavior = _tier_verdict("lean_exec")
    assert behavior.passed, behavior
    assert {c.targ_id for c in behavior.components} == \
        {"lean_exec_hot_targ", "lean_exec_cold_targ", "lean_exec_hold_targ"}


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
def test_laundered_behavior_change_refuted_by_proof_and_behavior():
    """The scenario only the semantic tiers catch: flip the hot branch of
    the implementation. Hash measurements would bless it after laundering
    (goldens are not consulted by the tier protocols at all); the theorems
    no longer prove AND the hot vector no longer matches."""
    orig = IMPL.read_text()
    broken = orig.replace("if temp > sp.high then .On",
                          "if temp > sp.high then .Off")
    assert broken != orig
    IMPL.write_text(broken)
    try:
        check = _tier_verdict("lean_check")
        assert not check.passed
        behavior = _tier_verdict("lean_exec")
        assert not behavior.passed
        failing = {c.targ_id for c in behavior.failing()}
        assert failing == {"lean_exec_hot_targ"}  # cold and hold still match
    finally:
        IMPL.write_text(orig)
