# Mr. Pybb (Python Blackboard)

**Install / run the demos:** see [docs/INSTALL.md](docs/INSTALL.md) —
`scripts/install.sh` builds the full attestation stack (CVM, asp-libs,
Rocq, Verus, Sireum/HAMR) and brings both interactive demo arcs
(`examples/demo_rocq.sh`, `examples/demo_isolette.sh`) to a passing
readiness gate.

## Vocabulary
* **partition:** collection of keys a knowledge source looks at
* **segment:** broader regions of blackboard. currently: **provision** (requests written by external events, e.g. to provision golden evidence; evaluated before certify each cycle, no knowledge-source chains — a failing request escalates immediately, a passing one remains as the record of provisioned state), **certify** (all other entries, entries with current work in progress, entries in good standing), **escalate** (entries that require user intervention)
* **component:** one named part of a dict measurement (e.g. `"x"` in `{"x": 5, "y": -2}`). Each component can have its own condition, and a knowledge source can be scoped to a single component
## Current Control Flow (missing a lot of detail)
1. Receive measurement and write entry to the blackboard
2. Controller establishes a "route" (knowledge source chains that can execute on an entry). After the entry's first evaluation, the Controller dispatches it onto a chain based on the outcome (see "Outcome-routed dispatch") and places it in that chain's first knowledge source's partition
3. Controller iterates through knowledge sources
4. If a knowledge source can contribute, run its `execute` function on the blackboard entry in its partition that is not in good standing
5. Knowledge source operates on blackboard entry and passes its result back to the Controller
6. Controller reverifies the entry
8. If the entry is still in bad standing after a knowledge source operated on it, send entry back to knowledge source for more attempts and controller reverifies after each attempt.
9. If a knowledge source reaches max_attempts and blackboard entry is still not in good standing, Controller passes the original blackboard entry to the next knowledge source in the route (failure handoff). For a component-scoped knowledge source, only its own component is restored so other components' fixes are preserved.
10. If all knowledge sources in the route fail and there are no more available knowledge sources in the route, move the bad entry to the "escalate partition"
11. The program will halt if all the entries are in good standing

### Restart-episode primitive
A knowledge source may call `request_restart(key, reason)` — for its own key or any other — to ask for a **fresh episode**: at the top of the next cycle the Controller forgets the predicate's memoized results for that entry's episode measurements (predicates expose an optional `forget` hook), resets the entry to its original measurement with a fresh `ks_history`, clears the dispatch latch and chain partitions, and re-evaluates — so memoized predicates (e.g. attestation) genuinely re-measure. Restarts are **pull-only** (nothing watches for state changes; re-evaluation happens only on request) and capped per key by the Controller's `max_restarts_per_key` regardless of who asks, so halting never depends on requester politeness. Completed restarts are counted in `blackboard.restarts` (outside the entry — a reset must not erase budget accounting).

### Component-wise entries (success-driven handoff)
An entry can instead hold a dict measurement (e.g. a pair `{"x": 5, "y": -2}`) with per-component `conditions` (e.g. `{"x": "less_than_3", "y": "is_positive"}`). The entry is in good standing only when every component's condition passes. Knowledge sources declare a `component` they may operate on and write repairs through `write_component`, so KS1 can only touch x and KS2 can only touch y. This enables a second advancement mode alongside failure handoff:
* **success handoff:** when the current knowledge source's component passes its condition, the Controller advances the key to the next knowledge source in the route *without* restoring anything - the fix is preserved (e.g. KS1 fixes x, then KS2 works on y)
* **failure handoff:** when the current knowledge source exhausts max_attempts, only its own component is restored to the original before handing off
* **end of route:** if the current component passes (or all knowledge sources are exhausted) and no knowledge source remains but the entry is still not in good standing overall, the entry is escalated

The overall pair is evaluated by the Controller at the start of every cycle, so once the last knowledge source fixes its component, the next cycle marks the whole entry in good standing and the program halts. See `example_pair.py`.

### Outcome-routed dispatch (on_pass / on_fail)
A route holds two chains, and the Controller chooses between them once the entry's first verdict exists:
* **on_fail:** the classic repair ladder, tried when the entry evaluates out of good standing. `route(key, chain)` is shorthand for `route(key, on_fail=chain)`, so existing routes keep their meaning
* **on_pass:** an optional confirmation chain, tried once when the entry evaluates as *passing*. The pass is provisional: the Controller clears the entry's standing, the chain's knowledge sources do their work, and re-evaluation decides. An empty on_pass chain means a pass is final
* Dispatch happens once per key. Within the chosen chain, failure handoff, success handoff, and end-of-route escalation behave exactly as described above; an empty chosen chain escalates immediately (nothing can help)

This lets a route encode a decision tree rather than a single ladder — e.g. remote attestation (`pybb/attestation`): a cheap integrity check that *fails* is attributed by a finer-grained tier on `on_fail`, while one that *passes* is semantically confirmed by an expensive verification tier on `on_pass`; either tier's failure escalates with that tier's report. See `pybb/attestation/README.md`.
## Knowledge Source
### Attributes
* **name:** name of knowledge source
* **partition:** collection of keys a knowledge source looks at
* **max_attempts:** maximum allowed attempts for a knowledge source to make on a single blackboard entry
* **component:** optional. scopes the knowledge source to one component of a dict measurement. By convention a component-scoped knowledge source only writes through `write_component` with its own component
### Methods
* **can_contribute:** knowledge source iterates through its own partition to identify any blackboard entries that are not in good standing (for a component-scoped knowledge source: whose *component* is not in good standing)
* **execute:** action knowledge source executes on a blackboard entry when entry is not in good standing

