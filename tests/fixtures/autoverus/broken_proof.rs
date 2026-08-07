// A proof attempt Verus rejects. The contract is written and the loop does
// carry an invariant -- but one conjunct is missing, so the `exists`
// postcondition cannot be discharged:
//
//   error: postcondition not satisfied
//     --> exists |i: int| 0 <= i < nums@.len() ==> nums@[i] == ret
//   verification results:: 1 verified, 1 errors
//
// A proof that is present but incomplete is exactly what AutoVerus's
// --mode repair is built for.
//
// Derived from find_max in AutoVerus's own Verus-Bench (Misc/verified,
// MIT-licensed) by deleting the loop invariant
//
//     exists |k: int| 0 <= k < i && nums@[k] == max,
//
// so the repair has a known-achievable target: the reference proof
// verifies at 2 verified, 0 errors.
#[allow(unused_imports)]
use vstd::prelude::*;
fn main() {}

verus! {
fn find_max(nums: Vec<i32>) -> (ret:i32)
requires
    nums.len() > 0,
ensures
    forall |i: int| 0 <= i < nums@.len() ==> nums@[i] <= ret,
    exists |i: int| 0 <= i < nums@.len() ==> nums@[i] == ret,
{
    let mut max = nums[0];
    let mut i = 1;
    while i < nums.len()
    invariant
        forall |k: int| 0 <= k < i ==> nums@[k] <= max,
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
