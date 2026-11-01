# Quitting: stop rules, decided in advance

Problem: never giving up — retrying a dead approach forever, or pushing past
every deadline because so much time has already been spent.

## Before starting

Set the stop rule up front, while you are still objective:

- Deadline: the hard deadline from `tb est` (3x calibrated estimate).
- Max attempts: 3 for any single approach.

Write both into your plan or todo list.

## Triggers (any one -> stop this approach)

- Hard deadline reached (`tb check` exit 20, or `tb wrap` exit 124).
- Same approach failed 3x with no new information.
- 2 fixes applied and the error message is exactly unchanged — your model of
  the problem is wrong.
- Remaining cost now exceeds the value of finishing this way.

## Sunk-cost rule

Time already spent is not a reason to continue. Decide only on:

    remaining cost of this path  vs  remaining cost of the alternatives

"I've already spent 40 minutes on this" is not an argument.

## Exits, in order of preference

1. **Switch approach** — a genuinely different hypothesis or technique, not the
   same one with a tweak. New timer, new stop rule.
2. **Cut scope** — deliver the part that works; isolate the part that does not.
3. **Revert** — return to the last known-good state (`git stash`, `git checkout`
   the file, undo the migration) so you do not leave a broken tree.
4. **Escalate** — report to the user with evidence and options.

## Escalation format

```
Goal: <what was asked>
Tried: <approach 1> -> <result + evidence>; <approach 2> -> <result + evidence>
State: <what works, what is broken, what was reverted>
Options:
  A. <option> (~<estimate>, <risk>)
  B. <option> (~<estimate>, <risk>)
  C. <option> (~<estimate>, <risk>)
```

## Quitting is not dropping

Abandoning an approach never means silently abandoning the task. Either switch
to another exit above, or report explicitly. The user must always know the
current state.

## Record it

`tb stop <id> --outcome abandoned` for the timer of the abandoned approach.
Abandoned records do not skew calibration, but they keep the history honest.
