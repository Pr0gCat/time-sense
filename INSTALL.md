# Installing time-sense (instructions for AI agents)

You are an AI coding agent asked to install time-sense for the user. Follow the
section for the harness the user asked for. If they did not say, install for
the harness you are running in. Run every command; do not skip verification.

Requirements: `python3` >= 3.9 and `git`. Check with `python3 --version`.

Repository: https://github.com/Pr0gCat/time-sense

## omp (Oh My Pi)

```bash
omp plugin install github:Pr0gCat/time-sense
```

Verify:

1. `omp plugin list` shows `time-sense@<version>`.
2. `omp plugin doctor` reports `plugin:time-sense` with no error.
3. Tell the user to start a new omp session. In it, the system prompt contains
   `TIME SENSE ACTIVE` and the skill list contains `time-sense`.

Update: `omp plugin upgrade time-sense`. Uninstall: `omp plugin uninstall time-sense`.

## Claude Code

Clone to a temporary directory and run the installer. It copies files (no
symlinks), so the clone can be deleted afterwards.

```bash
TMP=$(mktemp -d)
git clone --depth 1 https://github.com/Pr0gCat/time-sense "$TMP/time-sense"
python3 "$TMP/time-sense/install.py" claude
rm -rf "$TMP"
```

The installer:

- copies the skill to `~/.claude/skills/time-sense/`
- writes the resident rule into `~/.claude/CLAUDE.md` between
  `<!-- time-sense:begin -->` and `<!-- time-sense:end -->`
- merges enforcement hooks into `~/.claude/settings.json`, keeping existing hooks
- backs up each changed file once as `<file>.bak-time-sense`

Re-running it replaces the previous install, so it is also the update command.

Verify:

1. `ls ~/.claude/skills/time-sense/scripts` lists `tb.py` and `claude_hook.py`.
2. `grep -c 'time-sense:begin' ~/.claude/CLAUDE.md` prints `1`.
3. `grep -c claude_hook.py ~/.claude/settings.json` prints `5`.
4. `python3 ~/.claude/skills/time-sense/scripts/tb.py est 5m` prints a line
   starting with `tb: est 5m00s`.
5. Tell the user to start a new Claude Code session; hooks and CLAUDE.md load
   at session start.

Uninstall: clone again and run `python3 install.py claude --uninstall`. It
removes the skill, the marked rule block, and only the time-sense hooks.

## Codex (skills path unverified)

```bash
TMP=$(mktemp -d)
git clone --depth 1 https://github.com/Pr0gCat/time-sense "$TMP/time-sense"
python3 "$TMP/time-sense/install.py" codex
rm -rf "$TMP"
```

This copies the skill to `~/.codex/skills/time-sense/` and writes the rule into
`~/.codex/AGENTS.md`. No hooks. The skills path has not been verified against
a real Codex install; tell the user so, and if their Codex reads skills from a
different directory, move the copied folder there.

## Report back

Tell the user which harness you installed for, the verification results, and
that a new session is needed. Mention that state (timers and the calibration
ledger) is stored locally in `~/.time-sense` (override with `TIME_SENSE_HOME`).
