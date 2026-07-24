"""
Promotion on the blackboard: a sanctioned model change becomes the new
baseline.

A promotion request lives in the provision partition (written by the
out-of-band attestation manager after it detects that contracts changed —
see examples/attestation_manager.py) and names the model:

    {"model": <model_id>}

The registered predicate (built by `make_promotion_predicate`) IS the
promotion pipeline:

  1. codegen_fn() — re-run HAMR codegen on the sanctioned model (pluggable:
     real deployments configure `sireum hamr phantom` + `sireum hamr
     codegen`; the demo injects a simulation)
  2. optional validation gate (opt-in): the semantic protocol must pass on
     the regenerated project before gold may move
  3. derive fresh target maps from the new content (targetmap syntax scan)
     and install them into the shared ProtocolDirs — terms and asp_args
     regenerated, golden values cleared, stale prebuilts dropped
  4. capture the watched files into the golden directory: gold moves

The per-protocol provision requests written AFTER the promote request
(the provision partition evaluates in write order — `request_promotion`
writes them in pipeline order) then extract fresh golden values against
the new targets, and any attestation episode that follows measures the
live tree against the new baseline.

Trust note: promotion runs only on SANCTIONED model changes — the
attestation manager (or its administrator) is the authorization point;
malicious edits are assumed impossible at that level. The blackboard's
own failure handling still cannot reach this path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel

from ..blackboard import Blackboard, BlackboardEntry
from .appraisal import overall_verdict, parse_appraisal
from .provision import request_provision
from .snapshot import TargetSnapshot
from .targetmap import derive_targets, install_targets


def promotion_request(model: str) -> dict:
    """Measurement descriptor for a promotion request."""
    return {"model": model}


def request_promotion(
    blackboard: Blackboard, model: str, protocol_ids: List[str],
    predicate: str = "promotion",
) -> BlackboardEntry:
    """
    Attestation-manager API: write the promote request and the per-protocol
    provision requests, in pipeline order (the provision partition
    evaluates in write order, so promotion runs before provisioning).
    """
    entry = blackboard.write_entry(
        key=f"promote:{model}",
        predicate=predicate,
        measurement=promotion_request(model),
        partition="provision",
    )
    for pid in protocol_ids:
        request_provision(blackboard, pid)
    return entry


class PromotionOutcome(BaseModel):
    """Result of one promotion request; truthy iff gold moved."""

    model: str
    codegen: str = ""              # description of the codegen run
    validated: Optional[bool] = None  # None = gate not requested
    captured: int = 0              # watched files synced into golden/
    targets: Dict[str, int] = {}   # protocol id -> regenerated target count
    error: str = ""

    def __bool__(self) -> bool:
        return not self.error and self.captured > 0 and bool(self.targets)


def make_promotion_predicate(
    protocols: Dict[str, Any],
    golden_root: Path,
    spec: dict,
    codegen_fn: Callable[[], str],
    client: Any = None,
    validate_with: Optional[str] = None,
) -> Callable[[dict], PromotionOutcome]:
    """
    Predicate over promotion requests. `codegen_fn` re-runs HAMR on the
    sanctioned model and returns a description. `validate_with` (opt-in)
    names a semantic protocol that must pass, via `client`, before gold
    moves. Memoized on the measurement per predicate lifetime.
    """
    cache: Dict[str, PromotionOutcome] = {}

    def predicate(measurement: dict) -> PromotionOutcome:
        key = json.dumps(measurement, sort_keys=True)
        if key not in cache:
            cache[key] = _promote(
                protocols, golden_root, spec, codegen_fn, client,
                validate_with, measurement,
            )
        return cache[key]

    return predicate


def _promote(
    protocols: Dict[str, Any],
    golden_root: Path,
    spec: dict,
    codegen_fn: Callable[[], str],
    client: Any,
    validate_with: Optional[str],
    measurement: dict,
) -> PromotionOutcome:
    model = measurement.get("model", "")

    try:
        codegen = codegen_fn()
    except Exception as e:
        return PromotionOutcome(model=model, error=f"codegen failed: {e}")

    validated: Optional[bool] = None
    if validate_with is not None:
        protocol = protocols.get(validate_with)
        if protocol is None or client is None:
            return PromotionOutcome(
                model=model, codegen=codegen,
                error=f"validation gate needs client and protocol '{validate_with}'",
            )
        try:
            response = client.run_protocol(protocol)
        except Exception as e:
            return PromotionOutcome(model=model, codegen=codegen,
                                    error=f"validation gate failed: {e}")
        validated = overall_verdict(
            parse_appraisal(response, protocol.target_records())
        )
        if not validated:
            return PromotionOutcome(
                model=model, codegen=codegen, validated=False,
                error="validation gate failed: regenerated project does not verify",
            )

    # new target maps from the regenerated content, installed into the
    # shared ProtocolDirs (goldens cleared; provisioning refills them)
    try:
        derived = derive_targets(spec)
    except OSError as e:
        return PromotionOutcome(model=model, codegen=codegen,
                                validated=validated, error=f"target derivation failed: {e}")
    targets = {}
    for pid, asp_args in derived.items():
        if pid in protocols:
            targets[pid] = install_targets(protocols[pid], asp_args)

    # gold moves: capture the watched files (per the NEW maps) into golden/
    try:
        snapshot = TargetSnapshot.capture(protocols, dest=golden_root)
    except OSError as e:
        return PromotionOutcome(model=model, codegen=codegen,
                                validated=validated, targets=targets,
                                error=f"golden capture failed: {e}")

    return PromotionOutcome(
        model=model, codegen=codegen, validated=validated,
        captured=len(snapshot.files), targets=targets,
    )
