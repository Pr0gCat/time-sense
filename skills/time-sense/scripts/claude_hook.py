#!/usr/bin/env python3
"""Claude Code hook enforcing time-sense rules that agents skip in practice.

One script handles PreToolUse / PostToolUse / PostToolUseFailure; register it
for matchers `Bash`, `Agent|Task` and `Edit|Write|MultiEdit|NotebookEdit`.

- Bash with timeout > LONG_TIMEOUT_MS and no `tb wrap` -> deny: the agent
  expects a long run, so it must supply its own estimate via `tb wrap --est`.
- Bash that repeats the expensive command of the previous call (which took
  >= SLOW_S) with nothing changed in between -> deny: reuse the result.
  Escape hatch: append RERUN_MARK to the command.
- Bash that ran >= SLOW_S without `tb wrap` -> reminder in Claude's context.
- Agent/Task dispatched in the foreground or without a recent active
  `tb start --kind subagent` timer -> deny.

Standard library only; Python >= 3.9. Session state lives in
$TIME_SENSE_HOME/claude-sessions/<session_id>.json.
"""

import importlib.util
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TB_PATH = os.path.join(HERE, "tb.py")

LONG_TIMEOUT_MS = 60000
SLOW_S = 30.0
TIMER_FRESH_S = 600
RERUN_MARK = "# time-sense: rerun"
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
AGENT_TOOLS = ("Agent", "Task")
# Commands too cheap to count as "the expensive part" of a repeated call.
CHEAP = {
    "echo", "printf", "cd", "pwd", "true", "false", "ls", "cat", "head", "tail",
    "wc", "grep", "sort", "uniq", "test", "[", "export", "set", "sleep", "date",
}

_WRAP_RE = re.compile(r"tb\.py\s+wrap\b.*?\s--\s+", re.S)
_REDIR_RE = re.compile(r"\d*>>?&?\s*\S+|<\s*\S+")


def _load_tb():
    spec = importlib.util.spec_from_file_location("tb", TB_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tb = _load_tb()
TB_CMD = "python3 " + TB_PATH


def is_wrapped(cmd):
    return bool(_WRAP_RE.search(cmd))


def producers(cmd):
    """Normalized first command of every pipeline in cmd, minus cheap ones."""
    m = _WRAP_RE.search(cmd)
    if m:
        cmd = cmd[m.end():]
    out = set()
    for seq in re.split(r"&&|\|\||;|\n", cmd):
        first = seq.split("|", 1)[0]
        first = " ".join(_REDIR_RE.sub(" ", first).split())
        if first and first.split()[0] not in CHEAP and not first.startswith("#"):
            out.add(first)
    return out


# --- session state ---------------------------------------------------------


def _state_path(session_id):
    d = os.path.join(tb.home(), "claude-sessions")
    os.makedirs(d, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown")
    return os.path.join(d, safe + ".json")


def load_state(session_id):
    try:
        with open(_state_path(session_id)) as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return {}


def save_state(session_id, state):
    with open(_state_path(session_id), "w") as fh:
        json.dump(state, fh)


# --- decisions -------------------------------------------------------------


def deny(reason):
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "time-sense: " + reason,
        }
    }


def context(event, text):
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": "time-sense: " + text}}


