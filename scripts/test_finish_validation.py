"""Ticket 15.5 — Finish Validation tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.loop import validate_finish, run_agent
from agent.state import AgentState


def _hist(*tools: str) -> list[dict]:
    rows = []
    for i, tool in enumerate(tools, 1):
        rows.append({"step": i, "tool": tool, "arguments": {}, "result": {"ok": True}})
    return rows


def test1_false_finish() -> None:
    print("=== Test 1: False Finish ===")
    state = AgentState(
        goal="研究 WebGL portfolio",
        current_goal="研究 WebGL portfolio",
        researched_urls=[],
        saved_case_ids=[],
        step_count=5,
        history=_hist("search", "search"),
    )
    v = validate_finish(
        state,
        {"summary": "研究完成，找到 2 个案例", "references": []},
    )
    print(json.dumps(v, ensure_ascii=False, indent=2))
    assert v["valid"] is False
    assert v["evidence"]["researched_urls"] == 0
    assert v["evidence"]["saved_case_ids"] == 0


def test2_research_complete() -> None:
    print("=== Test 2: Research Complete ===")
    state = AgentState(
        goal="研究 WebGL portfolio",
        current_goal="研究 WebGL portfolio",
        researched_urls=["https://example-a.com", "https://example-b.com"],
        saved_case_ids=["case_a", "case_b"],
        history=_hist(
            "search",
            "open",
            "screenshot",
            "analyze_visual",
            "inspect_interaction",
            "save_case",
            "open",
            "analyze_visual",
            "inspect_interaction",
            "save_case",
        ),
    )
    v = validate_finish(state, {"summary": "Saved 2 WebGL cases."})
    print(json.dumps(v, ensure_ascii=False, indent=2))
    assert v["valid"] is True


def test3_specific_website() -> None:
    print("=== Test 3: Specific Website Research ===")
    state = AgentState(
        goal="调查 https://bruno-simon.com",
        current_goal="调查 https://bruno-simon.com",
        researched_urls=["https://bruno-simon.com"],
        saved_case_ids=[],
        history=_hist(
            "open",
            "screenshot",
            "analyze_visual",
            "inspect_interaction",
            "inspect_frontend",
        ),
    )
    v = validate_finish(
        state,
        {"summary": "Bruno Simon investigated: Three.js WebGL portfolio."},
    )
    print(json.dumps(v, ensure_ascii=False, indent=2))
    assert v["valid"] is True


def test4_similarity_skip() -> None:
    print("=== Test 4: Similarity Skip still valid ===")
    state = AgentState(
        goal="研究 WebGL portfolio",
        current_goal="研究 WebGL portfolio",
        researched_urls=["https://other-webgl.com"],
        saved_case_ids=["case_new"],
        skipped_urls=["https://bruno-simon.com"],
        history=_hist(
            "search_memory",
            "search",
            "open",
            "screenshot",
            "analyze_visual",
            "inspect_interaction",
            "save_case",
        ),
    )
    v = validate_finish(
        state,
        {
            "summary": (
                "Skipped Bruno as duplicate via memory; "
                "saved one novel WebGL case."
            )
        },
    )
    print(json.dumps(v, ensure_ascii=False, indent=2))
    assert v["valid"] is True
    assert v["evidence"]["skipped_urls"] == 1


def test5_memory_failure_irrelevant() -> None:
    print("=== Test 5: Memory failure does not block finish ===")
    state = AgentState(
        goal="研究 WebGL portfolio",
        current_goal="研究 WebGL portfolio",
        researched_urls=["https://example.com"],
        saved_case_ids=["case_x"],
        history=[
            {
                "step": 1,
                "tool": "search_memory",
                "arguments": {"query": "webgl"},
                "result": {
                    "ok": True,
                    "search_mode": "keyword_fallback",
                    "embedding_error": "embedding_unavailable",
                    "results": [],
                },
            },
            {"step": 2, "tool": "search", "arguments": {}, "result": {"ok": True}},
            {"step": 3, "tool": "open", "arguments": {"url": "https://example.com"}, "result": {"ok": True}},
            {"step": 4, "tool": "screenshot", "arguments": {}, "result": {"ok": True}},
            {"step": 5, "tool": "analyze_visual", "arguments": {}, "result": {"ok": True}},
            {"step": 6, "tool": "save_case", "arguments": {}, "result": {"ok": True, "saved": True}},
        ],
    )
    v = validate_finish(state, {"summary": "Completed one case despite memory fallback."})
    print(json.dumps(v, ensure_ascii=False, indent=2))
    assert v["valid"] is True


def test_loop_rejects_false_finish_once() -> None:
    print("=== Integration: loop rejects false finish once ===")
    decisions = [
        {"tool": "finish", "arguments": {"summary": "研究完成，找到 2 个案例"}, "thought": "done"},
        {
            "tool": "finish",
            "arguments": {"summary": "研究完成，找到 2 个案例"},
            "thought": "done again",
        },
    ]
    idx = {"i": 0}

    def fake_ask(client, goal, history, progress):
        d = decisions[min(idx["i"], len(decisions) - 1)]
        idx["i"] += 1
        return d

    with patch("agent.loop._ask_llm", side_effect=fake_ask):
        with patch("agent.loop._api_key", return_value="test"):
            with patch("agent.loop.OpenAI"):
                state = run_agent("研究 WebGL portfolio")

    print("stop_status:", state.stop_status)
    print("finish_validation_attempts:", state.finish_validation_attempts)
    statuses = [
        (h.get("result") or {}).get("status")
        for h in state.history
        if h.get("tool") == "finish"
    ]
    print("finish statuses:", statuses)
    assert state.finish_validation_attempts >= 1
    assert "finish_rejected" in statuses
    assert state.stop_status == "finish_validation_exhausted"
    assert state.final_result and state.final_result.get("ok") is False


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass

    test1_false_finish()
    test2_research_complete()
    test3_specific_website()
    test4_similarity_skip()
    test5_memory_failure_irrelevant()
    test_loop_rejects_false_finish_once()
    print("\nALL FINISH VALIDATION TESTS PASSED")


if __name__ == "__main__":
    main()
