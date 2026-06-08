# pybb
python blackboard experiments
Todo:
- simulate control flow
- shared state between knowledge sources
  - IDEA: NumberSubtracter, NumberNegativeChecker. do pass offs
    - subtask/process (ignore this for now actually):
      - resolve collisions monitoring same key. for now just go in order
      - give KS 3 chances to get entry in good_standing until pass off.
        - original entry preserved in history. should have a marker of entry before it was touched by anything
      - pass off to next KS w/ history of attempts, original value/condition restored on BB
      - cycle continues w/ next KS
      - if all KS fail, move to escalate partition w/ all history and logging info
- escalate partition
  - process for moving entry to escalate after bb processes fail
- logging/history for entries to be used in escalate/other

# Current simulation goal:
Communication between knowledge sources
Example of certify -> p1 -> p2 -> certify
Example of certify -> p1 -> p2 -> loop? -> escalate
Think about x -> x'  ; x' -> y satisfaction example


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