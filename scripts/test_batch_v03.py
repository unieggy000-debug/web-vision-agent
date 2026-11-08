"""Offline regression tests for batch boundaries and Trace; no API calls."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.batch import run_batch, validate_tasks
from reports import trace


class BatchV03Tests(unittest.TestCase):
    def test_validation_rejects_duplicate_ids(self):
        tasks = [{"task_id": "a", "goal": "research A"},
                 {"task_id": "a", "goal": "research B"}]
        with self.assertRaises(ValueError):
            validate_tasks(tasks)

    def test_validation_rejects_unbounded_batch_and_unsafe_url(self):
        with self.assertRaises(ValueError):
            validate_tasks([{"goal": "go"}] * 101)
        with self.assertRaises(ValueError):
            validate_tasks([{"goal": "go", "target_url": "file:///etc/passwd"}])

    def test_dry_run_never_calls_subprocess(self):
        with patch("agent.batch.subprocess.run") as mock:
            output = run_batch([{"task_id": "a", "goal": "research example.com"}])
            self.assertEqual(output["mode"], "dry_run")
            mock.assert_not_called()

    def test_live_requires_isolated_file(self):
        with self.assertRaises(ValueError):
            run_batch([{"goal": "research example.com"}], execute=True, env_file=None)

    def test_trace_isolated_by_run_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(trace, "TRACE_DIR", Path(tmp)):
                a = trace.TraceWriter("run_a", task_id="a", batch_id="batch1")
                b = trace.TraceWriter("run_b", task_id="b", batch_id="batch1")
                with a.span("tool", "open", 1) as span:
                    span.add(ok=True)
                with b.span("llm", "decision", 1) as span:
                    span.add(prompt_tokens=3, completion_tokens=4, total_tokens=7)
                a.finish("finished", 1, 1)
                rows_a = [json.loads(x) for x in a.path.read_text(encoding="utf-8").splitlines()]
                rows_b = [json.loads(x) for x in b.path.read_text(encoding="utf-8").splitlines()]
                self.assertTrue(all(x["task_id"] == "a" for x in rows_a))
                self.assertTrue(all(x["task_id"] == "b" for x in rows_b))
                self.assertEqual(rows_b[1]["total_tokens"], 7)


if __name__ == "__main__":
    unittest.main()
