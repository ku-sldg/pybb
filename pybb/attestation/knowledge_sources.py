"""
Attestation on the routed blackboard.

The predicate IS the attestation: an entry's measurement is a request
descriptor

    {"protocol": <protocol_id>}

and the registered predicate (built by `make_attestation_predicate`) runs
that protocol via the client, appraises the response, and returns a
`Appraised` — truthy iff every appraised component passed — which the
controller stores as the entry's result / good_standing. Protocols measure
the live target tree they were provisioned against; the clean copy for
repair / re-runs is a `TargetSnapshot`, outside the measurement path.

Knowledge sources are tier rungs: a `TierKS` responds to the entry by
re-pointing its measurement at this rung's protocol, so the controller's
next evaluation attests at the new tier. The decision tree is encoded in
the route's outcome chains:

    route("temp_control_aadl_slang",
          on_pass=[TierKS(protocol_id="temp_control_aadl_slang_validation")],
          on_fail=[TierKS(protocol_id="temp_control_aadl_slang_l2")])

reads: a passing l1 verdict is provisional until semantic validation
confirms it; a failing l1 verdict is attributed per-contract at l2. Either
chosen tier's pass ends the episode in good standing; its failure exhausts
the chain and the controller moves the entry to the escalate segment
carrying that tier's failing Appraised as the report.

The controller re-evaluates every entry each cycle, so the predicate
memoizes on the measurement: each protocol attests at most once per
EPISODE, and a fresh workflow run (fresh predicates, fresh caches)
re-attests everything. In-session re-attestation is the RESTART-EPISODE
primitive (not a measurement field): a chain rung — RestartEpisodeKS
after repair, or any knowledge source via request_restart — asks the
controller for a fresh episode; the controller forgets the memoized
verdicts for that entry's episode measurements (the predicate's `forget`
hook), reseeds the entry, and the next evaluation is a genuinely fresh
CVM run. Restarts are pull-only and controller-capped: iterating on the
live tree with bare tools between restarts costs nothing, because
mutable-file writes change no measurement and nothing re-measures until
asked.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List

from pydantic import BaseModel

from ..blackboard import Blackboard
from ..knowledge_source import KnowledgeSource
from .appraisal import (
    ComponentResult,
    overall_verdict,
    parse_appraisal,
    stamp_measured_files,
)


def attestation_request(protocol_id: str) -> dict:
    """Measurement descriptor for an attestation entry."""
    return {"protocol": protocol_id}


def ledger_request(bid: str) -> dict:
    """Measurement descriptor for an audit entry: re-appraise the run the
    ledger holds under `bid` (docs/ledger_plan.md, B.5/E/K.4) instead of
    measuring the live tree. Needs a ledger on the predicate."""
    return {"ledger_bundle": bid}


class Appraised(BaseModel):
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
    # archived raw response (gzipped) this verdict was interpreted from —
    # the episode's durable evidence artifact, re-summarizable later
    evidence_ref: str = ""
    # ledger runs (docs/ledger_plan.md): the signed appraisal package and the
    # interpreted component list archived beside it, the run's nonce id, and
    # the ledger key of its evidence record ("" when no ledger is configured)
    appraisal_ref: str = ""
    components_ref: str = ""
    bid: str = ""  # the measurement bundle id (sha256 of its nonce)
    ledger_ref: str = ""  # `bundle/<appraisal bid>`: the appraisal bundle the verdict came from

    def __bool__(self) -> bool:
        return self.passed

    def failing(self) -> List[ComponentResult]:
        return [c for c in self.components if not c.passed]


Verdict = Appraised  # Phase 1 name, kept as an alias (plan N.2)


class Measured(BaseModel):
    """
    Outcome of a measurement-only run (plan N.2): the signed measurement
    bundle is in the ledger and nothing has judged it. Truthy iff recorded.
    It is deliberately not an `Appraised`: the trust-decision logic consumes
    judged outcomes only, and a later `ledger_request(bid)` turns this
    measurement into one when policy says so.
    """

    protocol: str
    bid: str = ""
    ledger_ref: str = ""  # `bundle/<bid>`
    evidence_ref: str = ""
    assurance: str = ""
    error: str = ""

    def __bool__(self) -> bool:
        return self.error == "" and self.bid != "" and self.ledger_ref != ""


def make_attestation_predicate(
    client: Any, protocols: Dict[str, Any], archive_dir: Any = None,
    ledger: Any = None, ledger_config: Any = None,
) -> Callable[[dict], Appraised]:
    """
    Predicate over attestation-request measurements: run the named protocol
    (ProtocolDir | RodeoProtocol) via the client and appraise the response.
    Memoized on the measurement so per-cycle re-evaluation of unchanged
    entries does not re-run protocols.

    With `archive_dir` set, every raw response is archived (gzipped —
    evidence-type trees are highly self-similar and compress ~50x) under
    one timestamped episode directory, BEFORE interpretation and
    regardless of verdict: failures especially deserve durable evidence.
    The verdict's evidence_ref names its artifact; a summary is always
    re-derivable from it via the verified summarizer.

    With `ledger` set (a `pybb.attestation.ledger.Ledger`), every protocol
    runs as the nonce'd two-run flow of `ledger_runs` — a measurement+SIG
    run whose raw signed package is the archived artifact, then a signed
    appraisal run — and the run's records are committed to the ledger in
    one batch. Without a ledger the single-run, in-run-APPR flow is
    unchanged.
    """
    from .ledger import LedgerConfig

    if ledger is not None and ledger_config is None:
        ledger_config = LedgerConfig()
    cache: Dict[str, Appraised] = {}
    if archive_dir is None:
        def _archive(response: Any, protocol_id: str, kind: str = "response") -> str:
            return ""
    else:
        from .ledger_runs import archiver

        _archive = archiver(archive_dir)  # one episode directory per predicate instance

    def predicate(measurement: dict) -> Appraised:
        key = json.dumps(measurement, sort_keys=True)
        if key not in cache:
            if measurement.get("ledger_bundle") or measurement.get("ledger_nonce"):
                cache[key] = _audit_ledger(client, protocols, measurement, _archive,
                                           ledger, ledger_config)
            elif ledger is not None:
                cache[key] = _attest_ledger(client, protocols, measurement, _archive,
                                            ledger, ledger_config)
            else:
                cache[key] = _attest(client, protocols, measurement, _archive)
        return cache[key]

    def forget(measurement: dict) -> None:
        """Restart-episode hook: drop the memoized verdict for one
        measurement so the next evaluation re-attests (a fresh CVM run).
        Called by the controller's _process_restarts."""
        cache.pop(json.dumps(measurement, sort_keys=True), None)

    predicate.forget = forget
    return predicate


