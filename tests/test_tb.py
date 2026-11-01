import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(ROOT, "skills", "time-sense", "scripts", "tb.py")


class TbTestCase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)

    def tb(self, *args, now=None, timeout=30):
        env = dict(os.environ, TIME_SENSE_HOME=self.home)
        env.pop("TB_NOW", None)
        if now is not None:
            env["TB_NOW"] = str(now)
        return subprocess.run(
            [sys.executable, TB] + list(args),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def record(self, timer_id, est_s, actual_s, outcome="done", kind="action"):
        r = self.tb("start", timer_id, "--est", str(est_s), "--kind", kind, now=0)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.tb("stop", timer_id, "--outcome", outcome, now=actual_s)
        self.assertEqual(r.returncode, 0, r.stderr)

    def ledger(self):
        with open(os.path.join(self.home, "ledger.jsonl")) as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def active(self):
        path = os.path.join(self.home, "active.json")
        if not os.path.exists(path):
            return {}
        with open(path) as fh:
            return json.load(fh)


class DurationTest(TbTestCase):
    def test_accepted_forms(self):
        for arg, shown in (("90", "1m30s"), ("90s", "1m30s"), ("1h30m", "1h30m"), ("5m", "5m00s")):
            r = self.tb("est", arg)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(r.stdout.startswith("tb: est %s " % shown), r.stdout)

    def test_rejected_forms(self):
        for arg in ("0", "5x", "", "0m", "1m1h"):
            r = self.tb("est", arg)
            self.assertEqual(r.returncode, 2, arg)
            self.assertIn("tb: bad duration: %s" % arg, r.stderr)


class CalibrationTest(TbTestCase):
    def test_uncalibrated_below_min_samples(self):
        self.record("a", 100, 50)
        self.record("b", 100, 50)
        r = self.tb("est", "100")
        self.assertIn("x1.00 (n=2 action, uncalibrated)", r.stdout)

    def test_median_ratio(self):
        for i, ratio in enumerate((0.5, 0.5, 0.5, 2, 2)):
            self.record("r%d" % i, 100, 100 * ratio)
        r = self.tb("est", "100")
        self.assertIn("x0.50 (n=5 action) -> 50s; soft 1m15s; hard 2m30s", r.stdout)

    def test_abandoned_excluded(self):
        self.record("a", 100, 50)
        self.record("b", 100, 50)
        self.record("c", 100, 10, outcome="abandoned")
        r = self.tb("est", "100")
        self.assertIn("(n=2 action, uncalibrated)", r.stdout)

    def test_failed_counts(self):
        self.record("a", 100, 200)
        self.record("b", 100, 200, outcome="failed")
        self.record("c", 100, 200)
        r = self.tb("est", "100")
        self.assertIn("x2.00 (n=3 action)", r.stdout)

    def test_factor_clamped(self):
        for i in range(3):
            self.record("r%d" % i, 10, 100)
        r = self.tb("est", "10")
        self.assertIn("x4.00 (n=3 action)", r.stdout)

    def test_kinds_are_separate(self):
        for i in range(3):
            self.record("s%d" % i, 100, 50, kind="subagent")
        self.assertIn("x0.50 (n=3 subagent)", self.tb("est", "100", "--kind", "subagent").stdout)
        self.assertIn("x1.00 (n=0 action, uncalibrated)", self.tb("est", "100").stdout)


class CheckTest(TbTestCase):
    def setUp(self):
        super().setUp()
        r = self.tb("start", "t", "--est", "100s", now=0)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_ok(self):
        r = self.tb("check", now=140)
        self.assertEqual(r.returncode, 0)
        self.assertIn("t [action] elapsed 2m20s / cal 1m40s -> OK", r.stdout)

    def test_soft(self):
        r = self.tb("check", now=160)
        self.assertEqual(r.returncode, 10)
        self.assertIn("-> SOFT", r.stdout)

    def test_hard(self):
        r = self.tb("check", "t", now=310)
        self.assertEqual(r.returncode, 20)
        self.assertIn("-> HARD", r.stdout)

    def test_worst_wins(self):
        self.tb("start", "late", "--est", "10s", now=100)
        r = self.tb("check", now=140)
        self.assertEqual(r.returncode, 20)
        self.assertIn("t [action] elapsed 2m20s / cal 1m40s -> OK", r.stdout)
        self.assertIn("late [action] elapsed 40s / cal 10s -> HARD", r.stdout)

    def test_stale_dropped(self):
        r = self.tb("check", now=86400 + 1)
        self.assertEqual(r.returncode, 0)
        self.assertIn("tb: dropped stale t", r.stdout)
        self.assertIn("tb: no active timers", r.stdout)
        self.assertEqual(self.active(), {})
        self.assertFalse(os.path.exists(os.path.join(self.home, "ledger.jsonl")))

    def test_unknown_id(self):
        r = self.tb("check", "nope", now=1)
        self.assertEqual(r.returncode, 2)
        self.assertIn("tb: no active timer: nope", r.stderr)


class StartStopTest(TbTestCase):
    def test_duplicate_start(self):
        self.assertEqual(self.tb("start", "x", "--est", "1m", now=0).returncode, 0)
        r = self.tb("start", "x", "--est", "1m", now=1)
        self.assertEqual(r.returncode, 2)
        self.assertIn("tb: already active: x", r.stderr)

    def test_stop_unknown(self):
        r = self.tb("stop", "ghost")
        self.assertEqual(r.returncode, 2)
        self.assertIn("tb: no active timer: ghost", r.stderr)

    def test_stop_records(self):
        self.tb("start", "x", "--est", "5m", "--note", "hi", now=0)
        r = self.tb("stop", "x", now=220)
        self.assertIn("tb: x done in 3m40s (est 5m00s, ratio 0.73)", r.stdout)
        (rec,) = self.ledger()
        self.assertEqual((rec["id"], rec["outcome"], rec["actual_s"], rec["note"]), ("x", "done", 220, "hi"))
        self.assertEqual(self.active(), {})


class WrapTest(TbTestCase):
    def test_failure_exit_code_passed_through(self):
        r = self.tb("wrap", "--est", "1s", "--", "sh", "-c", "exit 3")
        self.assertEqual(r.returncode, 3, r.stderr)
        (rec,) = self.ledger()
        self.assertEqual(rec["outcome"], "failed")
        self.assertEqual(self.active(), {})

    def test_success(self):
        r = self.tb("wrap", "--est", "5s", "--id", "ok", "--", "true")
        self.assertEqual(r.returncode, 0, r.stderr)
        (rec,) = self.ledger()
        self.assertEqual((rec["id"], rec["outcome"]), ("ok", "done"))

    def test_hard_deadline_kills(self):
        t0 = time.monotonic()
        r = self.tb("wrap", "--est", "1s", "--", "sleep", "30")
        self.assertLess(time.monotonic() - t0, 10)
        self.assertEqual(r.returncode, 124, r.stderr)
        self.assertIn("tb: SOFT", r.stderr)
        self.assertIn("killed at", r.stderr)
        (rec,) = self.ledger()
        self.assertEqual(rec["outcome"], "abandoned")
        self.assertEqual(self.active(), {})

    def test_kills_whole_tree(self):
        # A surviving grandchild would hold the stdout pipe open and stall run().
        t0 = time.monotonic()
        r = self.tb("wrap", "--est", "1s", "--", "sh", "-c", "sleep 30 & wait")
        self.assertLess(time.monotonic() - t0, 10)
        self.assertEqual(r.returncode, 124, r.stderr)

    def _spawn_wrap(self):
        env = dict(os.environ, TIME_SENSE_HOME=self.home)
        env.pop("TB_NOW", None)
        proc = subprocess.Popen(
            [sys.executable, TB, "wrap", "--est", "10m", "--id", "w", "--", "sleep", "1000"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.addCleanup(proc.kill)
        deadline = time.monotonic() + 10
        while "child_pgid" not in self.active().get("w", {}):
            self.assertLess(time.monotonic(), deadline, "wrap never registered its child")
            time.sleep(0.05)
        return proc, self.active()["w"]["child_pgid"]

    def assertGroupDead(self, pgid):
        deadline = time.monotonic() + 10
        while True:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return
            self.assertLess(time.monotonic(), deadline, "command group still alive")
            time.sleep(0.05)

    def test_sigterm_kills_command_and_records(self):
        proc, pgid = self._spawn_wrap()
        proc.terminate()
        self.assertEqual(proc.wait(timeout=10), 128 + 15)
        self.assertGroupDead(pgid)
        (rec,) = self.ledger()
        self.assertEqual((rec["id"], rec["outcome"]), ("w", "abandoned"))
        self.assertEqual(self.active(), {})

    def test_check_reaps_sigkilled_wrap(self):
        proc, pgid = self._spawn_wrap()
        proc.kill()
        proc.wait(timeout=10)
        r = self.tb("check")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("tb: reaped dead wrap: w abandoned", r.stdout)
        self.assertGroupDead(pgid)
        self.assertEqual(self.active(), {})
        (rec,) = self.ledger()
        self.assertEqual(rec["outcome"], "abandoned")

    def test_needs_command(self):
        r = self.tb("wrap", "--est", "1s")
        self.assertEqual(r.returncode, 2)
        self.assertIn("tb: wrap needs a command after --", r.stderr)


if __name__ == "__main__":
    unittest.main()
