# Process optimization: improve how you work, mid-task

Problem: grinding through a task the same way from start to finish, never
noticing that the process itself is the bottleneck.

## When

At every checkpoint: each phase boundary, or roughly every ~10 tool calls.
Also whenever a `tb check` returns SOFT on your own `step` timer.

## Checkpoint questions

Ask each; act on any "yes".

1. **Repetition** — Have I done the same manual operation >=3 times?
   -> Script it (loop, codemod, `sed`-free AST edit, small helper script).
2. **Serial independence** — Are my next calls independent of each other?
   -> Issue them in parallel (parallel tool calls, subagents, `xargs -P`).
3. **Re-reading** — Am I searching for or re-reading the same thing again?
   -> Write the fact down once (notes file, todo item) and reuse it.
4. **Slow feedback loop** — Does each iteration take >1 min to tell me if I am
   right? -> Shorten it: run one test, use watch mode, build a minimal repro,
   call the function directly instead of the full app.
5. **Experiment choice** — Is my next experiment the cheapest one that
   distinguishes between my live hypotheses? -> If not, pick the one that is
   (a print statement before a full rebuild; a bisect before a rewrite).
6. **Scope drift** — Am I doing work the user did not ask for? -> Drop it.

## Rule: optimize only when it pays

Optimize the process only when

    (time saved on remaining work) > (time to optimize)

Estimate both with the same agent-time model (`estimation.md`). A 2-min script
that saves 10 manual edits is worth it; a 15-min tool for 3 remaining edits is
not. Near the end of a task, optimization rarely pays — just finish.

## Record

When the checkpoint changes your plan, note it in one line (todo item or
progress report): what changed, expected saving. If a phase timer is running,
keep it; the ledger should reflect the real phase duration.

## Smells

- Ten nearly identical edit calls in a row.
- Running the whole suite to check one assertion.
- Waiting on calls that could have been issued together.
- "Let me look at that file again."
