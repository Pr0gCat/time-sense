#!/usr/bin/env python3
"""tb - time budget CLI for coding agents.

Estimate durations with a calibration factor learned from your own history,
track active timers (actions, subagents, steps, tasks), flag soft/hard
deadline overruns, and wrap commands with an enforced hard deadline.

Standard library only; Python >= 3.9.
State lives in $TIME_SENSE_HOME (default ~/.time-sense):
  ledger.jsonl  append-only records of finished timers
  active.json   id -> running timer
"""

import argparse
import contextlib
import json
import os
import re
import signal
import statistics
import subprocess
import sys
import tempfile
import time

try:
    import fcntl
except ImportError:  # Windows: locking becomes a no-op
    fcntl = None

SOFT_MULT = 1.5
HARD_MULT = 3.0
MIN_SAMPLES = 3
WINDOW = 20
CLAMP = (0.25, 4.0)
STALE_S = 86400

KINDS = ("action", "subagent", "step", "task")
OUTCOMES = ("done", "failed", "abandoned")
CALIBRATING_OUTCOMES = ("done", "failed")

EXIT_OK = 0
EXIT_SOFT = 10
EXIT_HARD = 20
EXIT_USAGE = 2
EXIT_KILLED = 124

POLL_S = 0.5
KILL_GRACE_S = 5.0

_DURATION_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")


class TbError(Exception):
    """User-facing error: printed as `tb: <msg>` to stderr, exit 2."""


def say(msg, stream=None):
    print("tb: " + msg, file=stream or sys.stdout, flush=True)


def now():
    override = os.environ.get("TB_NOW")
    if override is not None:
        return float(override)
    return time.time()


def parse_duration(text):
    if text.isdigit():
        seconds = int(text)
    else:
        m = _DURATION_RE.match(text)
        if not m or not any(m.groups()):
            raise TbError("bad duration: " + text)
        h, mi, s = (int(g) if g else 0 for g in m.groups())
        seconds = h * 3600 + mi * 60 + s
    if seconds <= 0:
        raise TbError("bad duration: " + text)
    return float(seconds)


