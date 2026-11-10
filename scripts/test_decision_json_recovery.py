"""Offline regression for malformed LLM decision JSON. No external APIs or DB."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent import loop
from reports import trace as trace_module


def fake_response(content, finish_reason="stop"):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=content),
            finish_reason=finish_reason,
        )],
        usage=SimpleNamespace(
            prompt_tokens=101,
            completion_tokens=32,
            total_tokens=133,
        ),
    )


class DecisionJsonRecoveryTests(unittest.TestCase):
    def test_malformed_json_is_not_fabricated_search_memory(self):
        response = fake_response('{"tool": "save_case",', finish_reason="length")
        calls = []
        client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kw: (
                calls.append(kw), response
            )[1]),
        ))
        with patch.object(loop, "_model", return_value="unit-test"):
            result = loop._ask_llm(client, "research website", [], {"format_retry": False})
            self.assertEqual(result["_trace_parse_status"], "invalid_json")
            self.assertNotIn("tool", result)
            self.assertEqual(result["_trace_finish_reason"], "length")
            self.assertEqual(result["_trace_response_chars"], len('{"tool": "save_case",'))
            self.assertEqual(result["_trace_usage"]["total_tokens"], 133)
            self.assertIsInstance(result["_trace_json_error_pos"], int)

            loop._ask_llm(client, "research website", [], {"format_retry": True})
            retry_prompt = calls[-1]["messages"][-1]["content"]
            self.assertIn("FORMAT REPAIR", retry_prompt)

    def test_valid_json_preserves_action(self):
        response = fake_response(json.dumps({
            "tool": "search_memory", "arguments": {"query": "example"}, "thought": "check"
        }))
        client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kw: response)
        ))
        with patch.object(loop, "_model", return_value="unit-test"):
            result = loop._ask_llm(client, "example", [], {})
        self.assertEqual(result["_trace_parse_status"], "ok")
        self.assertEqual(result["tool"], "search_memory")

    def test_invalid_shape_is_not_fabricated_finish(self):
        response = fake_response('{"arguments": {}}')
        client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kw: response)
        ))
        with patch.object(loop, "_model", return_value="unit-test"):
            result = loop._ask_llm(client, "example", [], {})
        self.assertEqual(result["_trace_parse_status"], "invalid_shape")
        self.assertNotIn("tool", result)

    def test_explicit_save_requires_case_persistence(self):
        state = loop.AgentState(
            goal="研究并保存案例。只研究 https://vercel.com/",
            current_goal="研究并保存案例。只研究 https://vercel.com/",
            researched_urls=["https://vercel.com/"],
            history=[
                {"step": 1, "tool": "screenshot", "arguments": {}, "result": {"ok": True}},
                {"step": 2, "tool": "analyze_visual", "arguments": {}, "result": {"ok": True}},
            ],
        )
        validation = loop.validate_finish(state, {"summary": "Research complete"})
        self.assertFalse(validation["valid"])
        self.assertIn("persisted", validation["reason"])

    def test_repeated_bad_json_stops_without_running_tools(self):
        seen_retries = []
        def bad_decision(client, goal, history, progress):
            seen_retries.append(progress["format_retry"])
            return {
                "_trace_parse_status": "invalid_json",
                "_trace_usage": {
                    "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15
                },
                "_trace_response_chars": 25,
                "_trace_finish_reason": "length",
                "_trace_json_error_pos": 21,
            }

        with tempfile.TemporaryDirectory() as directory, (
            patch.object(trace_module, "TRACE_DIR", Path(directory)),
            patch.object(loop, "OpenAI", return_value=object()),
            patch.object(loop, "_api_key", return_value="test-only"),
            patch.object(loop, "_base_url", return_value="https://example.invalid"),
            patch.object(loop, "_model", return_value="unit-test"),
            patch.object(loop, "_ask_llm", side_effect=bad_decision),
            patch.object(loop, "_run_tool") as run_tool,
            patch.object(loop, "_finalize_run"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            state = loop.run_agent("research example.com", task_id="T001", batch_id="B001")

        self.assertEqual(state.stop_status, "invalid_model_response")
        self.assertEqual(state.json_parse_failures, 2)
        self.assertEqual(state.token_usage["total_tokens"], 30)
        self.assertEqual(len(state.history), 0)
        self.assertEqual(seen_retries, [False, True])
        run_tool.assert_not_called()


if __name__ == "__main__":
    unittest.main()
