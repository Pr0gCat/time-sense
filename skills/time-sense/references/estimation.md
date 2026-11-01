# Estimation: agent time, counted, calibrated

Problem: guessing durations by gut, overestimating difficulty, and quoting
human-engineer timescales ("2-3 days") for work an agent finishes in minutes.

## Agent time model

| Unit | Typical cost |
|---|---|
| One tool call (read, grep, edit, short command) | ~10-30s |
| Read or edit a single file | a few seconds of tool time |
| One model turn (think + respond) | ~20-60s |
| Machine time (build, tests, downloads, jobs) | **Measure it. Never guess.** |

## Procedure

1. List the steps. Concrete actions: "read X", "edit Y", "run test Z".
2. Count tool calls per step; multiply by ~20s.
3. Add machine time you have measured (previous run, preflight sample, log
   timestamps). Unknown machine time -> preflight first (`preflight.md`).
4. Calibrate: `tb est <total> --kind <k>`. The factor comes from your own
   ledger of actual/estimate ratios; trust it over intuition.
5. For multi-phase work, also time each phase: `tb start <phase> --kind step`.

## Starting priors (agent minutes)

These are **starting priors, replaced by your ledger** once `tb calib` shows
n >= 3 for the kind. They assume a working dev environment.

| Task | Prior |
|---|---|
| Rename a symbol across 20 files (with LSP/codemod) | 2-5 min |
| Rename across 20 files by hand edits | 5-10 min |
| Add one HTTP endpoint + its tests in a familiar codebase | 10-20 min |
| Debug a failing test that has a reliable repro | 5-20 min |
| Read and summarize an unfamiliar 5k-line module | 5-10 min |
| Write a 200-line standalone script + smoke run | 5-10 min |

## Against overestimation

- If you can list the steps, the task is not hard; estimate the steps.
- Unfamiliar code is a reading cost (minutes), not a difficulty multiplier.
- "Large" refactors are usually many small, mechanical edits; count them.
- The real uncertainty is usually machine time or an unknown root cause.
  Name that specific uncertainty instead of inflating everything.

## Human-time units

Use person-hours/days only when the user explicitly asks how long a human would
take, and label it: "human estimate: ~2 days; agent estimate: ~25 min".

## Reporting

Give a range plus its basis:

> ~3-5 min: 12 tool calls + 1 test run measured at 40s

> ~20-40 min: 4 phases; unknown root cause in phase 2 is the main risk

Never a bare number. When the estimate is blown, say so early with the new
estimate and why, rather than silently running long.
