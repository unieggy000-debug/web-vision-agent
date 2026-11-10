"""Offline orchestration regression tests. No model/search/DB calls."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.intent_router import (
    extract_urls, normalize_url, plan_request, task_manifest, summarize_batch,
)
from agent.orchestrate import orchestrate


class IntentRoutingTests(unittest.TestCase):
    def test_two_urls_become_independent_tasks(self):
        goal = "研究 https://vercel.com/ 和 https://linear.app 并保存案例"
        plan = plan_request(goal)
        self.assertEqual(plan["intent"], "website_research")
        tasks = task_manifest(plan)
        self.assertEqual(len(tasks), 2)
        self.assertEqual([t["task_id"] for t in tasks], ["site_001", "site_002"])
        self.assertTrue(all("保存" in t["goal"] for t in tasks))
        self.assertTrue(all("应用生成" in t["goal"] for t in tasks))

    def test_duplicate_explicit_urls_deduplicated(self):
        plan = plan_request("研究 https://vercel.com/ 和 https://vercel.com")
        self.assertEqual(len(task_manifest(plan)), 1)

    def test_generation_only_is_not_implicitly_supported(self):
        plan = plan_request("帮我生成一个模板应用")
        self.assertEqual(plan["status"], "unsupported")
        self.assertFalse(plan["app_generation_supported"])
        self.assertEqual(task_manifest(plan), [])

    def test_research_then_app_generation_needs_handoff(self):
        plan = plan_request("研究 https://linear.app 然后生成模板应用")
        self.assertTrue(plan["wants_app_generation"])
        self.assertEqual(plan["intent"], "website_research")
        self.assertEqual(len(task_manifest(plan)), 1)
        summary = summarize_batch(plan, {"results": {}})
        self.assertTrue(summary["generation_handoff_required"])
        self.assertFalse(summary["generation_implemented"])

    def test_discovery_needs_search_and_has_no_invented_urls(self):
        plan = plan_request("找3个极简网页设计案例")
        self.assertEqual(plan["status"], "needs_discovery")
        self.assertEqual(plan["requested_sites"], 3)
        self.assertEqual(task_manifest(plan), [])

    def test_discovery_uses_only_real_results_and_deduplicates_domains(self):
        plan = plan_request("找3个极简网页设计案例")
        rows = [
            {"url": "https://linear.app"},
            {"url": "https://linear.app/features"},
            {"url": "http://127.0.0.1/admin"},
            {"url": "https://vercel.com"},
            {"url": "https://www.framer.com"},
        ]
        tasks = task_manifest(plan, rows)
        self.assertEqual(len(tasks), 3)
        self.assertEqual([t["target_url"] for t in tasks], [
            "https://linear.app", "https://vercel.com", "https://www.framer.com",
        ])

    def test_model_cannot_invent_direct_target_urls(self):
        goal = "研究 https://vercel.com"
        decision = {
            "intent": "website_research",
            "urls": ["https://evil.example"],
            "requested_sites": 5,
        }
        tasks = task_manifest(plan_request(goal, decision))
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["target_url"], "https://vercel.com")

    def test_model_can_infer_web_research_when_no_keyword(self):
        plan = plan_request("帮我看看这个界面的参考", {
            "intent": "website_discovery", "requested_sites": 2,
            "search_query": "interface design references",
        })
        self.assertEqual(plan["status"], "needs_discovery")
        self.assertEqual(plan["search_query"], "interface design references")
        self.assertEqual(plan["requested_sites"], 2)

    def test_disallow_private_or_credentialed_urls(self):
        self.assertIsNone(normalize_url("http://127.0.0.1/private"))
        self.assertIsNone(normalize_url("http://localhost:8765"))
        self.assertIsNone(normalize_url("https://user:secret@example.com"))
        self.assertIsNone(normalize_url("file:///etc/passwd"))
        self.assertEqual(extract_urls("研究 https://example.com/"), ["https://example.com"])

    def test_total_targets_capped_and_flagged(self):
        urls = " ".join(f"https://example{i}.com" for i in range(7))
        plan = plan_request("研究 " + urls)
        self.assertTrue(plan["truncated_targets"])
        self.assertEqual(len(task_manifest(plan)), 5)

    def test_aggregate_never_claims_business_pass(self):
        plan = plan_request("研究 https://vercel.com 并保存")
        summary = summarize_batch(plan, {"batch_id": "batch_t", "results": {
            "site_001": {"status": "finished", "saved_case_ids": ["case_a"]},
            "site_002": {"status": "llm_error", "saved_case_ids": []},
        }})
        self.assertEqual(summary["technical_finished"], 1)
        self.assertEqual(summary["failed_tasks"], ["site_002"])
        self.assertIsNone(summary["business_pass"])
        self.assertTrue(summary["quality_review_required"])

    def test_preview_never_calls_models_or_batch(self):
        with (
            patch("agent.orchestrate.classify_with_llm") as llm,
            patch("agent.batch.run_batch") as batch,
        ):
            result = orchestrate("研究 https://vercel.com")
        self.assertEqual(result["mode"], "dry_run")
        self.assertEqual(len(result["tasks"]), 1)
        llm.assert_not_called()
        batch.assert_not_called()

    def test_execute_requires_test_env_before_any_model(self):
        with patch("agent.orchestrate.classify_with_llm") as llm:
            with self.assertRaises(ValueError):
                orchestrate("找3个极简网页设计案例", execute=True)
            llm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
