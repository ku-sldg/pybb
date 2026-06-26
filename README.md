# Mr. Pybb (Python Blackboard)
## Current Control Flow (missing a lot of detail)
1. Receive measurement and write entry to the blackboard
2. Controller establishes a "route" (list of knowledge sources that can execute on an entry) and places the entry in the first knowledge source's partition
3. Controller iterates through knowledge sources
4. If a knowledge source can contribute, run its `execute` function on the blackboard entry in its partition that is not in good standing
5. Knowledge source operates on blackboard entry and passes its result back to the Controller
6. Controller reverifies the entry
8. If the entry is still in bad standing after a knowledge source operated on it, send entry back to knowledge source for more attempts and controller reverifies after each attempt.
9. If a knowledge source reaches max_attempts and blackboard entry is still not in good standing, Controller passes the original blackboard entry to the next knowledge source in the route.
10. If all knowledge sources in the route fail and there are no more available knowledge sources in the route, move the bad entry to the "escalate partition"
11. The program will halt if all the entries are in good standing
## Knowledge Source
### Attributes
* **name:** name of knowledge source
* **partition:** collection of keys a knowledge source looks at
* **max_attempts:** maximum allowed attempts for a knowledge source to make on a single blackboard entry
### Methods
* **can_contribute:** knowledge source iterates through its own partition to identify any blackboard entries that are not in good standing
* **execute:** action knowledge source executes on a blackboard entry when entry is not in good standing

## Blackboard
### Attributes
### Methods

## Controller
### Attributes
* **blackboard:** blackboard the contorller operates on
* **knowledge_sources:** list of knowledge sources to be used
* **predicate_registry:** temporary mapping of blackboard entry keys to callable functions
* **routes:** mapping of a blackboard entry key to a knowledge source chain that can operate on that entry
* **max_cycles:** maximum cycles controller can perform if termination conditions are not met (don't think this is reachable at the moment due to escalate)
* **cycle_count:** number tracking the amount of cycles the controller has run. 1 cycle=1 iteration through all knowledge sources
### Methods
* **register_predicate:** create a mapping between a blackboard entry key and a callable
* **add_ks:** add a knowledge source to the controller's list of knowledge sources
* **route:** registers a route for a blackboard entry key and places the key in the first knowledge source's partition
  * example rationale: `route("less_than_3", [ks1, ks2])` ==> ks1 attempts on blackboard entry "less_than_3", if ks1 fails, ks2 attempts on the same blackboard entry. If all knowledge sources in the route fail, entry is moved to escalate
* **_advance:** moves a blackboard entry key into the next eligible knowledge source after the current knowledge source reaches maximum attempts on a key (failure). Restores the original measurement or moves entry to escalate partition if no available knowledge source remains in the route.
* **_evaluate_entry:** evaluates a predicate with a given measurement. calls the function from the predicate registry and uses the measurement as a parameter to the function. Update the standing of the entry according to the result of calling the predicate with the measurement.
* **_evaluate_all:** calls `_evaluate_entry` on all the blackboard entries
* **run:** main control loop. Determines which knowledge sources can contribute, routes knowledge sources using `_advance`, and calls knowledge source `execute`. Maintains a history of the blackboard that shows all changes.
* **status:** prints the current number of cycles and all blackboard entries