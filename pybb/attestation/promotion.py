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
from .provision import request_provision
from .snapshot import TargetSnapshot
from .targetmap import derive_targets, install_targets


def changed_contracts(l2_protocol: Any, model_suffix: str = ".aadl") -> List[str]:
    """
    Attestation-manager detection: contract slices from last provisioning
    whose golden content no longer appears in the current model files.
    Position-independent (a moved contract is not a changed one), and
    restricted to model files (`model_suffix`) — generated realizations
    are codegen OUTPUTS, not inputs to the codegen-needed decision.
    A changed result means HAMR codegen is needed: request_promotion.
    """
    import base64

    def norm(s: str) -> str:
        return "".join(s.split())

    texts: Dict[str, str] = {}
    changed: List[str] = []
    for targ, args in l2_protocol.asp_args.get("readfile_range", {}).items():
        fp, golden = args.get("filepath"), args.get("golden_b64")
        if not fp or not fp.endswith(model_suffix) or not golden:
            continue
        if fp not in texts:
            try:
                texts[fp] = norm(Path(fp).read_text())
            except OSError:
                texts[fp] = ""  # missing model file: every slice reads changed
        if norm(base64.b64decode(golden).decode()) not in texts[fp]:
            changed.append(targ)
    return changed


class DeclDiff(BaseModel):
    """changed_decls report; truthy iff promotion is needed. Entries are
    declaration metadata names (Module.Path::decl)."""

    added: List[str] = []      # live declarations with no provisioned slice
    removed: List[str] = []    # provisioned slices with no live declaration
    modified: List[str] = []   # same declaration, different content
    moved: List[str] = []      # same content, different position (re-baseline only)

    def __bool__(self) -> bool:
        return bool(self.added or self.removed or self.modified or self.moved)


