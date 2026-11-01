---
name: time-sense
description: >
  Time discipline for agents. Use before running long commands, builds, tests,
  data jobs or migrations; when dispatching subagents or background tasks; when
  estimating effort or duration; when work runs past its estimate or keeps
  failing; and when deciding whether to stop or abandon an approach.
---

# time-sense

Wall-clock time is a cost. Every minute spent waiting, retrying, or running an
unoptimized job is a minute the user pays for. This skill turns that cost into
explicit numbers: estimate, measure, set deadlines, watch them, and stop when
the numbers say stop.

`tb` below means `python3 <this skill dir>/scripts/tb.py`.

## Core loop

`ESTIMATE -> PREFLIGHT -> RUN WITH DEADLINE -> WATCH -> CHECKPOINT -> CLOSE (stop + record)`

- **ESTIMATE** — before any long command, subagent, or phase. Count steps, not feelings. Read `references/estimation.md`.
- **PREFLIGHT** — projected >2 min or unknown: time a sample, extrapolate, optimize first. Read `references/preflight.md`.
- **RUN WITH DEADLINE** — anything expected >30s runs under `tb wrap --est` (deadline + calibration record); never block without a limit. Read `references/preflight.md`.
- **WATCH** — every delegated subagent/task gets a budget, a timer, and a `tb check` on every wake. Read `references/watchdog.md`.
- **CHECKPOINT** — at each phase boundary or ~10 tool calls, look for repetition, serial work, slow loops. Read `references/process-optimization.md`.
- **CLOSE** — `tb stop` with the real outcome; when a stop rule fires, quit cleanly and report. Read `references/quitting.md`.

## Thresholds

| Signal | Threshold | Action |
|---|---|---|
| Projected run time | >2 min, or unknown | Preflight: time a sample first |
| Preflight sample size | ~1% of input, or 1 unit (file / test / batch) | Extrapolate: unit time x units + fixed overhead |
| Projected run time | >10 min | Optimize before the full run; optimization budget <= 10% of projected run time |
| Soft deadline | 1.5x calibrated estimate | Inspect progress; continue or steer |
| Hard deadline | 3x calibrated estimate | Kill, rescope, or report |
| Checkpoint cadence | Each phase, or ~10 tool calls | Run the process-optimization checklist |
| Stop rule | Same approach failed 3x with no new information, or 2 fixes left the error message unchanged | Stop; switch approach, revert, or escalate |

These numbers are defaults. They live here, in the resident rule, and in the
`tb.py` constants; change all three together.

## tb quick reference

```bash
tb est 5m --kind action                          # calibrated estimate + soft/hard deadlines
tb start sub-auth --est 8m --kind subagent --note "auth refactor"
tb check                                         # all timers; or: tb check sub-auth
tb stop sub-auth --outcome done                  # done | failed | abandoned
tb calib                                         # per-kind n, median actual/est, factor
tb wrap --est 3m -- npm test                     # SOFT warning, HARD kill, auto-recorded
```

Kinds: `action` (shell command / build / test), `subagent` (delegated agent or
background task), `step` (one phase of your own work), `task` (the whole user request).

Exit codes:

| Code | Meaning |
|---|---|
| 0 | OK / success (`wrap`: command's own exit code is passed through) |
| 10 | `check`: worst timer past soft deadline |
| 20 | `check`: at least one timer past hard deadline |
| 124 | `wrap`: command killed at hard deadline |
| 2 | Usage error (bad duration, unknown id, duplicate id, no command) |

Calibration needs at least 3 `done`/`failed` records of a kind; until then the
factor is 1.00 and the output says `uncalibrated`. `abandoned` records are
excluded because their actual time was cut short.

**Always `tb stop` with the true outcome.** A timer stopped as `done` when it
failed, or never stopped at all, corrupts the factor that every later estimate
depends on. Honest records are the whole point.

## When NOT to use tb

- A single quick command expected to finish in <30s.
- Trivial edits: a typo, a one-line change, reading one file.

Timer overhead (two tool calls) is not worth it there. Still estimate in your
head; just skip the bookkeeping.

## Reporting

Report estimates to the user as a range plus its basis:

> ~3-5 min: 12 tool calls + 1 test run measured at 40s

Never a bare number, never person-days. Use human-effort units only when the
user explicitly asks, and label them as such.
