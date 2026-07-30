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

    controller.route("gumbo:files", on_pass=[...], on_fail=[...])      # pre-registered
    controller.route("gumbo:contracts", on_fail=[...])
    controller.route("gumbo:ready",
        on_pass=[StartAttestationKS(episodes={"gumbo:files": "gumbo_l1a",
                                              "gumbo:contracts": "gumbo_l1b"})],
        on_fail=[])                                           # config failure -> escalate
    blackboard.write_entry(key="gumbo:ready", predicate="protocol_check",
        measurement=readiness_request(["gumbo_l1a", "gumbo_l1b", "gumbo_l2"]))
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

    def __bool__(self) -> bool:
        return (bool(self.checked) and not self.problems
                and not self.baseline_problems)


def make_readiness_predicate(
    protocols: Dict[str, Any], config: Optional[CvmConfig] = None, *,
    baseline_root: Optional[Any] = None, client: Optional[Any] = None,
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
    """
    config = config or CvmConfig()
    cache: Dict[str, ReadinessReport] = {}

    def predicate(measurement: dict) -> ReadinessReport:
        key = json.dumps(measurement, sort_keys=True)
        if key not in cache:
            report = _check(protocols, config, measurement)
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