def make_measurement_predicate(
    client: Any, protocols: Dict[str, Any], archive_dir: Any = None,
    ledger: Any = None, ledger_config: Any = None,
) -> Callable[[dict], Measured]:
    """
    Predicate over measurement requests `{"protocol": pid}`: run the named
    protocol's `measure` term, archive the package, and commit ONE
    measurement bundle to the ledger (plan N.1). Returns `Measured`, never a
    judged outcome; appraisal happens later through `ledger_request(bid)`
    on an attestation predicate. Memoized and restartable like
    `make_attestation_predicate`. A ledger is required: recording is the
    point.
    """
    from .ledger import LedgerConfig

    if ledger is not None and ledger_config is None:
        ledger_config = LedgerConfig()
    cache: Dict[str, Measured] = {}
    if archive_dir is None:
        def _archive(response: Any, protocol_id: str, kind: str = "response") -> str:
            return ""
    else:
        from .ledger_runs import archiver

        _archive = archiver(archive_dir)

    def predicate(measurement: dict) -> Measured:
        key = json.dumps(measurement, sort_keys=True)
        if key not in cache:
            cache[key] = _measure_ledger(client, protocols, measurement, _archive, ledger, ledger_config)
        return cache[key]

    def forget(measurement: dict) -> None:
        cache.pop(json.dumps(measurement, sort_keys=True), None)

    predicate.forget = forget
    return predicate


