
// The verified reference: find_max from AutoVerus's Verus-Bench
// (Misc/verified, MIT-licensed; see README.md). Committed PASSING —
// 2 verified, 0 errors — so the provisioning bundle signs a passing
// measurement and readiness verifies. The demo's --tamper arc deletes
// the `exists |k| ...` loop-invariant conjunct, reproducing the
// tests/fixtures/autoverus/broken_proof.rs repair task (1 verified,
// 1 error) that AutoVerus's --mode repair is built for.
#[allow(unused_imports)]
use vstd::prelude::*;
fn main() {}

verus! {

#[verifier::loop_isolation(false)]
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
        exists |k: int| 0 <= k < i && nums@[k] == max,
    decreases nums@.len() - i,
    {
        if nums[i] > max {
            max = nums[i];
        }
        i += 1;
    }

    proof {
    } // Added by AI
    max
}
}