## Blackboard Entry
### Attributes
* **predicate:** name of a function (single-condition entries; optional if `conditions` is set)
* **conditions:** optional mapping of component name to predicate name for dict measurements (e.g. `{"x": "less_than_3", "y": "is_positive"}`). An entry must have either `predicate` or `conditions`
* **measurement:** value received as input (a plain value, or a dict of components when using `conditions`)
* **result:** result of running predicate function with measurement as its argument --> predicate(measurement). For component-wise entries, a dict of component name to boolean
* **good_standing:** boolean indicator of whether result of predicate(measurement) is in good standing (currently the same value as `result`; for component-wise entries, true only when all components pass)
* **original_measurement:** initial measurement restored by controller during knowledge source handoff
* **ks_history:** dictionary containing a mapping of the name of a knowledge source and how many attempts it has made on the current entry

## Blackboard
### Attributes
* **entries:** dictionary mapping of entry IDs to a blackboard entry (at the moment, the entry ID is the same as the predicate name for the blackboard entry)
* **provision:** dictionary mapping of request IDs to provisioning-request entries (the provision segment). Evaluated before certify each cycle; never enters the knowledge-source machinery
* **history:** list history of changes made to blackboard entries (all segments share it)
* **escalate:** separate dictionary mapping of netry IDs to blackboard entries that require user intervention (all knowledge sources failed repair, or a provisioning request failed)

### Methods
* **write_entry:** write an entry to the certify, provision, or escalate segments of the blackboard. all entries added to the "certify" segment by default.
* **get_entry:** retrieves a blackboard entry at a given key
* **get_all_entries:** returns all entries currently in certify segment of blackboard
* **get_history:** returns all previous and current entries in certify segment of blackboard
* **get_escalate:** returns current entries n escalate segment of blackboard
* **get_provision:** returns current entries in provision segment of blackboard
* **add_ks_history:** increments number of attempts a knowledge source has made on a particular blackboard entry
* **restore_original:** restores original measurement associated with a blackboard entry
* **write_component:** write a repair for a single component of a dict measurement, leaving the other components untouched
* **restore_component:** restores a single component of a dict measurement from the original, preserving fixes made to other components

## Controller
### Attributes
* **blackboard:** blackboard the contorller operates on
* **knowledge_sources:** list of knowledge sources to be used
* **predicate_registry:** temporary mapping of blackboard entry keys to callable functions
* **routes:** mapping of a blackboard entry key to its outcome-routed knowledge source chains (`on_pass` / `on_fail`)
* **dispatched:** mapping of a blackboard entry key to the chain chosen by its first evaluated outcome
* **max_cycles:** maximum cycles controller can perform if termination conditions are not met (don't think this is reachable at the moment due to escalate)
* **cycle_count:** number tracking the amount of cycles the controller has run. 1 cycle=1 iteration through all knowledge sources
### Methods
* **register_predicate:** create a mapping between a blackboard entry key and a callable
* **add_ks:** add a knowledge source to the controller's list of knowledge sources
* **route:** registers outcome-routed chains for a blackboard entry key. Placement happens at dispatch time (after the entry's first evaluation), since the chain depends on the outcome
  * example rationale: `route("less_than_3", [ks1, ks2])` ==> ks1 attempts on blackboard entry "less_than_3", if ks1 fails, ks2 attempts on the same blackboard entry. If all knowledge sources in the route fail, entry is moved to escalate
  * `route(key, on_pass=[ks3], on_fail=[ks1, ks2])` additionally sends a *passing* first verdict through ks3 for confirmation before the entry may rest in good standing
* **_dispatch:** each cycle, places routed keys whose first verdict exists onto the matching chain (failing -> on_fail, passing with a confirmation chain -> on_pass)
* **_advance:** moves a blackboard entry key into the next eligible knowledge source. On failure (current knowledge source reached maximum attempts) restores the measurement the knowledge source worked on - component-scoped for component knowledge sources, full otherwise. On success (`restore=False`, current knowledge source's component passed) preserves the fix. Moves entry to escalate partition if no available knowledge source remains in the route.
* **_advance_ready:** success-driven handoff. Each cycle, after evaluation, advances any key whose current component-scoped knowledge source has satisfied its component's condition
* **_evaluate_entry:** evaluates a predicate with a given measurement. calls the function from the predicate registry and uses the measurement as a parameter to the function. Update the standing of the entry according to the result of calling the predicate with the measurement. For component-wise entries, evaluates each component's predicate and sets good standing only if all pass.
* **_evaluate_all:** calls `_evaluate_entry` on all the blackboard entries — the provision segment first, then certify, so certify entries in the same cycle always see freshly provisioned state
* **_escalate_failed_provision:** moves provisioning requests that evaluated and failed straight to the escalate segment (the provision segment has no knowledge-source chains)
* **run:** main control loop. Determines which knowledge sources can contribute, routes knowledge sources using `_advance`, and calls knowledge source `execute`. Maintains a history of the blackboard that shows all changes.
* **status:** prints the current number of cycles and all blackboard entries