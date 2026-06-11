# pybb
python blackboard experiments
Todo:
- simulate control flow
- logging/history for entries to be used in escalate/other
- resolving conflicts between KSes
- KS creating its own blackboard to break up smaller problem?

# Current simulation goal:
Control flow
Example of certify -> p1 -> certify -> p2 -> certify
Example of certify -> p1 -> escalate -> p2 -> certify
Think about resolving conflicts between 

## Example:


THINGS:
- (DONE?) have the can_contribute return the key so that the KS doesn't need to loop through its partition again. controller passes over key and into KS execute
  - but what if there are multiple keys? --> return list of keys?
    - for now: have controller maintain bad keys, KS receives bad keys into execute and only iterates through those
      - for future: could have specialized functions for different tasks that monitor unique keys/types of problems

# simulation goal 1 (complete):
Simulate moving to escalate partition
NumberChecker monitors lt_3, is_positive
1. less_than_3 gets measurement 4
2. NC does whatever to resolve
3. Receive new measurement -1 to is_positive
4. NumberChecker retries and documnets its process for is_positive
5. reach threshold for attempts
6. move entry to escalate segment w/ history
  a. ensure that original measurement is on bb

# Questions
- what happens when KS has 2 bad standings to resolve?