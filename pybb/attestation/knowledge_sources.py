"""
Attestation on the routed blackboard.

The predicate IS the attestation: an entry's measurement is a request
descriptor

    {"protocol": <protocol_id>}

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

    route("temp_control_aadl_slang",
          on_pass=[TierKS(protocol_id="temp_control_aadl_slang_validation")],
          on_fail=[TierKS(protocol_id="temp_control_aadl_slang_l2")])

reads: a passing l1 verdict is provisional until semantic validation
confirms it; a failing l1 verdict is attributed per-contract at l2. Either
chosen tier's pass ends the episode in good standing; its failure exhausts
the chain and the controller moves the entry to the escalate segment
carrying that tier's failing Verdict as the report.

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


def ledger_request(nid: str) -> dict:
    """Measurement descriptor for an audit entry: re-appraise the run the
    ledger holds under `nid` (docs/ledger_plan.md, B.5/E) instead of
    measuring the live tree. Needs a ledger on the predicate."""
    return {"ledger_nonce": nid}


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
    # archived raw response (gzipped) this verdict was interpreted from —
    # the episode's durable evidence artifact, re-summarizable later
    evidence_ref: str = ""
    # ledger runs (docs/ledger_plan.md): the signed appraisal package and the
    # interpreted component list archived beside it, the run's nonce id, and
    # the ledger key of its evidence record ("" when no ledger is configured)
    appraisal_ref: str = ""
    components_ref: str = ""
    nonce_id: str = ""
    ledger_ref: str = ""

    def __bool__(self) -> bool:
        return self.passed

    def failing(self) -> List[ComponentResult]:
        return [c for c in self.components if not c.passed]


def make_attestation_predicate(
    client: Any, protocols: Dict[str, Any], archive_dir: Any = None,
    ledger: Any = None, ledger_config: Any = None,
) -> Callable[[dict], Verdict]:
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
    tooling_resolver: List[Any] = [None]  # built lazily: needs _archive
    cache: Dict[str, Verdict] = {}
    episode_dir: List[Any] = [None]

    def _archive(response: Any, protocol_id: str, kind: str = "response") -> str:
        if archive_dir is None:
            return ""
        import gzip
        import secrets
        import time
        from pathlib import Path as _P

        if episode_dir[0] is None:
            # timestamp plus a random suffix: two predicates built in the
            # same second never share a directory (docs/ledger_plan.md,
            # schema point 5); the name is an archive detail, not a ledger field
            d = _P(archive_dir) / (time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2))
            d.mkdir(parents=True, exist_ok=True)
            episode_dir[0] = d
        path = episode_dir[0] / f"{protocol_id}.{kind}.json.gz"
        seq = 1
        while path.exists():  # restarted protocols archive alongside, never over
            seq += 1
            path = episode_dir[0] / f"{protocol_id}.{kind}.{seq}.json.gz"
        if isinstance(response, list):  # the components artifact: canonical bytes
            from .ledger import canonical_json

            with gzip.open(path, "wb") as f:
                f.write(canonical_json(response))
        else:
            with gzip.open(path, "wt") as f:
                json.dump(response, f)
        return str(path)

    def predicate(measurement: dict) -> Verdict:
        key = json.dumps(measurement, sort_keys=True)
        if key not in cache:
            if measurement.get("ledger_nonce"):
                cache[key] = _audit_ledger(client, protocols, measurement, _archive,
                                           ledger, ledger_config)
            elif ledger is not None:
                if tooling_resolver[0] is None:
                    from .ledger_tooling import ToolingResolver

                    tooling_resolver[0] = ToolingResolver(client, protocols, ledger,
                                                          ledger_config, archive=_archive)
                cache[key] = _attest_ledger(client, protocols, measurement, _archive,
                                            ledger, ledger_config, tooling_resolver[0])
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


def _attest(client: Any, protocols: Dict[str, Any], measurement: dict,
            archive: Any = None) -> Verdict:
    protocol_id = measurement.get("protocol", "")
    protocol = protocols.get(protocol_id)
    if protocol is None:
        return Verdict(protocol=protocol_id, passed=False,
                       error=f"unknown protocol '{protocol_id}'")
    try:
        response = client.run_protocol(protocol)
    except Exception as e:
        return Verdict(protocol=protocol_id, passed=False, error=str(e))
    ref = archive(response, protocol_id) if archive else ""
    components = _interpret(response, protocol)
    if isinstance(components, str):  # summarizer refusal — fail closed
        return Verdict(protocol=protocol_id, passed=False, error=components,
                       evidence_ref=ref)
    stamp_measured_files(components)  # freshness key for derived views
    return Verdict(
        protocol=protocol_id,
        passed=overall_verdict(components),
        components=components,
        evidence_ref=ref,
    )


def _attest_ledger(client: Any, protocols: Dict[str, Any], measurement: dict,
                   archive: Any, ledger: Any, config: Any, tooling_resolver: Any = None) -> Verdict:
    """The nonce'd two-run flow (ledger_runs.attest_with_ledger) as a Verdict,
    carrying the tooling reference the B.8 cadence prescribes."""
    from .ledger_runs import attest_with_ledger

    protocol_id = measurement.get("protocol", "")
    protocol = protocols.get(protocol_id)
    if protocol is None:
        return Verdict(protocol=protocol_id, passed=False,
                       error=f"unknown protocol '{protocol_id}'")
    tooling = tooling_resolver.ref(protocol_id) if tooling_resolver is not None else None
    r = attest_with_ledger(client, protocol, ledger, config, archive=archive, tooling=tooling)
    return Verdict(protocol=protocol_id, passed=r.passed, components=r.components,
                   error=r.error, evidence_ref=r.evidence_ref, appraisal_ref=r.appraisal_ref,
                   components_ref=r.components_ref, nonce_id=r.nonce_id, ledger_ref=r.ledger_ref)


def _audit_ledger(client: Any, protocols: Dict[str, Any], measurement: dict,
                  archive: Any, ledger: Any, config: Any) -> Verdict:
    """Re-appraise a ledger-held run (ledger_runs.appraise_record) as a Verdict:
    truthy iff the ledger reads verified, the bytes and nonce id matched,
    and the fresh signed appraisal passed."""
    from .ledger_runs import appraise_record

    nid = measurement.get("ledger_nonce", "")
    if ledger is None:
        return Verdict(protocol="", passed=False, nonce_id=nid,
                       error="ledger audit requested but no ledger is configured")
    try:
        records = ledger.get(nid)
    except Exception as e:
        return Verdict(protocol="", passed=False, nonce_id=nid, error=f"ledger run {nid}: {e}")
    protocol_id = records.evidence.protocol_id
    protocol = protocols.get(protocol_id)
    if protocol is None:
        return Verdict(protocol=protocol_id, passed=False, nonce_id=nid,
                       error=f"unknown protocol '{protocol_id}' for ledger run {nid}")
    rep = appraise_record(client, protocol, ledger, config, nid, archive=archive)
    error = rep.error
    if not error and rep.agrees_with_recorded_verdict is False:
        error = (f"audit verdict ({'pass' if rep.passed else 'fail'}) disagrees with the "
                 f"recorded verdict ({'pass' if records.verdict.passed else 'fail'})")
    return Verdict(protocol=protocol_id, passed=bool(rep), components=rep.components, error=error,
                   evidence_ref=records.evidence.locators[0].path if records.evidence.locators else "",
                   appraisal_ref=rep.appraisal_ref, nonce_id=nid, ledger_ref=rep.ledger_ref)


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