def changed_decls(l2_protocol: Any, package_root: Path,
                  prefix: str = "lean",
                  props_protocol: Any = None,
                  files: Any = None) -> DeclDiff:
    """
    Attestation-manager detection for a Lean package: the declaration-level
    diff between the baseline and a fresh syntax scan of the live sources.
    Declarations are matched by NAME (metadata Module::decl), so a moved
    declaration is not a changed one; anonymous declarations
    (instance/example, metadata `Module::kind@line`) are matched by content
    instead. Comparison is whitespace-insensitive — byte-level drift within
    a declaration is the episode's job (l1a/l2); this answers the
    sanctioning question: WHICH declarations changed.

    The baseline side: for files the administrator blessed (props_protocol,
    whole-file signed content), declarations are scanned FROM THE BLESSED
    BYTES — the l2 goldens are launderable by re-provisioning, the
    blessing is not, so it is the authoritative sanctioning reference.
    Files outside the blessing fall back to their provisioned l2 slices
    (detection scope = last provisioning for those).

    A truthy result means the baseline no longer describes the live spec:
    a sanctioned change should be promoted (--promote), an unsanctioned
    one investigated.

    `files` (optional, absolute paths) restricts the live scan — the
    goal-directed scenarios diff the blessed files only, since their
    mutable files (proofs, implementation) change by design.
    """
    import base64

    from .targetmap import derive_targets_from_lean, lean_decl_spans

    def norm(s: str) -> str:
        return "".join(s.split())

    live = derive_targets_from_lean(
        Path(package_root), prefix=prefix,
        files=files)[f"{prefix}_contracts"]["readfile_range"]
    files: Dict[str, List[str]] = {}

    def segment(args: dict) -> str:
        fp = args["filepath"]
        if fp not in files:
            try:
                files[fp] = Path(fp).read_text().splitlines()
            except OSError:
                files[fp] = []
        return norm("".join(
            files[fp][args["start_index"] - 1:args["end_index"]]))

    def position(args: dict) -> tuple:
        return (args.get("filepath"), args.get("start_index"),
                args.get("end_index"))

    def named(meta: str) -> bool:
        return "@" not in meta

    # the baseline: blessed files scanned from signed bytes, the rest
    # from provisioned l2 slices — (meta, content, position) triples
    blessed_texts: Dict[str, str] = {}
    if props_protocol is not None:
        for args in props_protocol.asp_args.get("readfile", {}).values():
            if args.get("golden_b64"):
                blessed_texts[args["filepath"]] = base64.b64decode(
                    args["golden_b64"]).decode()
    baseline: List[tuple] = []
    for fp, text in blessed_texts.items():
        lines = text.splitlines()
        for kind, name, start, end in lean_decl_spans(text):
            content = norm("".join(lines[start - 1:end]))
            meta = name if name else f"{kind}@{start}"
            baseline.append((fp, meta, name is not None, content,
                             (fp, start, end)))
    for targ, args in l2_protocol.asp_args.get("readfile_range", {}).items():
        if not args.get("golden_b64") or args["filepath"] in blessed_texts:
            continue
        meta = args.get("metadata", targ)
        baseline.append((args["filepath"], meta, named(meta),
                         norm(base64.b64decode(args["golden_b64"]).decode()),
                         position(args)))

    # blessed-side metas carry only the decl name; l2 metas are
    # Module::name — normalize live metas to both forms via suffix match
    def meta_key(fp: str, meta: str) -> str:
        return meta.rsplit("::", 1)[-1] if fp in blessed_texts else meta

    live_named = {}
    live_anon = []
    for a in live.values():
        meta = a.get("metadata", "")
        if named(meta):
            live_named[(a["filepath"], meta_key(a["filepath"], meta))] = a
        else:
            live_anon.append(a)

    diff = DeclDiff()
    matched_anon: set = set()
    baseline_named_keys = set()

    def display(fp: str, meta: str) -> str:
        if "::" in meta:
            return meta
        module = ".".join(
            Path(fp).relative_to(package_root).with_suffix("").parts) \
            if str(fp).startswith(str(package_root)) else Path(fp).stem
        return f"{module}::{meta}"

    for fp, meta, is_named, content, pos in baseline:
        if is_named:
            key = (fp, meta_key(fp, meta))
            baseline_named_keys.add(key)
            hit = live_named.get(key)
            if hit is None:
                diff.removed.append(display(fp, meta))
            elif segment(hit) != content:
                diff.modified.append(display(fp, meta))
            elif position(hit) != pos:
                diff.moved.append(display(fp, meta))
        else:
            hit = next((i for i, a in enumerate(live_anon)
                        if i not in matched_anon and a["filepath"] == fp
                        and segment(a) == content), None)
            if hit is None:
                diff.modified.append(display(fp, meta))
            else:
                matched_anon.add(hit)
                if position(live_anon[hit]) != pos:
                    diff.moved.append(live_anon[hit]["metadata"])
    diff.added.extend(a["metadata"] for k, a in live_named.items()
                      if k not in baseline_named_keys)
    diff.added.extend(a["metadata"] for i, a in enumerate(live_anon)
                      if i not in matched_anon)
    for bucket in (diff.added, diff.removed, diff.modified, diff.moved):
        bucket.sort()
    return diff


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
    spec: Optional[dict] = None,
    codegen_fn: Callable[[], str] = lambda: "no codegen configured",
    client: Any = None,
    validate_with: Optional[str] = None,
    targets_fn: Optional[Callable[[], Dict[str, Dict[str, dict]]]] = None,
    tool_gate: Optional[Callable[[], Optional[str]]] = None,
) -> Callable[[dict], PromotionOutcome]:
    """
    Predicate over promotion requests. `codegen_fn` re-runs HAMR on the
    sanctioned model and returns a description. `tool_gate` (opt-in;
    see tools.make_tool_gate) measures the codegen toolchain IMMEDIATELY
    BEFORE codegen_fn runs and refuses promotion on drift from the
    blessed hashes — every report/codegen event is bound to a measured
    emitter. `validate_with` (opt-in)
    names a semantic protocol that must pass, via `client`, before gold
    moves. Target derivation backend: `targets_fn` (e.g. a
    derive_targets_from_report closure — the HAMR attestation report as
    the authoritative source of golden slices), else the syntax scan over
    `spec`. Memoized on the measurement per predicate lifetime.
    """
    if targets_fn is None:
        assert spec is not None, "need spec (syntax scan) or targets_fn (report)"
        targets_fn = lambda: derive_targets(spec)  # noqa: E731
    cache: Dict[str, PromotionOutcome] = {}

    def predicate(measurement: dict) -> PromotionOutcome:
        key = json.dumps(measurement, sort_keys=True)
        if key not in cache:
            cache[key] = _promote(
                protocols, golden_root, targets_fn, codegen_fn, client,
                validate_with, measurement, tool_gate,
            )
        return cache[key]

    return predicate


def _promote(
    protocols: Dict[str, Any],
    golden_root: Path,
    targets_fn: Callable[[], Dict[str, Dict[str, dict]]],
    codegen_fn: Callable[[], str],
    client: Any,
    validate_with: Optional[str],
    measurement: dict,
    tool_gate: Optional[Callable[[], Optional[str]]] = None,
) -> PromotionOutcome:
    model = measurement.get("model", "")

    if tool_gate is not None:
        gate_error = tool_gate()
        if gate_error:
            return PromotionOutcome(
                model=model,
                error=f"toolchain gate refused codegen: {gate_error}")

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
        # interpret exactly as an episode would (verified appraisal
        # summary primary) — the gate must not judge evidence more
        # leniently than attestation does
        from .knowledge_sources import (attestation_request,
                                        make_attestation_predicate)
        try:
            verdict = make_attestation_predicate(
                client, {validate_with: protocol}
            )(attestation_request(validate_with))
        except Exception as e:
            return PromotionOutcome(model=model, codegen=codegen,
                                    error=f"validation gate failed: {e}")
        validated = bool(verdict.passed)
        if not validated:
            failing = sorted({c.targ_id or c.description
                              for c in verdict.failing()})
            detail = ("; failing: " + ", ".join(failing) if failing
                      else f"; {verdict.error}" if verdict.error else "")
            return PromotionOutcome(
                model=model, codegen=codegen, validated=False,
                error="validation gate failed: regenerated project "
                      "does not verify" + detail,
            )

    # new target maps from the regenerated content, installed into the
    # shared ProtocolDirs (goldens cleared; provisioning refills them)
    try:
        derived = targets_fn()
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