def fmt(seconds):
    total = int(round(seconds))
    if total < 60:
        return "%ds" % total
    if total < 3600:
        return "%dm%02ds" % (total // 60, total % 60)
    return "%dh%02dm" % (total // 3600, (total % 3600) // 60)


# --- state -----------------------------------------------------------------


def home():
    path = os.environ.get("TIME_SENSE_HOME") or os.path.join(
        os.path.expanduser("~"), ".time-sense"
    )
    os.makedirs(path, exist_ok=True)
    return path


@contextlib.contextmanager
def locked():
    lock_path = os.path.join(home(), ".lock")
    with open(lock_path, "a") as fh:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _active_path():
    return os.path.join(home(), "active.json")


def _ledger_path():
    return os.path.join(home(), "ledger.jsonl")


def load_active():
    try:
        with open(_active_path()) as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except ValueError:
        raise TbError("corrupt active.json: " + _active_path())
    return data if isinstance(data, dict) else {}


def save_active(active):
    directory = home()
    fd, tmp = tempfile.mkstemp(prefix=".active.", dir=directory)
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(active, fh, indent=1, sort_keys=True)
        os.replace(tmp, _active_path())
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def append_ledger(record):
    with open(_ledger_path(), "a") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def read_ledger():
    try:
        with open(_ledger_path()) as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return []
    records = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue  # tolerate a torn line; never block on history
    return records


# --- calibration -----------------------------------------------------------


def ratios(kind):
    """actual/est ratios of the most recent WINDOW calibrating records."""
    out = []
    for rec in read_ledger():
        if rec.get("kind") != kind or rec.get("outcome") not in CALIBRATING_OUTCOMES:
            continue
        est = rec.get("est_s") or 0
        actual = rec.get("actual_s")
        if est > 0 and actual is not None:
            out.append(float(actual) / float(est))
    return out[-WINDOW:]


def factor(kind):
    """(factor, n, median_ratio_or_None) for a kind."""
    rs = ratios(kind)
    if len(rs) < MIN_SAMPLES:
        return 1.0, len(rs), (statistics.median(rs) if rs else None)
    med = statistics.median(rs)
    return min(max(med, CLAMP[0]), CLAMP[1]), len(rs), med


def estimate(est_s, kind):
    f, n, _ = factor(kind)
    cal_s = est_s * f
    tag = "n=%d %s" % (n, kind)
    if n < MIN_SAMPLES:
        tag += ", uncalibrated"
    line = "est %s x%.2f (%s) -> %s; soft %s; hard %s" % (
        fmt(est_s),
        f,
        tag,
        fmt(cal_s),
        fmt(cal_s * SOFT_MULT),
        fmt(cal_s * HARD_MULT),
    )
    return cal_s, line


def status_of(elapsed, cal_s):
    if elapsed > cal_s * HARD_MULT:
        return "HARD"
    if elapsed > cal_s * SOFT_MULT:
        return "SOFT"
    return "OK"


def finish(active, timer_id, outcome, end):
    """Remove timer from active (caller holds lock and saves) and record it."""
    timer = active.pop(timer_id)
    actual = max(0.0, end - timer["start"])
    record = {
        "id": timer_id,
        "kind": timer["kind"],
        "est_s": timer["est_s"],
        "cal_s": timer["cal_s"],
        "actual_s": round(actual, 1),
        "outcome": outcome,
        "start": timer["start"],
        "end": end,
        "note": timer.get("note"),
    }
    append_ledger(record)
    return "%s %s in %s (est %s, ratio %.2f)" % (
        timer_id,
        outcome,
        fmt(actual),
        fmt(timer["est_s"]),
        actual / timer["est_s"],
    )


def register(timer_id, est_s, kind, note, extra=None):
    """Add an active timer; returns (cal_s, estimate line, start)."""
    with locked():
        active = load_active()
        if timer_id in active:
            raise TbError("already active: " + timer_id)
        cal_s, line = estimate(est_s, kind)
        start = now()
        active[timer_id] = {
            "id": timer_id,
            "kind": kind,
            "est_s": est_s,
            "cal_s": cal_s,
            "start": start,
            "note": note,
        }
        active[timer_id].update(extra or {})
        save_active(active)
    return cal_s, line, start


# --- commands --------------------------------------------------------------


def cmd_est(args):
    _, line = estimate(parse_duration(args.dur), args.kind)
    say(line)
    return EXIT_OK


def cmd_start(args):
    est_s = parse_duration(args.est)
    _, line, _ = register(args.id, est_s, args.kind, args.note)
    say(line)
    say("started " + args.id)
    return EXIT_OK


def cmd_check(args):
    t = now()
    reaped = []
    with locked():
        active = load_active()
        stale = [k for k, v in active.items() if t - v["start"] > STALE_S]
        for k in stale:
            del active[k]
        # A wrap whose tb process died (e.g. SIGKILL from a harness) can never
        # clean up after itself: kill its orphaned command and record it.
        for k, v in list(active.items()):
            if "pid" in v and not _alive(v["pid"]):
                if v.get("child_pgid") and hasattr(os, "killpg"):
                    with contextlib.suppress(ProcessLookupError, PermissionError):
                        os.killpg(v["child_pgid"], signal.SIGKILL)
                reaped.append(finish(active, k, "abandoned", t))
        if stale or reaped:
            save_active(active)
    for k in stale:
        say("dropped stale " + k)
    for msg in reaped:
        say("reaped dead wrap: " + msg)
    if args.id is not None:
        if args.id not in active:
            raise TbError("no active timer: " + args.id)
        timers = [active[args.id]]
    else:
        timers = sorted(active.values(), key=lambda v: v["start"])
    if not timers:
        say("no active timers")
        return EXIT_OK
    worst = EXIT_OK
    for v in timers:
        elapsed = max(0.0, t - v["start"])
        st = status_of(elapsed, v["cal_s"])
        worst = max(worst, {"OK": EXIT_OK, "SOFT": EXIT_SOFT, "HARD": EXIT_HARD}[st])
        say(
            "%s [%s] elapsed %s / cal %s -> %s"
            % (v["id"], v["kind"], fmt(elapsed), fmt(v["cal_s"]), st)
        )
    return worst


def cmd_stop(args):
    with locked():
        active = load_active()
        if args.id not in active:
            raise TbError("no active timer: " + args.id)
        msg = finish(active, args.id, args.outcome, now())
        save_active(active)
    say(msg)
    return EXIT_OK


def cmd_calib(args):
    kinds = [args.kind] if args.kind else list(KINDS)
    print("%-9s %3s  %12s  %6s" % ("kind", "n", "median_ratio", "factor"))
    for k in kinds:
        f, n, med = factor(k)
        print(
            "%-9s %3d  %12s  %6.2f"
            % (k, n, "-" if med is None else "%.2f" % med, f)
        )
    return EXIT_OK


def _signal_tree(proc, sig):
    try:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, sig)
        else:
            proc.send_signal(sig)
    except (ProcessLookupError, PermissionError):
        pass


class _Interrupted(Exception):
    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


def _raise_interrupted(signum, _frame):
    raise _Interrupted(signum)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate(proc):
    _signal_tree(proc, signal.SIGTERM)
    try:
        proc.wait(timeout=KILL_GRACE_S)
    except subprocess.TimeoutExpired:
        _signal_tree(proc, getattr(signal, "SIGKILL", signal.SIGTERM))
        proc.wait()


def cmd_wrap(args):
    if not args.cmd:
        raise TbError("wrap needs a command after --")
    est_s = parse_duration(args.est)
    timer_id = args.id or "wrap-%d-%d" % (int(time.time()), os.getpid())
    cal_s, line, start = register(
        timer_id, est_s, args.kind, " ".join(args.cmd), {"pid": os.getpid()}
    )
    # A harness killing tb with SIGTERM/SIGHUP must still kill the command
    # tree and record the run; only SIGKILL escapes (see check's reaping).
    for name in ("SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _raise_interrupted)
    say(line, sys.stderr)
    say("started " + timer_id, sys.stderr)

    outcome = None
    rc = EXIT_OK
    try:
        try:
            # Own process group so a hard kill reaches the whole command tree.
            proc = subprocess.Popen(args.cmd, start_new_session=hasattr(os, "killpg"))
        except OSError as exc:
            raise TbError("cannot run %s: %s" % (args.cmd[0], exc.strerror or exc))
        with locked():
            active = load_active()
            if timer_id in active:
                active[timer_id]["child_pgid"] = proc.pid
                save_active(active)
        soft_s = cal_s * SOFT_MULT
        hard_s = cal_s * HARD_MULT
        warned = False
        try:
            while True:
                try:
                    proc_rc = proc.wait(timeout=POLL_S)
                    outcome = "done" if proc_rc == 0 else "failed"
                    rc = proc_rc if proc_rc >= 0 else 128 - proc_rc
                    break
                except subprocess.TimeoutExpired:
                    pass
                elapsed = now() - start
                if not warned and elapsed > soft_s:
                    warned = True
                    say(
                        "SOFT %s elapsed %s > %.1fx cal %s"
                        % (timer_id, fmt(elapsed), SOFT_MULT, fmt(cal_s)),
                        sys.stderr,
                    )
                if not args.no_kill and elapsed >= hard_s:
                    say("HARD %s killed at %s" % (timer_id, fmt(elapsed)), sys.stderr)
                    _terminate(proc)
                    outcome = "abandoned"
                    rc = EXIT_KILLED
                    break
        except KeyboardInterrupt:
            _terminate(proc)
            outcome = "abandoned"
            rc = 130
        except _Interrupted as exc:
            _terminate(proc)
            outcome = "abandoned"
            rc = 128 + exc.signum
    finally:
        with locked():
            active = load_active()
            if timer_id in active:
                msg = finish(active, timer_id, outcome, now()) if outcome else None
                active.pop(timer_id, None)
                save_active(active)
                if msg:
                    say(msg, sys.stderr)
    return rc


# --- entry -----------------------------------------------------------------


def build_parser():
    p = argparse.ArgumentParser(prog="tb", description="Time budget CLI for agents.")
    sub = p.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    def kind_opt(sp, default="action"):
        sp.add_argument("--kind", choices=KINDS, default=default)

    sp = sub.add_parser("est", help="calibrated estimate with soft/hard deadlines")
    sp.add_argument("dur")
    kind_opt(sp)
    sp.set_defaults(func=cmd_est)

    sp = sub.add_parser("start", help="start an active timer")
    sp.add_argument("id")
    sp.add_argument("--est", required=True)
    kind_opt(sp)
    sp.add_argument("--note")
    sp.set_defaults(func=cmd_start)

    sp = sub.add_parser("check", help="report timers; exit 0 OK, 10 SOFT, 20 HARD")
    sp.add_argument("id", nargs="?")
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("stop", help="stop a timer and record its outcome")
    sp.add_argument("id")
    sp.add_argument("--outcome", choices=OUTCOMES, default="done")
    sp.set_defaults(func=cmd_stop)

    sp = sub.add_parser("calib", help="show calibration per kind")
    sp.add_argument("--kind", choices=KINDS)
    sp.set_defaults(func=cmd_calib)

    sp = sub.add_parser("wrap", help="run CMD with soft warning and hard kill: wrap --est D -- CMD...")
    sp.add_argument("--est", required=True)
    kind_opt(sp)
    sp.add_argument("--id")
    sp.add_argument("--no-kill", action="store_true", help="warn at hard deadline, never kill")
    sp.set_defaults(func=cmd_wrap)
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = []
    if "--" in argv:
        i = argv.index("--")
        argv, cmd = argv[:i], argv[i + 1 :]
    args = build_parser().parse_args(argv)
    args.cmd = cmd
    try:
        return args.func(args)
    except TbError as exc:
        say(str(exc), sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
