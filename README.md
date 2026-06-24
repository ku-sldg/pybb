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
## Controller
### Attributes

## Blackboard

