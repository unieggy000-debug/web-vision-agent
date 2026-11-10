"""Deterministic offline intent-routing evaluation, independent of paid Agent E2E.

The scored sample set is for architecture smoke testing, NOT production task
success, real-world generalization, or business-quality scores.
"""
from __future__ import annotations

import json
import sys

from agent.intent_router import plan_request, task_manifest

DISCOVERY = [
    {"url": "https://linear.app"},
    {"url": "https://vercel.com"},
    {"url": "https://www.framer.com"},
    {"url": "https://astro.build"},
    {"url": "https://stripe.com"},
]

CASES = [
    ("I01", "研究 https://vercel.com 并保存视觉案例", "website_research", 1, False),
    ("I02", "研究 https://vercel.com 和 https://linear.app", "website_research", 2, False),
    ("I03", "研究 https://vercel.com/ 和 https://vercel.com", "website_research", 1, False),
    ("I04", "找3个极简网页设计案例", "website_discovery", 3, False),
    ("I05", "找2个网站作为视觉参考", "website_discovery", 2, False),
    ("I06", "生成一个模板应用", "app_generation", 0, True),
    ("I07", "请帮我计算 12*34", "out_of_scope", 0, False),
    ("I08", "研究 https://linear.app 再生成一个模板应用", "website_research", 1, True),
    ("I09", "分析 https://vercel.com 的布局和前端", "website_research", 1, False),
    ("I10", "寻找网站做视觉设计调研", "website_discovery", 3, False),
    ("I11", "请写一封求职邮件", "out_of_scope", 0, False),
    ("I12", "研究 https://www.framer.com 的视觉效果", "website_research", 1, False),
]


def evaluate() -> dict:
    results = []
    for case_id, goal, expected_intent, expected_count, expected_generation in CASES:
        plan = plan_request(goal)
        tasks = task_manifest(
            plan,
            DISCOVERY if plan["status"] == "needs_discovery" else None,
        )
        actual = (plan["intent"], len(tasks), plan["wants_app_generation"])
        expected = (expected_intent, expected_count, expected_generation)
        results.append({
            "id": case_id,
            "passed": actual == expected,
            "expected": {
                "intent": expected_intent,
                "task_count": expected_count,
                "generation_handoff": expected_generation,
            },
            "actual": {
                "intent": actual[0], "task_count": actual[1],
                "generation_handoff": actual[2],
            },
        })
    passed = sum(row["passed"] for row in results)
    return {
        "evaluation_scope": "offline_intent_routing_only",
        "sample_count": len(results),
        "passed_count": passed,
        "failed_count": len(results) - passed,
        "pass_rate": passed / len(results),
        "business_pass": None,
        "paid_calls": 0,
        "results": results,
    }


if __name__ == "__main__":
    report = evaluate()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["failed_count"]:
        sys.exit(1)