def pre_bash(inp, state):
    tool_input = inp.get("tool_input") or {}
    cmd = tool_input.get("command") or ""
    if "tb.py" in cmd and not is_wrapped(cmd):
        return None  # tb bookkeeping (est/start/check/stop/calib)

    last = state.get("last_slow")
    if last and RERUN_MARK not in cmd:
        repeated = producers(cmd) & set(last["producers"])
        if repeated:
            return deny(
                "`%s` already ran %ds ago in the previous call and took %ds; nothing "
                "has changed since. Reuse that result instead of paying for it again "
                "(capture output and exit code to a log the first time). If its inputs "
                "really changed, append `%s` to the command."
                % (sorted(repeated)[0], time.time() - last["at"], last["duration_s"], RERUN_MARK)
            )

    timeout = tool_input.get("timeout") or 0
    if timeout > LONG_TIMEOUT_MS and not is_wrapped(cmd) and not tool_input.get("run_in_background"):
        return deny(
            "you set timeout=%ds, so you expect this to run long. Estimate it and "
            "resend as `%s wrap --est <your estimate> -- <cmd>` with timeout above "
            "3x the estimate (tb's hard deadline). If you expect <30s, resend "
            "without the long timeout." % (timeout // 1000, TB_CMD)
        )
    if is_wrapped(cmd) and inp.get("agent_id"):
        return check_nested_budget(cmd)
    return None


_WRAP_OPTS_RE = re.compile(r"tb\.py\s+wrap\b(.*?)\s--\s", re.S)


def check_nested_budget(cmd):
    """A subagent's `tb wrap` hard deadline must fit its own remaining budget.

    The budget is the newest active `--kind subagent` timer (the parent starts
    it right before dispatch); without one there is nothing to check.
    """
    opts = _WRAP_OPTS_RE.search(cmd).group(1)
    est = re.search(r"--est[ =](\S+)", opts)
    kind = re.search(r"--kind[ =](\S+)", opts)
    kind = kind.group(1) if kind else "action"
    if not est or kind not in tb.KINDS:
        return None  # let tb itself report the usage error
    try:
        est_s = tb.parse_duration(est.group(1))
    except tb.TbError:
        return None
    with tb.locked():
        active = tb.load_active()
    subs = [v for v in active.values() if v.get("kind") == "subagent"]
    if not subs:
        return None
    budget = max(subs, key=lambda v: v["start"])
    remaining = budget["est_s"] - (time.time() - budget["start"])
    factor = tb.factor(kind)[0]
    hard = est_s * factor * tb.HARD_MULT
    if hard <= remaining:
        return None
    max_est = max(remaining, 0) / (factor * tb.HARD_MULT)
    return deny(
        "`tb wrap --est %s` has a hard deadline of %s, but only %s remain of the "
        "subagent budget `%s`. Use --est <= %s, or stop and return partial "
        "results with status." % (
            est.group(1), tb.fmt(hard), tb.fmt(max(remaining, 0)), budget["id"], tb.fmt(max_est),
        )
    )


def pre_agent(inp):
    tool_input = inp.get("tool_input") or {}
    if not tool_input.get("run_in_background"):
        return deny(
            "dispatch subagents with run_in_background: true so you can watch them "
            "with `tb check` instead of blocking until they return."
        )
    with tb.locked():
        active = tb.load_active()
    now = time.time()
    fresh = [
        v for v in active.values()
        if v.get("kind") == "subagent" and now - v.get("start", 0) <= TIMER_FRESH_S
    ]
    if not fresh:
        return deny(
            "start a watchdog timer first: `%s start <id> --est <dur> --kind subagent`, "
            "and put the time budget in the subagent prompt." % TB_CMD
        )
    return None


def post_bash(inp, state, event):
    cmd = (inp.get("tool_input") or {}).get("command") or ""
    duration_s = (inp.get("duration_ms") or 0) / 1000.0
    state.pop("last_slow", None)
    out = None
    if duration_s >= SLOW_S:
        state["last_slow"] = {
            "producers": sorted(producers(cmd)),
            "duration_s": int(duration_s),
            "at": time.time(),
        }
        if not is_wrapped(cmd):
            out = context(
                event,
                "that command took %ds without tb wrap: no deadline and no "
                "calibration record. Run commands like it as `%s wrap --est <dur> -- <cmd>`."
                % (duration_s, TB_CMD),
            )
    return out


def handle(inp):
    event = inp.get("hook_event_name")
    tool = inp.get("tool_name")
    session_id = inp.get("session_id") or "unknown"
    if event == "PreToolUse" and tool in AGENT_TOOLS:
        return pre_agent(inp)
    if tool == "Bash":
        state = load_state(session_id)
        if event == "PreToolUse":
            return pre_bash(inp, state)
        if event in ("PostToolUse", "PostToolUseFailure"):
            out = post_bash(inp, state, event)
            save_state(session_id, state)
            return out
    if tool in EDIT_TOOLS and event in ("PostToolUse", "PostToolUseFailure"):
        state = load_state(session_id)
        if state.pop("last_slow", None) is not None:
            save_state(session_id, state)
    return None


def main():
    try:
        inp = json.load(sys.stdin)
    except ValueError:
        return 0  # not our problem; never block Claude on a malformed event
    out = handle(inp)
    if out is not None:
        json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
