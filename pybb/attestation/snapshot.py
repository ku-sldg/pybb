"""
Clean-copy snapshots of attested target files.

Attestation protocols measure the live target tree. A `TargetSnapshot` is
the clean copy of the watched files: `capture()` provisions one from the
live tree (the deliberate act of declaring it known-good — e.g. into the
repo's golden directory), `load()` opens one that already exists, and
`restore()` reverts the live targets to it. Nothing in the attestation flow
calls capture() or restore() — declaring and reverting are repair / new-run
decisions made outside the measurement path, so a failed appraisal can
neither overwrite its own evidence nor launder tampered files into gold.
"""

from __future__ import annotations

import filecmp
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


def watched_files(protocols: Dict[str, Any]) -> Set[Path]:
    """Every filepath referenced by the protocols' asp_args."""
    return {
        Path(args["filepath"])
        for proto in protocols.values()
        for targets in proto.asp_args.values()
        for args in targets.values()
        if args.get("filepath")
    }


class TargetSnapshot:
    """
    Clean copy of the watched target files, captured before attestation.

    Live absolute paths are mirrored under `root` (e.g. `/a/b/c` is stored
    at `<root>/a/b/c`), so files from multiple target trees coexist in one
    snapshot without needing a common ancestor.
    """

    def __init__(self, root: Path, files: Dict[Path, Path]):
        self.root = root
        self.files = files  # live path -> snapshot copy

    @classmethod
    def capture(
        cls, protocols: Dict[str, Any], dest: Optional[Path] = None
    ) -> "TargetSnapshot":
        root = Path(dest) if dest else Path(tempfile.mkdtemp(prefix="pybb_snapshot_"))
        files = {}
        for live in sorted(watched_files(protocols)):
            copy = root / live.relative_to(live.anchor)
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(live, copy)
            files[live] = copy
        return cls(root, files)

    @classmethod
    def load(cls, protocols: Dict[str, Any], root: Path) -> "TargetSnapshot":
        """
        Open an existing snapshot (e.g. the provisioned golden directory).
        Every watched file must already have a copy under `root`.
        """
        root = Path(root)
        files = {
            live: root / live.relative_to(live.anchor)
            for live in sorted(watched_files(protocols))
        }
        missing = [str(live) for live, copy in files.items() if not copy.is_file()]
        if missing:
            raise FileNotFoundError(
                f"no snapshot copy under {root} for: " + ", ".join(missing)
            )
        return cls(root, files)

    def dirty(self) -> List[Path]:
        """Live targets that no longer match their snapshot copy (or are gone)."""
        return [
            live
            for live, copy in self.files.items()
            if not (live.is_file() and filecmp.cmp(live, copy, shallow=False))
        ]

    def restore(self) -> List[Path]:
        """Revert changed live targets to their clean copies; return them."""
        changed = self.dirty()
        for live in changed:
            live.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.files[live], live)
        return changed
