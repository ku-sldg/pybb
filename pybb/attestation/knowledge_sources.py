"""
Attestation on the routed blackboard.

The predicate IS the attestation: an entry's measurement is a request
descriptor

    {"protocol": <protocol_id>, "nonce": <int>}

and the registered predicate (built by `make_attestation_predicate`) runs
that protocol via the client, appraises the response, and returns a
`Verdict` — truthy iff every appraised component passed — which the
controller stores as the entry's result / good_standing. Protocols measure
the live target tree they were provisioned against; the clean copy for
repair / re-runs is a `TargetSnapshot`, outside the measurement path.

Knowledge sources are tier rungs: a `TierKS` responds to the entry by
re-pointing its measurement at this rung's protocol, so the controller's
next evaluation attests at the new tier. The decision tree is encoded in
the route's outcome chains:

    route("gumbo",
          on_pass=[TierKS(protocol_id="gumbo_validation")],
          on_fail=[TierKS(protocol_id="gumbo_l2")])

reads: a passing l1 verdict is provisional until semantic validation
confirms it; a failing l1 verdict is attributed per-contract at l2. Either
chosen tier's pass ends the episode in good standing; its failure exhausts
the chain and the controller moves the entry to the escalate segment
carrying that tier's failing Verdict as the report.

The controller re-evaluates every entry each cycle, so the predicate
memoizes on the measurement: unchanged request descriptors reuse the last
Verdict instead of re-running the (possibly minutes-long) protocol. A
future repair KS forces fresh attestation by bumping the nonce.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List

from pydantic import BaseModel

from ..blackboard import Blackboard
from ..knowledge_source import KnowledgeSource
from .appraisal import ComponentResult, overall_verdict, parse_appraisal


def attestation_request(protocol_id: str, nonce: int = 0) -> dict:
    """Measurement descriptor for an attestation entry."""
    return {"protocol": protocol_id, "nonce": nonce}


class Verdict(BaseModel):
    """
    Appraised outcome of one protocol run; an attestation entry's result.

    Truthiness is the overall verdict, so the controller's
    `good_standing = bool(result)` needs no special casing, while the
    per-component results remain available for attribution.
    """

    protocol: str
    passed: bool
    components: List[ComponentResult] = []
    error: str = ""

    def __bool__(self) -> bool:
        return self.passed

    def failing(self) -> List[ComponentResult]:
        return [c for c in self.components if not c.passed]


def make_attestation_predicate(
    client: Any, protocols: Dict[str, Any]
) -> Callable[[dict], Verdict]:
    """
    Predicate over attestation-request measurements: run the named protocol
    (ProtocolDir | RodeoProtocol) via the client and appraise the response.
    Memoized on the measurement so per-cycle re-evaluation of unchanged
    entries does not re-run protocols.
    """
    cache: Dict[str, Verdict] = {}

    def predicate(measurement: dict) -> Verdict:
        key = json.dumps(measurement, sort_keys=True)
        if key not in cache:
            cache[key] = _attest(client, protocols, measurement)
        return cache[key]

    return predicate


def _attest(client: Any, protocols: Dict[str, Any], measurement: dict) -> Verdict:
    protocol_id = measurement.get("protocol", "")
    protocol = protocols.get(protocol_id)
    if protocol is None:
        return Verdict(protocol=protocol_id, passed=False,
                       error=f"unknown protocol '{protocol_id}'")
    try:
        response = client.run_protocol(protocol)
    except Exception as e:
        return Verdict(protocol=protocol_id, passed=False, error=str(e))
    components = parse_appraisal(response, protocol.target_records())
    return Verdict(
        protocol=protocol_id,
        passed=overall_verdict(components),
        components=components,
    )


class StartAttestationKS(KnowledgeSource):
    """
    Links a readiness entry to its attestation episode: on the readiness
    entry's on_pass chain, writes the attestation entry seeded at the
    starting tier. Idempotent — an existing entry under `key` is never
    clobbered. Writes nothing back to the readiness entry; its memoized
    check re-passes on the next evaluation and standing recovers by itself.
    """

    name: str = ""
    partition: List[str] = []
    max_attempts: int = 1
    key: str
    start: str  # starting tier's protocol id
    predicate_name: str = "attestation"
    nonce: int = 0

    def model_post_init(self, __context) -> None:
        if not self.name:
            self.name = f"start:{self.key}@{self.start}"

    def execute(self, blackboard: Blackboard, keys: List[str]) -> None:
        if blackboard.get_entry(self.key) is not None:
            return  # live episode; never clobber
        blackboard.write_entry(
            key=self.key,
            predicate=self.predicate_name,
            measurement=attestation_request(self.start, nonce=self.nonce),
        )


class TierKS(KnowledgeSource):
    """
    One tier rung: re-point the entry's measurement at this rung's protocol
    so the next evaluation attests there.
    """

    name: str = ""
    partition: List[str] = []
    max_attempts: int = 1
    protocol_id: str

    def model_post_init(self, __context) -> None:
        if not self.name:
            self.name = f"tier:{self.protocol_id}"

    def execute(self, blackboard: Blackboard, keys: List[str]) -> None:
        for key in keys:
            entry = blackboard.get_entry(key)
            measurement = attestation_request(
                self.protocol_id,
                nonce=entry.measurement.get("nonce", 0),
            )
            blackboard.write_entry(
                key=key,
                predicate=entry.predicate,
                measurement=measurement,
                result=None,  # controller re-evaluates (attests) next cycle
            )
