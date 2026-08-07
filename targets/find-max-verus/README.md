# find-max-verus

One self-contained Verus file, `find_max.rs`, committed in its VERIFIED
state (2 verified, 0 errors) — the attested AutoVerus repair demo's
target (`examples/find_max_verus.py`, protocol `find_max_verus_check`).

Provenance: `find_max` from AutoVerus's Verus-Bench (Misc/verified,
MIT-licensed; github.com/microsoft/verus-proof-synthesis), the same
source `tests/fixtures/autoverus/broken_proof.rs` derives from. The
committed file is the reference proof; the demo's `--tamper` arc deletes
the `exists |k: int| 0 <= k < i && nums@[k] == max` loop-invariant
conjunct, reproducing the broken fixture's repair task (1 verified,
1 error — the `exists` postcondition cannot be discharged).

The committed state is verified because the provisioning bundle signs an
actual measurement run: readiness re-appraises the stored evidence at
every episode, so the blessed baseline must pass.
