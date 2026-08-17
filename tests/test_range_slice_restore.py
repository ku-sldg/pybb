"""RangeSliceRestoreKS: content-aligned splicing of positional slices.

The repair unit is the measurement unit: only divergences overlapping a
violated slice's golden span are restored; every other divergence —
notably an inserted note that shifts positions — survives the repair.
"""

from pathlib import Path

from pybb.attestation.repair import RangeSliceRestoreKS
from pybb.attestation.snapshot import mirror_path

GOLD = """line one
line two
slice a
slice b
line five
line six
"""


def _setup(tmp_path: Path):
    live = tmp_path / "live" / "f.txt"
    live.parent.mkdir(parents=True)
    live.write_text(GOLD)
    golden_root = tmp_path / "golden"
    copy = mirror_path(golden_root, live)
    copy.parent.mkdir(parents=True)
    copy.write_text(GOLD)
    ks = RangeSliceRestoreKS(golden_root=golden_root)
    return live, ks


def test_corrupted_slice_restored_note_survives(tmp_path):
    live, ks = _setup(tmp_path)
    text = GOLD.splitlines(keepends=True)
    text[2] = "slice a TAMPERED\n"                    # inside span (3, 4)
    text.insert(0, "// note above everything\n")      # shifts every position
    live.write_text("".join(text) + "// trailing note\n")

    hit, missed = ks._splice_file(live, [(3, 4)])
    assert hit == [(3, 4)] and missed == []
    out = live.read_text()
    assert "slice a\n" in out and "TAMPERED" not in out
    assert out.startswith("// note above everything\n")
    assert out.endswith("// trailing note\n")


def test_benign_insertion_inside_slice_is_reverted(tmp_path):
    live, ks = _setup(tmp_path)
    text = GOLD.splitlines(keepends=True)
    text.insert(3, "smuggled into the slice\n")       # strictly inside (3, 4)
    live.write_text("".join(text))

    hit, missed = ks._splice_file(live, [(3, 4)])
    assert hit == [(3, 4)] and missed == []
    assert live.read_text() == GOLD


def test_divergence_outside_every_slice_left_alone(tmp_path):
    live, ks = _setup(tmp_path)
    text = GOLD.splitlines(keepends=True)
    text[5] = "line six EDITED\n"                     # outside (3, 4)
    live.write_text("".join(text))

    hit, missed = ks._splice_file(live, [(3, 4)])
    assert hit == [] and missed == [(3, 4)]
    assert "line six EDITED" in live.read_text()


def test_missing_golden_is_unrestorable(tmp_path):
    live, ks = _setup(tmp_path)
    other = live.parent / "elsewhere.txt"
    other.write_text("x\n")
    hit, missed = ks._splice_file(other, [(1, 1)])
    assert hit == [] and missed == [(1, 1)]
