"""
Protocol readiness: the first verdict of an attestation episode.

A readiness entry asks "do these protocols exist and can they run?" before
any attestation happens. Its measurement names every protocol the episode
might touch:

    {"protocols": [<protocol_id>, ...], "nonce": <int>}

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

    controller.route("gumbo", on_pass=[...], on_fail=[...])   # pre-registered
    controller.route("gumbo:ready",
        on_pass=[StartAttestationKS(key="gumbo", start="gumbo_l1")],
        on_fail=[])                                           # config failure -> escalate
    blackboard.write_entry(key="gumbo:ready", predicate="protocol_check",
        measurement=readiness_request(["gumbo_l1", "gumbo_l2", "gumbo_validation"]))
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel

from .client import CvmConfig


def readiness_request(protocol_ids: List[str], nonce: int = 0) -> dict:
    """Measurement descriptor for a protocol-readiness entry."""
    return {"protocols": list(protocol_ids), "nonce": nonce}


class ReadinessReport(BaseModel):
    """
    Outcome of a readiness check; a readiness entry's result. Truthy iff
    every named protocol exists and can run.
    """

    checked: List[str] = []
    problems: List[str] = []

    def __bool__(self) -> bool:
        return bool(self.checked) and not self.problems


def make_readiness_predicate(
    protocols: Dict[str, Any], config: Optional[CvmConfig] = None
) -> Callable[[dict], ReadinessReport]:
    """
    Predicate over readiness measurements: check every named protocol
    against the protocol map and the CVM environment. Memoized on the
    measurement; re-check via a bumped nonce.
    """
    config = config or CvmConfig()
    cache: Dict[str, ReadinessReport] = {}

    def predicate(measurement: dict) -> ReadinessReport:
        key = json.dumps(measurement, sort_keys=True)
        if key not in cache:
            cache[key] = _check(protocols, config, measurement)
        return cache[key]

    return predicate


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
        golden_ids = {a for a, c in comps.items()
                      if c in ("goldenbytes_appr", "goldenevidence_appr")}
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
