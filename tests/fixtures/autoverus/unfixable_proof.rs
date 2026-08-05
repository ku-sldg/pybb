// A proof Verus rejects that no repair can fix: the proof is complete and
// correct, and the SPECIFICATION is false.
//
// `ret` is `max`, which is an element of `nums`, so the strict postcondition
// demands `max < max` at the index holding it. `requires nums.len() > 0`
// rules out the vacuous escape, so no proof exists:
//
//   error: postcondition not satisfied
//     --> forall |i: int| 0 <= i < nums@.len() ==> nums@[i] < ret
//   verification results:: 1 verified, 1 errors
//
// This is the escalation fixture. AutoVerus cannot succeed here without
// weakening the spec -- which its own code_change_is_safe blocks, comparing
// pre- and post-repair specs via lynette, and this bridge never passes
// --disable-safe -- or reaching for a vacuous escape hatch, which find_cheat
// rejects before Verus is even invoked. So the rung fails honestly, the
// chain exhausts, and the entry escalates carrying the repair in ks_history.
//
// (Those escape hatches are deliberately not spelled out above: find_cheat
// is a plain substring scan, so naming them even in a comment would have
// this file rejected as vacuous before Verus ever ran -- escalating for the
// wrong reason and hiding the postcondition failure this fixture exists to
// show.)
//
// Derived from find_max in AutoVerus's own Verus-Bench (Misc/verified,
// MIT-licensed, (c) 2024 Microsoft) by changing ONE character in the first
// postcondition:
//
//     nums@[i] <= ret        ->      nums@[i] < ret
//
// Both loop invariants are left exactly as the reference proof has them. They
// establish `forall nums@[k] <= max` and `exists nums@[k] == max`, which
// together prove the postcondition false -- so Verus reports a clean
// postcondition failure rather than running out of ideas.
//
// Contrast broken_proof.rs: there the proof is incomplete and the spec is
// true, so repair converges. Here the proof is fine and the claim is wrong.
#[allow(unused_imports)]
use vstd::prelude::*;
fn main() {}

verus! {
fn find_max(nums: Vec<i32>) -> (ret:i32)
requires
    nums.len() > 0,
ensures
    forall |i: int| 0 <= i < nums@.len() ==> nums@[i] < ret,
    exists |i: int| 0 <= i < nums@.len() ==> nums@[i] == ret,
{
    let mut max = nums[0];
    let mut i = 1;
    while i < nums.len()
    invariant
        forall |k: int| 0 <= k < i ==> nums@[k] <= max,
        exists |k: int| 0 <= k < i && nums@[k] == max,
    decreases nums@.len() - i,
    {
        if nums[i] > max {
            max = nums[i];
        }
        i += 1;
    }
    max
}
}
