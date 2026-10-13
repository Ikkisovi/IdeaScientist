"""Offline regression checks: no providers or corpus queries."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ideascientist.harness import runner
from ideascientist.harness.completion import complete, recover, verdicts


class Client:
    actions = []

    def __init__(self, **kwargs):
        self.model = "test"
        self.last_prompt_tokens = 0
        self.actions = list(type(self).actions)

    def chat(self, *args, **kwargs):
        msg = self.actions.pop(0) if self.actions else {"content": "done"}
        return {"choices": [{"message": msg}]}

    def set_step(self, step):
        pass

    def summary(self):
        return {"total_tokens": 0, "total_calls": 0}

    def close(self):
        pass


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        Client.actions = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_harness(self, subagent=None):
        with patch.object(runner, "AgenticLLMClient", Client), \
             patch.object(runner, "context_window_for", return_value=128000), \
             patch.object(runner, "_run_subagent", side_effect=subagent):
            return asyncio.run(runner.run_ideation("test problem", self.root,
                                                  model="test", max_turns=3,
                                                  finalization_turns=1))

    def test_budget_always_delivers_report(self):
        result = self.run_harness()
        self.assertEqual(result["completion"]["reason"], "exploration_budget")
        self.assertEqual(result["completion"]["status"], "no_surviving_candidate")
        self.assertTrue((self.root / "outputs/report.md").is_file())
        self.assertFalse((self.root / "outputs/report.json").exists())

    def test_latest_verdict_wins(self):
        docs = self.root / "outputs"
        docs.mkdir()
        (docs / "scores.md").write_text("### C1 verdict\n- **Verdict**: survive\n"
                                        "### C1 verdict\n- **Verdict**: revise(focus=novelty)\n")
        self.assertEqual(verdicts(docs), {"C1": "revise"})

    def test_writer_failure_preserves_evidence(self):
        Client.actions = [{"tool_calls": [{"id": "a", "type": "function", "function": {
            "name": "spawn_subagent", "arguments": '{"role":"innovator","task":"test"}'}}]}]
        calls = []

        def subagent(role, task, ctx, *args, **kwargs):
            calls.append((role, kwargs))
            if role == "report_writer":
                raise TimeoutError("test timeout")
            (ctx.docs_dir / "candidates.md").write_text("### C1 — test idea\nEvidence preserved.")
            (ctx.docs_dir / "scores.md").write_text("### C1 verdict\n- **Verdict**: survive\n")
            return {"digest": "done", "tokens": 0, "calls": 0}

        result = self.run_harness(subagent)
        self.assertEqual(result["completion"]["status"], "writer_incomplete")
        self.assertIn("TimeoutError", result["completion"]["finalizer_error"])
        self.assertEqual(calls[-1], ("report_writer", {"hard_turn_cap": 1}))
        self.assertIn("Evidence preserved", (self.root / "outputs/report.md").read_text())

    def test_existing_report_is_preserved(self):
        docs = self.root / "outputs"
        docs.mkdir()
        (docs / "report.md").write_text("original report")
        receipt = complete(self.root, "test")
        self.assertEqual((docs / "report.md").read_text(), "original report")
        self.assertEqual(receipt["report_file"], "completion_report.md")

    def test_complete_proposal_is_rendered_without_another_writer(self):
        from ideascientist.rewards.report_writer.parser import REPORT_FIELDS
        docs = self.root / "outputs"
        docs.mkdir()
        rep = {name: "test" for name in REPORT_FIELDS}
        (docs / "report.json").write_text(json.dumps(rep))
        with patch("ideascientist.harness.completion.render_proposal", return_value="# Test proposal\n"):
            result = self.run_harness()
        self.assertEqual(result["completion"]["status"], "proposal_unvalidated")
        self.assertIn("# Test proposal", (docs / "report.md").read_text())

    def test_broken_report_shape_still_delivers_evidence(self):
        from ideascientist.rewards.report_writer.parser import REPORT_FIELDS
        docs = self.root / "outputs"
        docs.mkdir()
        (docs / "report.json").write_text(json.dumps({name: "test" for name in REPORT_FIELDS}))
        with patch("ideascientist.harness.completion.render_proposal", side_effect=ValueError("bad shape")):
            result = complete(self.root, "test")
        self.assertIn("bad shape", result["finalizer_error"])
        self.assertTrue((docs / "report.md").is_file())

    def test_invalid_json_is_preserved_and_does_not_pass(self):
        docs = self.root / "outputs"
        docs.mkdir()
        (docs / "report.json").write_text("{}")
        receipt = complete(self.root, "test")
        self.assertEqual(receipt["status"], "no_surviving_candidate")
        self.assertEqual((docs / "report.json").read_text(), "{}")

    def test_crash_still_delivers_and_propagates(self):
        with patch.object(runner, "AgenticLLMClient", Client), \
             patch.object(Client, "chat", side_effect=RuntimeError("test crash")), \
             patch.object(runner, "context_window_for", return_value=128000):
            with self.assertRaisesRegex(RuntimeError, "test crash"):
                asyncio.run(runner.run_ideation("test", self.root, model="test"))
        receipt = json.loads((self.root / "outputs/completion.json").read_text())
        self.assertEqual(receipt["reason"], "orchestrator_error")
        self.assertTrue((self.root / "outputs/report.md").is_file())

    def test_recovery_waits_for_active_owner_and_is_idempotent(self):
        run = self.root / "runs_spark/test_q1"
        (run / "outputs").mkdir(parents=True)
        (run / "outputs/problem.md").write_text("test")
        with patch("ideascientist.harness.completion.active_runs", return_value={run.resolve()}):
            results, active = recover(self.root)
            self.assertEqual(results, [])
            self.assertTrue(active)
            self.assertFalse((run / "outputs/report.md").exists())
        with patch("ideascientist.harness.completion.active_runs", return_value=set()):
            self.assertEqual(len(recover(self.root)[0]), 1)
            self.assertEqual(recover(self.root)[0], [])

    def test_role_override_cannot_expand_finalization_budget(self):
        from ideascientist.harness import tools as T
        from ideascientist.harness.runlog import RunLogger
        docs = self.root / "outputs"
        docs.mkdir()
        log = RunLogger(self.root / "logs")
        ctx = T.ToolContext(run_dir=self.root, docs_dir=docs, query_text="test", log=log)
        with patch.object(runner, "AgenticLLMClient", Client), \
             patch.object(runner, "_role_env_int_map", return_value={"report_writer": 999}), \
             patch.object(runner, "_tool_loop", return_value=("done", 0)) as loop:
            runner._run_subagent("report_writer", "test", ctx, "test", log,
                                 "test", "test#1", 40, hard_turn_cap=2)
            self.assertEqual(loop.call_args.args[6], 2)
        log.close()


if __name__ == "__main__":
    unittest.main()
