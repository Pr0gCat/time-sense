# Preflight: measure before the long run

Problem: launching an hours-long action without first checking whether it can
be made faster, or whether it will even work.

## When

- Projected run time >2 min, or you cannot project it at all.
- Any command over a dataset, the full test suite, a full build, a migration,
  a crawl, a batch API job, or anything with "all" in its scope.

## 1. Sample and extrapolate

1. Pick one unit: 1 file, 1 test module, 1 batch, or ~1% of the input.
2. Time it: `tb wrap --est <guess> --id pre-<name> -- <cmd on sample>`.
3. Note fixed overhead separately (startup, compile, connection, warmup).
4. Projection = unit time x number of units + fixed overhead.
5. Feed it through calibration: `tb est <projection> --kind action`.
6. If the sample failed, you just saved the full run. Fix, then resample.

## 2. Decide

| Projection | Decision |
|---|---|
| <=2 min | Run it, with a deadline |
| 2-10 min | Run it in the background with a deadline; do other work meanwhile |
| >10 min | Optimize first; spend at most 10% of the projection on optimizing |

## 3. Optimize (in priority order; stop when under budget)

1. **Cut scope** — run only what the question needs: one test (`-k`, `--filter`,
   `-run`), one package, changed files only, one target.
2. **Fail fast** — `pytest -x`, `jest --bail`, `go test -failfast`,
   `set -euo pipefail`, early assertions on input shape.
3. **Reuse** — caches, incremental builds, previous outputs, `--lf` (last
   failed), memoized intermediate files. Do not rebuild what did not change.
4. **Parallelize** — `make -j`, `pytest -n auto`, `xargs -P`, batched API
   calls, concurrent independent tool calls.
5. **Sample the data** — validate on a subset; run full data only once the
   pipeline is proven.
6. **Skip irrelevant stages** — lint/docs/packaging steps the question does not
   need.
7. **Move heavy work off the critical path** — start it in the background now,
   keep working on things that do not depend on it.

Re-project after optimizing. If still >10 min, tell the user the projection and
its basis before launching, unless they already approved long runs.

## 4. Launch safely

- Run in the background; never block the session on it.
- Always attach a deadline: run it as `tb wrap --est <projection> -- <cmd>`, and
  set any harness timeout above tb's hard deadline (3x calibrated estimate).
- Redirect output to a log file: `<cmd> > /tmp/<name>.log 2>&1`.
- Decide the progress signal before starting: a log line per item, a row count,
  a file count, a percentage. If there is none, add one (`--verbose`,
  `pv`, a counter print) so `SOFT` checks can tell slow from stuck.
- When the run ends, `tb stop` (or let `wrap` record it) so the next estimate
  is calibrated.

## Anti-patterns

- "It's probably fine, just run it all." — Measure one unit; it costs seconds.
- Re-running the full suite after every small fix. — Rerun the failing test only.
- Waiting in the foreground for a job you could have backgrounded.
- Optimizing for 30 min to save 5 min. — Respect the 10% budget.
