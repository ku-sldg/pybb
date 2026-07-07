"""
Attestation knowledge sources for the pybb blackboard.

Key conventions (the integration surface between KSs):

    attestation.request/<id>    {"protocol": <id>, "path_map": {...}?}
    attestation.evidence/<id>   {"protocol", "success", "response" | "error"}
    attestation.verdict/<id>    {"protocol", "passed", "components": {cid: bool}}
    attestation.component/<id>/<cid>   ComponentResult dump

All coordination state lives on the blackboard; the KSs themselves are
stateless. Guards compare timestamps (evidence newer than request, verdict
newer than evidence) rather than bare key existence so that re-posting a
request naturally re-runs the pipeline.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..blackboard import Blackboard
from ..knowledge_source import KnowledgeSource
from .appraisal import component_key_id, overall_verdict, parse_appraisal
from .client import AttestationClient
from .copland import rewrite_filepaths

REQUEST_PREFIX = "attestation.request/"
EVIDENCE_PREFIX = "attestation.evidence/"
VERDICT_PREFIX = "attestation.verdict/"
COMPONENT_PREFIX = "attestation.component/"
REPAIR_ATTEMPTS_PREFIX = "repair.attempts/"
REPAIR_ACTION_PREFIX = "repair.action/"


def request_key(rid: str) -> str:
    return REQUEST_PREFIX + rid


def evidence_key(rid: str) -> str:
    return EVIDENCE_PREFIX + rid


def verdict_key(rid: str) -> str:
    return VERDICT_PREFIX + rid


def component_key(rid: str, cid: str) -> str:
    return f"{COMPONENT_PREFIX}{rid}/{cid}"


def _ids_with_prefix(bb: Blackboard, prefix: str) -> List[str]:
    return [k[len(prefix):] for k in bb.entries if k.startswith(prefix)]


def _newer(bb: Blackboard, key_a: str, key_b: str) -> bool:
    """True if entry key_a exists and is at least as new as entry key_b."""
    a, b = bb.entries.get(key_a), bb.entries.get(key_b)
    return a is not None and (b is None or a.timestamp >= b.timestamp)


def pending_requests(bb: Blackboard) -> List[str]:
    """Request ids with no evidence at least as new as the request."""
    return [
        rid for rid in _ids_with_prefix(bb, REQUEST_PREFIX)
        if not _newer(bb, evidence_key(rid), request_key(rid))
    ]


def pending_evidence(bb: Blackboard) -> List[str]:
    """Evidence ids with no verdict at least as new as the evidence."""
    return [
        rid for rid in _ids_with_prefix(bb, EVIDENCE_PREFIX)
        if not _newer(bb, verdict_key(rid), evidence_key(rid))
    ]


class AttestationKS(KnowledgeSource):
    """Serves attestation requests by running the protocol via the client."""

    name: str = "AttestationKS"
    priority: int = 20
    client: Any  # AttestationClient
    protocols: Dict[str, Any]  # protocol_id -> ProtocolDir | RodeoProtocol

    def can_contribute(self, blackboard: Blackboard) -> bool:
        return any(
            (blackboard.read(request_key(rid)) or {}).get("protocol") in self.protocols
            for rid in pending_requests(blackboard)
        )

    def execute(self, blackboard: Blackboard) -> None:
        served = [
            rid for rid in pending_requests(blackboard)
            if (blackboard.read(request_key(rid)) or {}).get("protocol") in self.protocols
        ]
        rid = min(served, key=lambda r: blackboard.entries[request_key(r)].timestamp)
        req = blackboard.read(request_key(rid))
        protocol = self.protocols[req["protocol"]]
        try:
            response = self.client.run_protocol(protocol, path_map=req.get("path_map"))
            value = {
                "protocol": protocol.protocol_id,
                "success": bool(response.get("SUCCESS")),
                "response": response,
                "path_map": req.get("path_map"),
            }
            tags = ["attestation", "evidence"]
        except Exception as e:
            value = {"protocol": protocol.protocol_id, "success": False, "error": str(e)}
            tags = ["attestation", "evidence", "error"]
        blackboard.write(
            key=evidence_key(rid),
            value=value,
            source=self.name,
            confidence=1.0 if value["success"] else 0.0,
            tags=tags,
        )


class AppraisalKS(KnowledgeSource):
    """Turns raw CVM evidence into a verdict and per-component entries."""

    name: str = "AppraisalKS"
    priority: int = 30
    protocols: Dict[str, Any] = {}  # protocol_id -> ProtocolDir | RodeoProtocol

    def can_contribute(self, blackboard: Blackboard) -> bool:
        return bool(pending_evidence(blackboard))

    def execute(self, blackboard: Blackboard) -> None:
        pending = pending_evidence(blackboard)
        rid = min(pending, key=lambda r: blackboard.entries[evidence_key(r)].timestamp)
        ev = blackboard.read(evidence_key(rid)) or {}
        protocol = self.protocols.get(ev.get("protocol"))
        records = protocol.target_records() if protocol else []
        if ev.get("path_map"):
            # evidence args carry re-rooted filepaths; align records to match
            records = rewrite_filepaths(records, ev["path_map"])

        components = []
        if ev.get("success") and "response" in ev:
            components = parse_appraisal(ev["response"], records)
        passed = overall_verdict(components)

        seen: Dict[str, int] = {}
        summary: Dict[str, bool] = {}
        for c in components:
            cid = component_key_id(c, seen)
            summary[cid] = c.passed
            blackboard.write(
                key=component_key(rid, cid),
                value=c.model_dump(),
                source=self.name,
                confidence=1.0 if c.passed else 0.0,
                tags=["attestation", "component", ev.get("protocol", "")],
            )
        blackboard.write(
            key=verdict_key(rid),
            value={
                "protocol": ev.get("protocol"),
                "passed": passed,
                "components": summary,
                "error": ev.get("error"),
            },
            source=self.name,
            confidence=1.0 if passed else 0.0,
            tags=["attestation", "verdict"],
        )


class EscalationKS(KnowledgeSource):
    """On a failed verdict, posts a follow-up attestation request."""

    name: str = "EscalationKS"
    priority: int = 10
    on_fail: str
    escalate_to: str
    path_map: Optional[Dict[str, str]] = None

    def can_contribute(self, blackboard: Blackboard) -> bool:
        verdict = blackboard.read(verdict_key(self.on_fail))
        if verdict is None or verdict.get("passed"):
            return False
        return not _newer(blackboard, request_key(self.escalate_to), verdict_key(self.on_fail))

    def execute(self, blackboard: Blackboard) -> None:
        value: Dict[str, Any] = {
            "protocol": self.escalate_to,
            "triggered_by": self.on_fail,
        }
        if self.path_map:
            value["path_map"] = self.path_map
        blackboard.write(
            key=request_key(self.escalate_to),
            value=value,
            source=self.name,
            tags=["attestation", "request", "escalation"],
        )


class TrustDecisionKS(KnowledgeSource):
    """
    Summarizes all verdicts into the blackboard hypothesis once idle.

    Verdict ids listed in `semantic` denote semantic-verification protocols
    (e.g. Sireum tipe/logika/test runs): their passing means "the system
    still verifies", which is weighed against integrity failures rather
    than lumped in with them. This KS is deliberately the only place where
    tier semantics exist in code.
    """

    name: str = "TrustDecisionKS"
    priority: int = 5
    semantic: List[str] = []

    def can_contribute(self, blackboard: Blackboard) -> bool:
        if blackboard.hypothesis is not None:
            return False
        if pending_requests(blackboard) or pending_evidence(blackboard):
            return False
        return bool(_ids_with_prefix(blackboard, VERDICT_PREFIX))

    @staticmethod
    def _failing(blackboard: Blackboard, rid: str) -> List[str]:
        verdict = blackboard.read(verdict_key(rid)) or {}
        failing = [
            f"{rid}/{cid}"
            for cid, ok in verdict.get("components", {}).items()
            if not ok
        ]
        if not verdict.get("passed") and not verdict.get("components"):
            failing.append(f"{rid} (no appraisal evidence)")
        return failing

    def execute(self, blackboard: Blackboard) -> None:
        verdict_ids = _ids_with_prefix(blackboard, VERDICT_PREFIX)
        semantic_ids = sorted(r for r in verdict_ids if r in self.semantic)
        integrity_ids = sorted(r for r in verdict_ids if r not in self.semantic)

        integrity_fail: List[str] = []
        for rid in integrity_ids:
            integrity_fail.extend(self._failing(blackboard, rid))
        semantic_fail: List[str] = []
        for rid in semantic_ids:
            semantic_fail.extend(self._failing(blackboard, rid))

        repair_attempts = sum(
            blackboard.read(k) or 0
            for k in blackboard.entries
            if k.startswith(REPAIR_ATTEMPTS_PREFIX)
        )
        if not integrity_fail and not semantic_fail:
            if repair_attempts:
                plural = "attempt" if repair_attempts == 1 else "attempts"
                hypothesis = (
                    "Integrity violation detected and repaired "
                    f"({repair_attempts} {plural}); system re-attested clean ("
                    + ", ".join(sorted(verdict_ids)) + " passed)"
                )
            else:
                hypothesis = (
                    "All attested components intact ("
                    + ", ".join(sorted(verdict_ids)) + " passed)"
                )
        elif semantic_fail:
            parts = []
            if integrity_fail:
                parts.append(
                    "failing components: " + ", ".join(sorted(integrity_fail))
                )
            parts.append(
                "failing verification: " + ", ".join(sorted(semantic_fail))
            )
            hypothesis = (
                "Attestation integrity violation with failed semantic "
                "verification; " + "; ".join(parts)
                if integrity_fail
                else "Semantic verification failed; " + "; ".join(parts)
            )
        elif integrity_fail and semantic_ids:
            hypothesis = (
                "Attestation integrity violation; failing components: "
                + ", ".join(sorted(integrity_fail))
                + "; however semantic verification passed ("
                + ", ".join(semantic_ids)
                + ") — artifacts modified yet system still verifies"
            )
        else:
            hypothesis = (
                "Attestation integrity violation; failing components: "
                + ", ".join(sorted(integrity_fail))
            )
        failing_any = bool(integrity_fail or semantic_fail)
        if failing_any and repair_attempts:
            plural = "attempt" if repair_attempts == 1 else "attempts"
            hypothesis += f" — repair attempted ({repair_attempts} {plural}) without success"
        blackboard.hypothesis = hypothesis
        blackboard.write(
            key="attestation.hypothesis",
            value=hypothesis,
            source=self.name,
            confidence=0.0 if failing_any else 1.0,
            tags=["attestation", "hypothesis"],
        )
