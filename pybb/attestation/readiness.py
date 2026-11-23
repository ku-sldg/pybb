"""
Protocol readiness: the first verdict of an attestation episode.

A readiness entry asks "do these protocols exist and can they run?" before
any attestation happens. Its measurement names every protocol the episode
might touch:

    {"protocols": [<protocol_id>, ...]}

and the registered predicate (built by `make_readiness_predicate`) checks
each one: the id resolves, the protocol config is complete, goldenbytes
targets are provisioned, and the CVM binary plus every manifest-listed ASP
executable is present. The checks are deliberately shallow — "exists and
can run", not "is semantically valid"; deeper checks (e.g. a CVM dry-run
or term typecheck) are the documented extension point.

The payoff is where failures land: a bad protocol id or missing binary
escalates as a CONFIGURATION failure, with its ReadinessReport as the
report, before any attestation runs — instead of surfacing mid-episode
disguised as an integrity failure. Wiring (each entry spends its one
dispatch on its own branch point):

    controller.route("temp_control_aadl_slang:files", on_pass=[...], on_fail=[...])      # pre-registered
    controller.route("temp_control_aadl_slang:contracts", on_fail=[...])
    controller.route("temp_control_aadl_slang:ready",
        on_pass=[StartAttestationKS(episodes={"temp_control_aadl_slang:files": "temp_control_aadl_slang_l1a",
                                              "temp_control_aadl_slang:contracts": "temp_control_aadl_slang_l1b"})],
        on_fail=[])                                           # config failure -> escalate
    blackboard.write_entry(key="temp_control_aadl_slang:ready", predicate="protocol_check",
        measurement=readiness_request(["temp_control_aadl_slang_l1a", "temp_control_aadl_slang_l1b", "temp_control_aadl_slang_l2"]))
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel

from .client import CvmConfig
from .provision import GOLDEN_COMPANIONS


def readiness_request(protocol_ids: List[str]) -> dict:
    """Measurement descriptor for a protocol-readiness entry."""
    return {"protocols": list(protocol_ids)}


class ReadinessReport(BaseModel):
    """
    Outcome of a readiness check; a readiness entry's result. Truthy iff
    every named protocol exists, can run, and — when baseline verification
    is enabled — every golden-bearing protocol's signed provision bundle
    verifies and anchors its installed goldens.

    baseline_problems is a DISTINCT failure category from problems:
    problems are configuration failures (missing binary, unprovisioned
    target); baseline_problems are integrity failures of the golden
    baseline itself (bad signature, goldens not matching signed evidence,
    bundle not covering the current target map).
    """

    checked: List[str] = []
    problems: List[str] = []
    baseline_verified: List[str] = []  # protocols with a verified signed baseline
    baseline_problems: List[str] = []
    # ledger runs (docs/ledger_plan.md B.7 / O.10): the assurance level each
    # protocol's configuration can reach, and this writer's stack evidence
    assurance: Dict[str, str] = {}
    assurance_excepted: Dict[str, str] = {}  # protocol -> reason
    # with a ledger: stack_bid, blessing_key, latest_stack_blessed, stack_audit
    context: Dict[str, str] = {}

    def __bool__(self) -> bool:
        return (bool(self.checked) and not self.problems
                and not self.baseline_problems)


def make_readiness_predicate(
    protocols: Dict[str, Any], config: Optional[CvmConfig] = None, *,
    baseline_root: Optional[Any] = None, client: Optional[Any] = None,
    ledger_config: Optional[Any] = None, ledger: Optional[Any] = None,
) -> Callable[[dict], ReadinessReport]:
    """
    Predicate over readiness measurements: check every named protocol
    against the protocol map and the CVM environment. Memoized on the
    measurement (per predicate lifetime; a fresh run re-checks).

    With `baseline_root` set, readiness additionally verifies each
    golden-bearing protocol's SIGNED provision bundle via an appraisal-only
    CVM run (baseline.verify_bundle): bundle signature valid and every
    installed golden anchored to the signed evidence. Failures land in the
    distinct baseline_problems category, so a forged baseline escalates as
    a baseline-integrity failure before any attestation runs — never
    disguised as a config problem or an integrity violation of the live
    tree. `client` defaults to a CvmSubprocessClient on the same config.

    With `ledger_config` (a `ledger.LedgerConfig`), readiness also reports,
    as configuration failures before any attestation runs: the ledger ASPs
    missing from asp_bin; every protocol whose configuration cannot reach
    `min_assurance` and is not in `assurance_exceptions`. With `ledger` too,
    it reports as problems a writer with no `stack` bundle or no blessing in
    the ledger, and informationally (`report.context`) whether the latest
    stack bundle is blessed and how its last audit against the latest
    blessing went (docs/ledger_plan.md B.7 / O.10). pybb reads verdicts off
    the ledger; it computes none.
    """
    config = config or CvmConfig()
    cache: Dict[str, ReadinessReport] = {}

    def predicate(measurement: dict) -> ReadinessReport:
        key = json.dumps(measurement, sort_keys=True)
        if key not in cache:
            report = _check(protocols, config, measurement)
            if ledger_config is not None:
                _ledger_checks(protocols, config, ledger_config, measurement, report, ledger)
            if baseline_root is not None:
                _verify_baselines(protocols, config, client, baseline_root, report)
            cache[key] = report
        return cache[key]

    return predicate


def _verify_baselines(
    protocols: Dict[str, Any], config: CvmConfig, client: Optional[Any],
    baseline_root: Any, report: ReadinessReport,
) -> None:
    from .baseline import verify_bundle
    from .client import CvmSubprocessClient

    client = client or CvmSubprocessClient(config)
    for pid in report.checked:
        protocol = protocols.get(pid)
        if protocol is None:
            continue
        comps = protocol.session.get("Session_Context", {}).get("ASP_Comps", {})
        if not any(c in GOLDEN_COMPANIONS for c in comps.values()):
            continue  # no golden baseline to verify (e.g. semantic tiers)
        result = verify_bundle(client, protocol, baseline_root,
                               anchor_protocols=protocols)
        if result:
            report.baseline_verified.append(pid)
        else:
            report.baseline_problems.extend(f"{pid}: {p}" for p in result.problems)


def _check(
    protocols: Dict[str, Any], config: CvmConfig, measurement: dict
) -> ReadinessReport:
    ids = measurement.get("protocols", [])
    problems: List[str] = []

    if not os.path.isfile(config.cvm_binary):
        problems.append(f"CVM binary not found: {config.cvm_binary}")
    if not os.path.isdir(config.asp_bin):
        problems.append(f"ASP bin directory not found: {config.asp_bin}")

    for pid in ids:
        protocol = protocols.get(pid)
        if protocol is None:
            problems.append(f"{pid}: unknown protocol")
            continue
        for field in ("term", "session", "manifest"):
            if not getattr(protocol, field, None):
                problems.append(f"{pid}: protocol config missing {field}")
        comps = protocol.session.get("Session_Context", {}).get("ASP_Comps", {})
        golden_ids = {a for a, c in comps.items() if c in GOLDEN_COMPANIONS}
        for asp_id in golden_ids:
            for targ_id, args in protocol.asp_args.get(asp_id, {}).items():
                if not args.get("golden_b64"):
                    problems.append(f"{pid}: target {targ_id} has no provisioned golden")
        if os.path.isdir(config.asp_bin):
            for asp in protocol.manifest.get("ASPS", []):
                asp_path = os.path.join(config.asp_bin, asp)
                if not (os.path.isfile(asp_path) and os.access(asp_path, os.X_OK)):
                    problems.append(f"{pid}: ASP executable not found: {asp}")

    # NOTE: deliberately shallow. Deeper readiness (CVM dry-run of the
    # measurement-only term, term typechecking via cvm tools) slots in here.
    return ReadinessReport(checked=list(ids), problems=problems)


def reachable_assurance(protocol: Any) -> str:
    """The assurance level a protocol's configuration can reach under
    ledger runs: pybb always adds the nonce event, so it is `signed+nonce`
    with a `sig` step and companion, `nonce` without."""
    comps = protocol.session.get("Session_Context", {}).get("ASP_Comps", {})
    has_sig = "sig" in comps and "sig" in protocol.manifest.get("ASPS", []) \
        and _term_has_sig(protocol.term)
    return "signed+nonce" if has_sig else "nonce"


def _term_has_sig(term: Any) -> bool:
    if not isinstance(term, dict):
        return False
    body = term.get("TERM_BODY")
    if term.get("TERM_CONSTRUCTOR") == "asp":
        return isinstance(body, dict) and body.get("ASP_CONSTRUCTOR") == "SIG"
    if isinstance(body, list):
        return any(_term_has_sig(x) for x in body)
    if isinstance(body, dict):
        return _term_has_sig(body)
    return False


def _ledger_checks(protocols: Dict[str, Any], config: CvmConfig, ledger_config: Any,
                   measurement: dict, report: ReadinessReport, ledger: Optional[Any] = None) -> None:
    from .ledger import assurance_at_least
    from .ledger_runs import LEDGER_ASPS

    if os.path.isdir(config.asp_bin):
        for asp in LEDGER_ASPS:
            path = os.path.join(config.asp_bin, asp)
            if not (os.path.isfile(path) and os.access(path, os.X_OK)):
                report.problems.append(f"ledger ASP executable not found: {asp}")

    for pid in measurement.get("protocols", []):
        protocol = protocols.get(pid)
        if protocol is None:
            continue
        level = reachable_assurance(protocol)
        report.assurance[pid] = level
        if not assurance_at_least(level, ledger_config.min_assurance):
            reason = ledger_config.assurance_exceptions.get(pid)
            if reason is None:
                report.problems.append(
                    f"{pid}: configuration reaches assurance '{level}', below the ledger "
                    f"minimum '{ledger_config.min_assurance}' and not excepted")
            else:
                report.assurance_excepted[pid] = reason

    if ledger is not None:
        _context_checks(ledger, ledger_config, report)


def _context_checks(ledger: Any, ledger_config: Any, report: ReadinessReport) -> None:
    """Plan O.10: this writer's stack evidence. A missing stack bundle or
    blessing is a problem; the audit state of the latest stack bundle is
    reported, not judged."""
    from .ledger import load_appraiser_id

    writer = ledger_config.appraiser_id or load_appraiser_id(ledger_config.state_dir)
    stacks = [b for b in ledger.bundles(role="stack") if b.appraiser_id == writer]
    if not stacks:
        report.problems.append("no stack bundle for this writer in the ledger "
                               "(python examples/ledger_context.py measure stack --bless)")
        return
    latest = stacks[-1]
    report.context["stack_bid"] = latest.key_id
    blessed = [b for b in stacks if ledger.blessing_of(b.key_id) is not None]
    if not blessed:
        report.problems.append("no blessing for this writer's stack in the ledger "
                               f"(python examples/ledger_context.py bless {latest.key_id})")
        return
    report.context["blessing_key"] = f"blessing/{blessed[-1].key_id}"
    report.context["latest_stack_blessed"] = str(ledger.blessing_of(latest.key_id) is not None).lower()
    audits = [a for a in ledger.appraisals_of(latest.key_id) if a.verdict is not None
              and any(g.source == "blessing" and g.ref == report.context["blessing_key"]
                      for g in a.golden_provenance or [])]
    report.context["stack_audit"] = ("passed" if audits[-1].verdict.passed else "failed") if audits else "none"
