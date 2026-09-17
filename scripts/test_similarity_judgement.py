"""Ticket 15 — similarity-aware research judgment tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.loop import run_agent
from tools.memory import normalize_url, save_case, search_memory


def _print(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def _trace(state) -> list[dict]:
    rows = []
    for h in state.history:
        rows.append(
            {
                "step": h.get("step"),
                "tool": h.get("tool"),
                "thought": (h.get("thought") or "")[:180],
                "judgment": h.get("judgment") or {},
                "args": h.get("arguments") or {},
            }
        )
    return rows


def test_memory_result_shape() -> dict:
    _print("UNIT: search_memory enriched shape")
    r = search_memory("WebGL interactive portfolio")
    print("search_mode:", r.get("search_mode"))
    assert r.get("ok") is True, r
    assert r.get("results"), r
    first = r["results"][0]
    for key in ("id", "title", "url", "visual", "interaction", "frontend", "replication"):
        assert key in first, first
    print(json.dumps(first, ensure_ascii=False, indent=2)[:900])
    return r


def test_exact_url_duplicate() -> None:
    _print("Test 4: Exact URL duplicate_url")
    r1 = save_case(
        {
            "title": "Dup URL probe",
            "url": "https://bruno-simon.com/",
            "visual": {"style": "3D WebGL portfolio already in memory"},
            "interaction": {"scroll": "drive"},
            "frontend": {"libraries": [{"name": "Three.js"}]},
        }
    )
    print(json.dumps(r1, ensure_ascii=False, indent=2))
    assert r1.get("ok") is True
    assert r1.get("saved") is False
    assert r1.get("reason") == "duplicate_url"
    assert r1.get("existing_case_id")


def test_memory_unavailable() -> None:
    _print("Test 5: Memory unavailable → fallback / no crash")
    with patch(
        "tools.memory._semantic_search",
        side_effect=RuntimeError("Supabase down"),
    ):
        r = search_memory("WebGL portfolio")
    print(json.dumps({k: r.get(k) for k in ("ok", "search_mode", "embedding_error")}, indent=2))
    assert r.get("ok") is True
    assert r.get("search_mode") == "keyword_fallback"

    # Agent path: run_agent must not crash if search_memory returns fallback.
    # Lightweight: just ensure tool wrapper path is safe.
    from agent.loop import _run_tool

    with patch(
        "agent.loop.search_memory",
        return_value={
            "ok": True,
            "search_mode": "keyword_fallback",
            "results": [],
            "embedding_error": "embedding_unavailable",
            "error": None,
            "query": "x",
        },
    ):
        out = _run_tool("search_memory", {"query": "x"})
    assert out.get("ok") is True
    print("agent tool path ok")


def test_agent_bruno_skip_and_novel() -> dict:
    """
    Test 1 + 2 (+ partial 3): one agent run.
    Expect: search_memory used; Bruno treated as duplicate/skip;
    another WebGL candidate may be researched as novel/complementary.
    """
    _print("Test 1/2/3: Agent run — WebGL portfolio with memory")
    goal = (
        "研究一个具有 3D / WebGL 交互的 portfolio。"
        "先用 search_memory 对照历史案例。"
        "如果再次遇到 Bruno Simon (bruno-simon.com)，应判断 duplicate 并 skip，不要完整重研。"
        "如果发现与已有 WebGL portfolio 相似但导航/交互明显不同的站点，"
        "应判断 similar_but_novel 或 complementary，继续有针对性地研究并 save_case。"
        "信息足够后 finish。"
    )
    state = run_agent(goal)
    tools = [h.get("tool") for h in state.history]
    judgments = [h.get("judgment") or {} for h in state.history]
    novelties = [j.get("novelty") for j in judgments if j.get("novelty")]
    decisions = [j.get("decision") for j in judgments if j.get("decision")]

    opened = []
    for h in state.history:
        if h.get("tool") in {"open", "screenshot", "inspect_interaction", "inspect_frontend"}:
            url = normalize_url(str((h.get("arguments") or {}).get("url") or ""))
            if url:
                opened.append(url)

    bruno = "https://bruno-simon.com"
    deep_bruno_tools = [
        h.get("tool")
        for h in state.history
        if h.get("tool") in {"screenshot", "analyze_visual", "inspect_interaction", "inspect_frontend"}
        and normalize_url(str((h.get("arguments") or {}).get("url") or "")) == bruno
    ]

    summary = {
        "stop_status": state.stop_status,
        "steps": state.step,
        "tools": tools,
        "novelties": novelties,
        "decisions": decisions,
        "opened_urls": opened,
        "saved_case_ids": list(state.saved_case_ids),
        "skipped_urls": list(state.skipped_urls),
        "called_search_memory": "search_memory" in tools,
        "called_finish": "finish" in tools,
        "deep_researched_bruno": bool(deep_bruno_tools),
        "deep_bruno_tools": deep_bruno_tools,
        "trace": _trace(state),
    }
    print(json.dumps({k: v for k, v in summary.items() if k != "trace"}, ensure_ascii=False, indent=2))

    assert summary["called_search_memory"], "Agent should consult memory"
    # Soft expectations — LLM-driven; report honestly.
    return summary


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass

    only = sys.argv[1] if len(sys.argv) > 1 else "all"
    results: dict = {}

    if only in {"all", "unit"}:
        results["memory_shape"] = {
            "ok": True,
            "mode": test_memory_result_shape().get("search_mode"),
        }
        test_exact_url_duplicate()
        results["duplicate_url"] = {"ok": True}
        test_memory_unavailable()
        results["memory_unavailable"] = {"ok": True}

    if only in {"all", "agent"}:
        results["agent"] = test_agent_bruno_skip_and_novel()

    out = ROOT / "data" / "ticket15_test_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nWrote", out)


if __name__ == "__main__":
    main()