def _measure_ledger(client: Any, protocols: Dict[str, Any], measurement: dict, archive: Any,
                    ledger: Any, config: Any) -> Measured:
    from .ledger_runs import measure

    protocol_id = measurement.get("protocol", "")
    protocol = protocols.get(protocol_id)
    if protocol is None:
        return Measured(protocol=protocol_id, error=f"unknown protocol '{protocol_id}'")
    if ledger is None:
        return Measured(protocol=protocol_id, error="measurement-only recording needs a ledger")
    r = measure(client, protocol, ledger, config, archive=archive)
    return Measured(protocol=protocol_id, bid=r.bid, ledger_ref=r.ledger_ref, evidence_ref=r.evidence_ref,
                    assurance=r.assurance, error=r.error)


def _attest(client: Any, protocols: Dict[str, Any], measurement: dict,
            archive: Any = None) -> Appraised:
    protocol_id = measurement.get("protocol", "")
    protocol = protocols.get(protocol_id)
    if protocol is None:
        return Appraised(protocol=protocol_id, passed=False,
                       error=f"unknown protocol '{protocol_id}'")
    try:
        response = client.run_protocol(protocol)
    except Exception as e:
        return Appraised(protocol=protocol_id, passed=False, error=str(e))
    ref = archive(response, protocol_id) if archive else ""
    components = _interpret(response, protocol)
    if isinstance(components, str):  # summarizer refusal — fail closed
        return Appraised(protocol=protocol_id, passed=False, error=components,
                       evidence_ref=ref)
    stamp_measured_files(components)  # freshness key for derived views
    return Appraised(
        protocol=protocol_id,
        passed=overall_verdict(components),
        components=components,
        evidence_ref=ref,
    )


def _attest_ledger(client: Any, protocols: Dict[str, Any], measurement: dict,
                   archive: Any, ledger: Any, config: Any) -> Appraised:
    """The nonce'd two-run flow (ledger_runs.attest) as an Appraised. Runs
    carry no context pointer (plan O.7): the CVM runs in the state it is in
    and readers derive the stack and configuration in force."""
    from .ledger_runs import attest

    protocol_id = measurement.get("protocol", "")
    protocol = protocols.get(protocol_id)
    if protocol is None:
        return Appraised(protocol=protocol_id, passed=False,
                       error=f"unknown protocol '{protocol_id}'")
    r = attest(client, protocol, ledger, config, archive=archive)
    return Appraised(protocol=protocol_id, passed=r.passed, components=r.components,
                   error=r.error, evidence_ref=r.evidence_ref, appraisal_ref=r.appraisal_ref,
                   components_ref=r.components_ref, bid=r.bid, ledger_ref=r.ledger_ref)


def _audit_ledger(client: Any, protocols: Dict[str, Any], measurement: dict,
                  archive: Any, ledger: Any, config: Any) -> Appraised:
    """Appraise a ledger-held bundle again (ledger_runs.appraise_bundle) as a
    Appraised: truthy iff the ledger reads verified, the bytes and bundle id
    matched, and the fresh signed appraisal passed. A disagreement with the
    live appraisal is surfaced as the error, never re-decided."""
    from .ledger_runs import appraise_bundle, live_appraisal_of

    bid = measurement.get("ledger_bundle") or measurement.get("ledger_nonce", "")
    if ledger is None:
        return Appraised(protocol="", passed=False, bid=bid,
                       error="ledger audit requested but no ledger is configured")
    try:
        target = ledger.get(bid)
    except Exception as e:
        return Appraised(protocol="", passed=False, bid=bid, error=f"ledger bundle {bid}: {e}")
    protocol_id = target.protocol_id
    protocol = protocols.get(protocol_id)
    if protocol is None:
        return Appraised(protocol=protocol_id, passed=False, bid=bid,
                       error=f"unknown protocol '{protocol_id}' for ledger bundle {bid}")
    rep = appraise_bundle(client, protocol, ledger, config, bid, archive=archive,
                          appraisal_kind=measurement.get("appraisal_kind"))  # None: deferred/audit per plan N.3
    error = rep.error
    if not error and rep.agrees_with_live is False:
        live = live_appraisal_of(ledger, bid)
        recorded = live.verdict.passed if live is not None and live.verdict is not None else None
        error = (f"audit verdict ({'pass' if rep.passed else 'fail'}) disagrees with the "
                 f"live appraisal ({'pass' if recorded else 'fail'})")
    local = next((l.path for l in target.blob.locations if l.store == "local"), "")
    return Appraised(protocol=protocol_id, passed=bool(rep), components=rep.components, error=error,
                   evidence_ref=local, appraisal_ref=rep.appraisal_ref, bid=bid, ledger_ref=rep.ledger_ref)


