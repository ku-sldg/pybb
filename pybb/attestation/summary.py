"""
Post-run trust summary: the old TrustDecisionKS's hypothesis, recomputed
from the routed blackboard's final state.

The controller already encodes the decision structurally — good standing
means some tier passed, the escalate segment means every tier failed. This
helper reads entries, escalate, and history and renders that as prose,
including the one nuance that needs tier semantics: a `semantic` protocol
(e.g. Sireum tipe/logika/test) passing after integrity tiers failed means
"artifacts modified yet the system still verifies", not "intact".
"""

from __future__ import annotations

from typing import Iterable, List, Tuple

from ..blackboard import Blackboard
from .knowledge_sources import Verdict
from .readiness import ReadinessReport


def _tier_trail(blackboard: Blackboard, key: str) -> List[Verdict]:
    """Distinct (protocol, passed) verdicts for key, in evaluation order."""
    trail: List[Verdict] = []
    seen: set[Tuple[str, bool]] = set()
    for hist_key, entry in blackboard.get_history():
        if hist_key != key or not isinstance(entry.result, Verdict):
            continue
        sig = (entry.result.protocol, entry.result.passed)
        if sig not in seen:
            seen.add(sig)
            trail.append(entry.result)
    return trail


def _attribution(trail: List[Verdict]) -> str:
    """Failing components from the finest-grained failing verdict."""
    failing_verdicts = [v for v in trail if not v.passed and v.failing()]
    if not failing_verdicts:
        errors = [v.error for v in trail if v.error]
        return errors[-1] if errors else "no appraisal evidence"
    # ties go to the later (finer) tier
    finest = max(reversed(failing_verdicts), key=lambda v: len(v.components))
    # deduplicate: bseq(both_paths) replicates prior evidence into every
    # branch, so one violated event (e.g. a woven tool measurement) can be
    # witnessed once per branch — same violation, one name
    def label(c) -> str:
        name = c.targ_id or c.description or c.target_asp
        # batched appraisers (hashfile_many_appr) carry the per-item
        # attribution in the refusal reason — surface it with the name
        reason = " ".join((c.reason or "").split())
        return f"{name} [{reason[:160]}]" if reason else name

    names = sorted({label(c) for c in finest.failing()})
    return f"failing components ({finest.protocol}): " + ", ".join(names)


def _summarize_key(
    blackboard: Blackboard, key: str, escalated: bool, semantic: Iterable[str]
) -> str:
    trail = _tier_trail(blackboard, key)
    passed = [v.protocol for v in trail if v.passed]
    failed = [v.protocol for v in trail if not v.passed]
    if escalated:
        entry = blackboard.get_escalate().get(key)
        repaired = entry is not None and any(
            ks.startswith("repair:") for ks in entry.ks_history
        )
        # "repaired from golden" is the RESTORE rungs' claim; a claim-based
        # rung (out-of-band, black-box) in the history proves only that it
        # RAN — a declined operator gate repaired nothing
        golden_repaired = entry is not None and any(
            ks.startswith(("repair:whole-file", "repair:slice"))
            for ks in entry.ks_history
        )
        restarted = blackboard.restarts.get(key, 0)
        if repaired and restarted:
            terminal = (
                f"repaired but re-attestation failed after {restarted} "
                "in-session restart(s) — restart budget exhausted; "
                "user intervention required"
            )
        elif golden_repaired:
            terminal = (
                "repaired from golden — verification pending next episode "
                "(re-run the workflow)"
            )
        else:
            terminal = "user intervention required"
        if passed:
            return (
                f"{key}: {', '.join(passed)} passed but confirmation failed "
                f"({', '.join(failed)}); {_attribution(trail)}; {terminal}"
            )
        tiers = ", ".join(failed) or "no tier produced evidence"
        return (
            f"{key}: integrity violation — ladder exhausted ({tiers} failed); "
            f"{_attribution(trail)}; {terminal}"
        )
    final = trail[-1] if trail else None
    if final is None or not final.passed:
        return f"{key}: attestation failed ({_attribution(trail)})"
    restarted = blackboard.restarts.get(key, 0)
    if restarted:
        # earlier episodes' verdicts remain in the trail; the standing
        # comes from the FRESH episode's measurement
        return (
            f"{key}: all attested components intact ({final.protocol} "
            f"passed) — repaired and re-attested clean in-session "
            f"(episode {restarted + 1})"
        )
    if not failed:
        if len(passed) > 1:
            return (
                f"{key}: all attested components intact "
                f"({', '.join(passed[:-1])} passed; confirmed by {final.protocol})"
            )
        return f"{key}: all attested components intact ({final.protocol} passed)"
    if final.protocol in semantic:
        return (
            f"{key}: integrity violation ({', '.join(failed)} failed; "
            f"{_attribution(trail)}) but semantic verification passed "
            f"({final.protocol}) — artifacts modified yet system still verifies"
        )
    return (
        f"{key}: {final.protocol} passed after {', '.join(failed)} failed — "
        f"attested clean at finer granularity"
    )


def trust_summary(blackboard: Blackboard, semantic: Iterable[str] = ()) -> str:
    """One line per attestation entry, certify segment then escalate."""
    lines = [
        f"{key}: protocols validated ({', '.join(entry.result.checked)})"
        + (f"; signed baselines verified ({', '.join(entry.result.baseline_verified)})"
           if entry.result.baseline_verified else "")
        for key, entry in blackboard.get_all_entries().items()
        if isinstance(entry.result, ReadinessReport) and entry.good_standing
    ]
    lines += [
        _summarize_key(blackboard, key, escalated=False, semantic=semantic)
        for key, entry in blackboard.get_all_entries().items()
        if isinstance(entry.result, Verdict)
    ]
    lines += [
        _summarize_key(blackboard, key, escalated=True, semantic=semantic)
        for key, entry in blackboard.get_escalate().items()
        if isinstance(entry.result, Verdict)
    ]
    lines += [
        f"{key}: " + "; ".join(
            (["protocol readiness failed — " + "; ".join(entry.result.problems)]
             if entry.result.problems else [])
            + (["golden baseline integrity failed — "
                + "; ".join(entry.result.baseline_problems)]
               if entry.result.baseline_problems else [])
        ) + "; attestation never started; user intervention required"
        for key, entry in blackboard.get_escalate().items()
        if isinstance(entry.result, ReadinessReport)
    ]
    return "\n".join(lines) if lines else "no attestation entries on the blackboard"
