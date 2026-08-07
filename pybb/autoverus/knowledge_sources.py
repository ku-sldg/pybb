"""
The proof predicate and the repair rung.

The trust question is "does this Rust file's Verus proof check?"; the
measurement is the file's identity plus the hash of its current contents

    {"file": <path>, "sha256": <hash>}

and the predicate built by `make_verus_predicate` runs Verus over that
file and returns a `VerusResult` — truthy iff Verus reports at least one
verified function and no errors — which the controller stores as the
entry's result / good_standing. `AutoVerusRepairKS` responds to a failing
entry by running AutoVerus in repair mode, writing the repaired source
back, and re-measuring the file.

Why the content hash is in the measurement: it makes each state the file
passed through visible in the entry's history, so the audit trail records
what was actually verified rather than just which path was.

The controller re-evaluates every entry each cycle, so the predicate
memoizes to avoid re-running Verus on unchanged code — but it keys on the
file's digest read at call time, not on the measurement. That distinction
matters as soon as an entry's route has more than one rung:
`controller._advance` restores the original measurement when a rung
exhausts and hands off, so a measurement-keyed memo would serve the next
rung a verdict for a file state its predecessor had already overwritten.
The predicate measures the artifact; the measurement describes it.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Callable, Optional, Tuple

from pydantic import BaseModel

from ..blackboard import Blackboard
from ..knowledge_source import KnowledgeSource
from .bridge import _run_autoverus, _run_verus
from .config import AutoVerusConfig
from .shell import ShellError

# Proof cheats: these make Verus pass vacuously, so a file containing one
# is never "verified" here no matter what Verus reports. AutoVerus applies
# the same rule when scoring its own benchmark output (its verify.py) --
# worth mirroring, since repair is exactly where a model is tempted to
# reach for them.
CHEATS = ("assume(", "admit()")

_VERUS_RESULTS_RE = re.compile(
    r"verification results::\s*(\d+)\s+verified,\s+(\d+)\s+error")


def file_digest(path) -> str:
    """sha256 of the file's bytes; "" when it cannot be read."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""  # unreadable: predicate reports it as a failing result


def source_measurement(path) -> dict:
    """
    Measurement descriptor for a Rust source file: which file, and the
    hash of what is in it right now. Repairing the file changes the
    measurement, so the entry's history records each state the file passed
    through.
    """
    p = Path(path)
    return {"file": str(p), "sha256": file_digest(p)}


class VerusResult(BaseModel):
    """
    Outcome of verifying one file; a proof entry's result.

    Truthiness is the verdict, so the controller's
    `good_standing = bool(result)` needs no special casing, while the
    counts and raw output remain available for the report.
    """

    file: str
    passed: bool
    verified: int = 0
    errors: int = 0
    output: str = ""
    error: str = ""

    def __bool__(self) -> bool:
        return self.passed

    def summary(self) -> str:
        if self.error:
            return self.error
        plural = "" if self.errors == 1 else "s"
        return f"{self.verified} verified, {self.errors} error{plural}"


def find_cheat(source: str) -> Optional[str]:
    """The first proof cheat in `source`, or None."""
    return next((c for c in CHEATS if c in source), None)


def parse_verus_output(output: str) -> Optional[Tuple[int, int]]:
    """(verified, errors) from a Verus run, or None if absent."""
    match = _VERUS_RESULTS_RE.search(output)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _verify(measurement: dict, verify_fn: Callable,
            allow_cheats: bool) -> VerusResult:
    path = (measurement or {}).get("file", "")
    try:
        source = Path(path).read_text()
    except OSError as e:
        return VerusResult(file=path, passed=False, error=f"unreadable: {e}")
    if not allow_cheats:
        # Checked before Verus runs: a cheated proof passes verification,
        # so trusting the verifier alone would call it repaired.
        cheat = find_cheat(source)
        if cheat:
            return VerusResult(file=path, passed=False,
                               error=f"vacuous proof: source contains {cheat!r}")
    try:
        output = verify_fn(path)
    except ShellError as e:
        return VerusResult(file=path, passed=False, error=str(e))
    counts = parse_verus_output(output)
    if counts is None:
        return VerusResult(file=path, passed=False, output=output,
                           error="verus reported no verification results")
    verified, errors = counts
    return VerusResult(file=path, passed=verified > 0 and errors == 0,
                       verified=verified, errors=errors, output=output)


