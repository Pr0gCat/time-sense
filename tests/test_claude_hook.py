import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "skills", "time-sense", "scripts", "claude_hook.py")
TB = os.path.join(ROOT, "skills", "time-sense", "scripts", "tb.py")
WRAP = "python3 %s wrap --est 70s -- " % TB


class HookTestCase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        self.env = dict(os.environ, TIME_SENSE_HOME=self.home)
        self.env.pop("TB_NOW", None)

    def hook(self, event, tool, tool_input, **extra):
        payload = dict(
            hook_event_name=event, tool_name=tool, tool_input=tool_input, session_id="s1", **extra
        )
        r = subprocess.run(
            [sys.executable, HOOK], input=json.dumps(payload), env=self.env,
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def pre(self, command, **tool_input):
        return self.hook("PreToolUse", "Bash", dict(command=command, **tool_input))

    def post(self, command, seconds, event="PostToolUse"):
        return self.hook(event, "Bash", {"command": command}, duration_ms=int(seconds * 1000))

    def assertDenied(self, out, fragment):
        self.assertIsNotNone(out)
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn(fragment, out["permissionDecisionReason"])


class LongTimeoutTest(HookTestCase):
    def test_long_timeout_unwrapped_denied(self):
        self.assertDenied(self.pre("./migrate.sh", timeout=240000), "wrap --est")

    def test_wrapped_allowed(self):
        self.assertIsNone(self.pre(WRAP + "./migrate.sh", timeout=600000))

    def test_short_or_default_timeout_allowed(self):
        self.assertIsNone(self.pre("./migrate.sh", timeout=60000))
        self.assertIsNone(self.pre("./migrate.sh"))

    def test_background_allowed(self):
        self.assertIsNone(self.pre("./migrate.sh", timeout=600000, run_in_background=True))


class SlowReminderTest(HookTestCase):
    def test_slow_unwrapped_gets_reminder(self):
        out = self.post("./test.sh", 61)
        self.assertIn("took 61s without tb wrap", out["additionalContext"])

    def test_slow_failure_gets_reminder(self):
        out = self.post("./test.sh", 45, event="PostToolUseFailure")
        self.assertEqual(out["hookEventName"], "PostToolUseFailure")

    def test_fast_or_wrapped_silent(self):
        self.assertIsNone(self.post("./test.sh", 29))
        self.assertIsNone(self.post(WRAP + "./test.sh", 61))


class RerunTest(HookTestCase):
    FIRST = "sed -i '' 's/a/b/' pkg/*.py && ./test.sh 2>&1 | grep -v '^ok'; echo exit=$?"
    AGAIN = "./test.sh >/tmp/out.txt 2>&1; echo exit=$?"

    def test_immediate_rerun_denied(self):
        self.post(self.FIRST, 61)
        self.assertDenied(self.pre(self.AGAIN), "`./test.sh` already ran")

    def test_rerun_of_wrapped_command_denied(self):
        self.post(WRAP + "./test.sh 2>&1 | tail -5", 61)
        self.assertDenied(self.pre(self.AGAIN), "`./test.sh` already ran")

    def test_marker_allows_rerun(self):
        self.post(self.FIRST, 61)
        self.assertIsNone(self.pre(self.AGAIN + " # time-sense: rerun"))

    def test_edit_in_between_allows_rerun(self):
        self.post(self.FIRST, 61)
        self.hook("PostToolUse", "Edit", {"file_path": "pkg/mod00.py"})
        self.assertIsNone(self.pre(self.AGAIN))

    def test_other_command_in_between_allows_rerun(self):
        self.post(self.FIRST, 61)
        self.post("python3 fix.py", 1)
        self.assertIsNone(self.pre(self.AGAIN))

    def test_fast_previous_call_allows_rerun(self):
        self.post(self.FIRST, 10)
        self.assertIsNone(self.pre(self.AGAIN))

    def test_only_cheap_overlap_allowed(self):
        self.post(self.FIRST, 61)
        self.assertIsNone(self.pre("cat /tmp/out.txt; echo exit=$?"))

    def test_tb_bookkeeping_never_denied(self):
        self.post(self.FIRST, 61)
        self.assertIsNone(self.pre("python3 %s check" % TB))


class AgentTest(HookTestCase):
    def agent(self, **tool_input):
        return self.hook("PreToolUse", "Agent", dict(prompt="do it", **tool_input))

    def test_foreground_denied(self):
        self.assertDenied(self.agent(), "run_in_background: true")

    def test_background_without_timer_denied(self):
        self.assertDenied(self.agent(run_in_background=True), "--kind subagent")

    def test_action_timer_does_not_count(self):
        subprocess.run([sys.executable, TB, "start", "x", "--est", "1m"], env=self.env, check=True,
                       capture_output=True)
        self.assertDenied(self.agent(run_in_background=True), "--kind subagent")

    def test_background_with_timer_allowed(self):
        subprocess.run([sys.executable, TB, "start", "sub", "--est", "3m", "--kind", "subagent"],
                       env=self.env, check=True, capture_output=True)
        self.assertIsNone(self.agent(run_in_background=True))


class NestedBudgetTest(HookTestCase):
    def setUp(self):
        super().setUp()
        subprocess.run([sys.executable, TB, "start", "audit-agent", "--est", "5m", "--kind", "subagent"],
                       env=self.env, check=True, capture_output=True)

    def sub_pre(self, command):
        return self.hook("PreToolUse", "Bash", {"command": command}, agent_id="a1", agent_type="general-purpose")

    def test_hard_deadline_over_budget_denied(self):
        # observed failure: --est 2m -> hard 6m inside a 5m budget
        out = self.sub_pre("python3 %s wrap --est 2m -- ./audit.sh" % TB)
        self.assertDenied(out, "hard deadline of 6m00s")
        self.assertIn("--est <= 1m40s", out["permissionDecisionReason"])

    def test_fitting_estimate_allowed(self):
        self.assertIsNone(self.sub_pre("python3 %s wrap --est 90s -- ./audit.sh" % TB))

    def test_main_agent_not_checked(self):
        self.assertIsNone(self.pre("python3 %s wrap --est 2m -- ./audit.sh" % TB))


if __name__ == "__main__":
    unittest.main()