def _interpret(response: dict, protocol: Any):
    """Interpret a protocol response: the VERIFIED appraisal summary
    (copland-evidence-tools) is primary for CVM evidence responses — its
    partitioning carries a correctness theorem, and attribution is an
    asp_targid field read. Rodeo APPSUMM responses keep their own path;
    the legacy Python walker remains only for hosts without the tool."""
    from . import summarizer

    if response.get("ACTION") == "APPSUMM":
        return parse_appraisal(response, protocol.target_records())
    if summarizer.available():
        try:
            return summarizer.summarize_response(response, protocol.session)
        except summarizer.SummaryError as e:
            return f"verified appraisal summary refused: {e}"
    return parse_appraisal(response, protocol.target_records())


class StartAttestationKS(KnowledgeSource):
    """
    Links a readiness entry to its attestation episodes: on the readiness
    entry's on_pass chain, writes each attestation entry seeded at its
    starting tier. A single rung starts every episode — chains are failure
    ladders, so two starter rungs in one chain would never both run.
    Idempotent — existing entries are never clobbered. Writes nothing back
    to the readiness entry; its memoized check re-passes on the next
    evaluation and standing recovers by itself.
    """

    name: str = ""
    partition: List[str] = []
    max_attempts: int = 1
    episodes: Dict[str, str]  # entry key -> starting tier's protocol id
    predicate_name: str = "attestation"

    def model_post_init(self, __context) -> None:
        if not self.name:
            self.name = "start:" + ",".join(self.episodes)

    def execute(self, blackboard: Blackboard, keys: List[str]) -> None:
        for key, start in self.episodes.items():
            if blackboard.get_entry(key) is not None:
                continue  # live episode; never clobber
            blackboard.write_entry(
                key=key,
                predicate=self.predicate_name,
                measurement=attestation_request(start),
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
            blackboard.write_entry(
                key=key,
                predicate=entry.predicate,
                measurement=attestation_request(self.protocol_id),
                result=None,  # controller re-evaluates (attests) next cycle
            )


class RestartEpisodeKS(KnowledgeSource):
    """
    The budgeted chain rung of the restart-episode primitive: placed after
    repair (or synthesis), it requests a fresh episode so the fix is judged
    by fresh measurement IN-SESSION — "verification pending next episode"
    becomes something the session does itself. Trust semantics unchanged:
    the repair's word is still worthless; only the fresh attestation that
    the restart triggers re-establishes standing.

    budget = restarts this rung may request per key (chain-level POLICY;
    the controller's max_restarts_per_key stays the halting LAW). When the
    budget is exhausted the rung does nothing, so the chain ends and normal
    end-of-route escalation reports the entry with its last failing
    verdict.

    `also` names sibling entries whose verdicts this chain's repair
    stales — the primitive supports any key, and a repair to one entry's
    subject (restoring a blessed file) invalidates every verdict
    measured over the pre-repair tree. Each sibling is restarted
    alongside, within the same budget; a sibling that already escalated
    on the stale tree is revived into the certify segment first, so the
    fresh episode re-judges it instead of leaving a dead verdict as the
    session's last word.
    """

    name: str = ""
    partition: List[str] = []
    max_attempts: int = 1
    budget: int = 1
    also: List[str] = []

    def model_post_init(self, __context) -> None:
        if not self.name:
            self.name = f"restart:budget{self.budget}"

    def execute(self, blackboard: Blackboard, keys: List[str]) -> None:
        for key in keys:
            if blackboard.restarts.get(key, 0) >= self.budget:
                continue
            blackboard.request_restart(key, "re-attest after repair")
            for extra in self.also:
                if extra == key or blackboard.restarts.get(extra, 0) >= self.budget:
                    continue
                if extra in blackboard.escalate and extra not in blackboard.entries:
                    # revive: the sibling escalated on the pre-repair tree
                    blackboard.entries[extra] = blackboard.escalate.pop(extra)
                blackboard.request_restart(
                    extra, "sibling repair staled this verdict")