def make_verus_predicate(verify_fn: Callable = None, *,
                         allow_cheats: bool = False,
                         config: AutoVerusConfig = None
                         ) -> Callable[[dict], VerusResult]:
    """
    Predicate over source measurements: verify the named file with Verus.
    Memoized so per-cycle re-evaluation of unchanged files does not re-run
    Verus, and a repaired file is re-verified rather than served stale.

    The memo keys on the file as it is *now*, not on the measurement that
    describes it. `controller._advance` restores an entry's original
    measurement when one rung exhausts and hands off, so a
    measurement-keyed memo would hand the next rung a verdict for a file
    state its predecessor has already overwritten. The measurement's
    sha256 remains the entry's provenance; the predicate measures the
    artifact.

    `verify_fn` defaults to the real Verus bridge. It is a seam for unit
    tests only; nothing ships a substitute.
    """
    verify_fn = verify_fn or (lambda path: _run_verus(path, config=config))
    cache: dict = {}

    def predicate(measurement: dict) -> VerusResult:
        path = (measurement or {}).get("file", "")
        key = (path, file_digest(path))
        if key not in cache:
            cache[key] = _verify(measurement, verify_fn, allow_cheats)
        return cache[key]

    return predicate


class AutoVerusRepairKS(KnowledgeSource):
    """
    Proof repair rung: hand the failing file to AutoVerus, write back the
    repaired source, and re-measure so the predicate verifies the result.

    One attempt, like the other repair rungs — AutoVerus does its own
    iterating internally (`repair_steps`), and a rung that could retry
    forever would obscure whether the repair actually converged. When the
    repair does not verify, the entry escalates carrying this KS in its
    history.

    `repair_fn` defaults to the real AutoVerus bridge and exists as a seam
    for unit tests only; nothing ships a substitute.
    """

    name: str = "repair:autoverus"
    partition: list[str] = []
    max_attempts: int = 1
    repair_steps: int = 5
    keep_intermediate: bool = False
    config: Optional[AutoVerusConfig] = None
    repair_fn: Optional[Callable] = None

    model_config = {"arbitrary_types_allowed": True}

    def execute(self, blackboard: Blackboard, keys: list[str]) -> None:
        for key in keys:
            entry = blackboard.get_entry(key)
            if entry is None or not isinstance(entry.measurement, dict):
                continue
            path = entry.measurement.get("file")
            if not path:
                continue
            try:
                if self.repair_fn is not None:
                    repaired = self.repair_fn(path, self.repair_steps)
                else:
                    repaired = _run_autoverus(
                        path, self.repair_steps, config=self.config,
                        keep_intermediate=self.keep_intermediate)
                # newline="" suppresses the \n -> \r\n translation Windows
                # would otherwise apply: the measurement hashes raw bytes,
                # so a rewritten line ending is a different measurement.
                Path(path).write_text(repaired, newline="")
                print(f"  {self.name}: repaired {Path(path).name}")
            except Exception as e:
                # The controller does not wrap execute(), so anything that
                # escapes here kills the run. A subprocess bridge fails in
                # more ways than the OSError the file-copy rungs guard
                # against, so everything becomes a report instead.
                print(f"  {self.name}: repair failed on "
                      f"{Path(path).name} - {e}")
            blackboard.write_entry(
                key=key, predicate=entry.predicate,
                measurement=source_measurement(path),  # new hash => re-verify
                result=None,
            )
