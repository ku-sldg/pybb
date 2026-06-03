# pybb
python blackboard experiments
Todo:
- simulate control flow
- shared state between knowledge sources
  - IDEA: NumberSubtracter, NumberAdder, NumberChecker (check type). do pass offs
    - subtask/process:
      - resolve collisions monitoring same key. for now just go in order
      - give KS 3 chances to get entry in good_standing until pass off.
        - original entry preserved in history. should have a marker of entry before it was touched by anything
      - pass off to next KS w/ history of attempts, original value/condition restored on BB
      - cycle continues w/ next KS
      - if all KS fail, move to escalate partition w/ all history and logging info
- escalate partition
  - process for moving entry to escalate after bb processes fail
- logging/history for entries to be used in escalate/other