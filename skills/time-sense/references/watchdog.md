# Watchdog: never wait forever on delegated work

Problem: dispatching a subagent or background task, then waiting indefinitely
with no deadline and no progress check.

## Before dispatch

1. Estimate the subagent's work (see `estimation.md`): its steps x ~20s plus
   any machine time it must spend.
2. Start a timer: `tb start sub-<name> --est <dur> --kind subagent --note "<goal>"`.
   Use `--kind action` for a plain background command.
3. Write the budget and the deliverable into the task prompt itself:

   ```
   Time budget: <dur>. Deliverable: <exact artifact / answer>.
   At <dur>, stop and return partial results with status (done / remaining /
   blockers) instead of continuing.
   Any `tb wrap --est X` you run must fit the budget: 3 x X <= remaining budget.
   ```

   The last line matters: a `tb wrap` hard deadline is 3x its estimate, so a
   subagent wrapping a command with `--est 2m` can run 6m inside a 5m budget.

4. If the harness supports it, ask for incremental output (progress notes,
   partial files) so you can judge progress without waiting for completion.
5. Set any harness `wait` / `timeout` parameter to the soft deadline
   (1.5x calibrated). Never omit it; never pass "no timeout".
6. Dispatch in the background when the harness allows it (omp `task` is async;
   Claude Code: `run_in_background: true`). A foreground subagent blocks you,
   so you cannot `tb check` it; its only watchdog is its own deadlines.

## While it runs

- Do not idle. If other work exists, do it; results arrive on their own.
- On every wake (any result, message, or notification): `tb check`.

| `tb check` | Action |
|---|---|
| OK (exit 0) | Continue your own work |
| SOFT (exit 10) | Read the subagent's progress / output / log. Progressing -> let it run, maybe steer with a message. Stuck or looping -> treat as HARD |
| HARD (exit 20) | Cancel it. Collect partial results. Then rescope and re-dispatch smaller, do it yourself, or report to the user |

## Cancelling (by harness)

- omp: write to `proc://<id>/kill`; read `agent://<id>` for partial output.
- Claude Code: stop the background task / agent (TaskStop or the task UI);
  read its output file for partial results.
- Plain shell job: `kill <pid>` (or `kill -- -<pgid>` for the whole tree).
- `tb wrap` jobs kill themselves at the hard deadline (exit 124).

## After

- `tb stop sub-<name> --outcome done|failed|abandoned` with the true outcome.
  A cancelled subagent is `abandoned`.
- If you re-dispatch, start a new timer with a new id; do not reuse the old one.

## Smells

- "I'll just wait a bit more" for the third time. — That is the hard deadline.
- No visible output for longer than the soft deadline. — Inspect now.
- Subagent asking the same question or redoing the same step. — Steer or kill.
- Waiting on a subagent whose result you no longer need. — Kill it.
