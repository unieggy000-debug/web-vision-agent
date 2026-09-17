"""Ticket 17 — Weekly Research Run Packaging tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.loop import _track_progress, run_agent, validate_finish
from agent.prompts import format_progress
from agent.state import AgentState
from reports.run_artifact import (
    build_run_artifact,
    new_run_id,
    write_run_artifact,
)


def _hist(*tools: str) -> list[dict]:
    rows = []
    for i, tool in enumerate(tools, 1):
        rows.append({"step": i, "tool": tool, "arguments": {}, "result": {"ok": True}})
    return rows


def test1_build_schema() -> dict:
    print("=== T1: build_run_artifact schema ===")
    state = AgentState(
        goal="test goal",
        run_id="run_test_001",
        started_at="2026-09-17T00:00:00+00:00",
        ended_at="2026-09-17T00:01:00+00:00",
        stop_status="finished",
        step=3,
        researched_urls=["https://a.example"],
        saved_case_ids=["case_1"],
        skipped_urls=[],
        report_paths=["reports/report_x.md"],
        report_errors=[],
        history=_hist("search", "open", "finish"),
        final_result={"ok": True, "status": "finished", "summary": "done"},
    )
    art = build_run_artifact(state, model="deepseek-flash", max_steps=28)
    print(json.dumps({k: art[k] for k in ("schema_version", "run_id", "ok", "stop_status")}, ensure_ascii=False))
    assert art["schema_version"] == 1
    assert art["run_id"] == "run_test_001"
    assert art["ok"] is True
    assert art["stop_status"] == "finished"
    assert art["saved_case_ids"] == ["case_1"]
    assert art["report_paths"] == ["reports/report_x.md"]
    assert isinstance(art["tool_trace"], list) and len(art["tool_trace"]) == 3
    assert "goal" in art and "started_at" in art and "ended_at" in art
    return art


def test2_write_artifact(art: dict) -> str:
    print("=== T2: write_run_artifact ===")
    written = write_run_artifact(art)
    print(json.dumps({k: written.get(k) for k in ("ok", "path", "error")}, ensure_ascii=False))
    assert written["ok"] is True
    path = written["path"]
    assert path and path.startswith("reports/runs/")
    assert "\\" not in path
    abs_path = ROOT / path
    assert abs_path.exists()
    loaded = json.loads(abs_path.read_text(encoding="utf-8"))
    assert loaded["run_id"] == art["run_id"]
    assert loaded["artifact_path"] == path
    return path


def test3_unique_run_ids() -> None:
    print("=== T3: unique run_id ===")
    a, b = new_run_id(), new_run_id()
    print(a, b)
    assert a != b
    assert a.startswith("run_")
    assert b.startswith("run_")


def test4_format_progress_with_reports() -> None:
    print("=== T4: format_progress with report_paths ===")
    text = format_progress(
        {
            "researched_urls": [],
            "saved_case_ids": [],
            "skipped_urls": [],
            "report_paths": ["reports/report_demo.md"],
            "step_count": 2,
            "max_steps": 28,
            "last_tool": "generate_research_report",
            "last_novelty": "",
        }
    )
    print(text)
    assert "report paths (1):" in text
    assert "reports/report_demo.md" in text
    assert "/ 28" not in text
    assert "current step: 2" in text


def test5_format_progress_empty_reports() -> None:
    print("=== T5: format_progress empty report_paths ===")
    text = format_progress(
        {
            "researched_urls": [],
            "saved_case_ids": [],
            "skipped_urls": [],
            "report_paths": [],
            "step_count": 1,
            "max_steps": 28,
            "last_tool": "search",
            "last_novelty": "",
        }
    )
    print(text)
    assert "report paths (0): (none)" in text
    assert "/ 28" not in text


def test6_track_report_failure() -> None:
    print("=== T6: track report failure ===")
    state = AgentState(goal="g", step=4)
    _track_progress(
        state,
        "generate_research_report",
        {"limit": 5},
        {"ok": False, "path": None, "error": "no_cases", "detail": "empty", "case_ids": []},
    )
    assert state.report_paths == []
    assert len(state.report_errors) == 1
    assert state.report_errors[0]["error"] == "no_cases"
    assert state.report_errors[0]["step"] == 4
    print(json.dumps(state.report_errors, ensure_ascii=False))


def test7_track_report_success() -> None:
    print("=== T7: track report success ===")
    state = AgentState(goal="g", step=5)
    _track_progress(
        state,
        "generate_research_report",
        {},
        {"ok": True, "path": "reports/report_ok.md", "error": None},
    )
    assert state.report_paths == ["reports/report_ok.md"]
    assert state.report_errors == []
    print(state.report_paths)


def test8_failed_report_not_synthesis_evidence() -> None:
    print("=== T8: failed report is NOT synthesis evidence ===")
    state = AgentState(
        goal="总结已有案例写报告",
        current_goal="总结已有案例写报告",
        researched_urls=[],
        saved_case_ids=[],
        report_paths=[],
        history=[
            {
                "step": 1,
                "tool": "get_research_cases",
                "arguments": {},
                "result": {"ok": True, "count": 2},
            },
            {
                "step": 2,
                "tool": "generate_research_report",
                "arguments": {},
                "result": {"ok": False, "error": "synthesis_failed", "path": None},
            },
        ],
    )
    v = validate_finish(state, {"summary": "报告已生成"})
    print(json.dumps(v, ensure_ascii=False, indent=2))
    assert v["valid"] is False


def test9_successful_report_synthesis_finish() -> None:
    print("=== T9: successful report still allows synthesis-only finish ===")
    state = AgentState(
        goal="总结已有案例写报告",
        current_goal="总结已有案例写报告",
        researched_urls=[],
        saved_case_ids=[],
        report_paths=["reports/report_ok.md"],
        history=[
            {
                "step": 1,
                "tool": "get_research_cases",
                "arguments": {},
                "result": {"ok": True, "count": 2},
            },
            {
                "step": 2,
                "tool": "generate_research_report",
                "arguments": {},
                "result": {"ok": True, "path": "reports/report_ok.md"},
            },
        ],
    )
    v = validate_finish(state, {"summary": "报告已生成，见 reports/report_ok.md"})
    print(json.dumps(v, ensure_ascii=False, indent=2))
    assert v["valid"] is True


def test10_run_agent_writes_artifact_on_safety_stop() -> None:
    print("=== T10: run_agent persists artifact on finish_validation_exhausted ===")
    decisions = [
        {"tool": "finish", "arguments": {"summary": "研究完成，找到 2 个案例"}, "thought": "done"},
        {"tool": "finish", "arguments": {"summary": "研究完成，找到 2 个案例"}, "thought": "again"},
    ]
    idx = {"i": 0}

    def fake_ask(client, goal, history, progress):
        d = decisions[min(idx["i"], len(decisions) - 1)]
        idx["i"] += 1
        return d

    with patch("agent.loop._ask_llm", side_effect=fake_ask):
        with patch("agent.loop._api_key", return_value="test"):
            with patch("agent.loop.OpenAI"):
                with patch("agent.loop._model", return_value="test-model"):
                    state = run_agent("研究 WebGL portfolio")

    print("run_id:", state.run_id)
    print("stop_status:", state.stop_status)
    print("artifact_path:", state.artifact_path)
    assert state.run_id
    assert state.started_at
    assert state.ended_at
    assert state.stop_status == "finish_validation_exhausted"
    assert state.artifact_path
    assert state.artifact_path.startswith("reports/runs/")
    abs_path = ROOT / state.artifact_path
    assert abs_path.exists()
    loaded = json.loads(abs_path.read_text(encoding="utf-8"))
    assert loaded["run_id"] == state.run_id
    assert loaded["ok"] is False  # A: ok follows stop_status == finished
    assert loaded["stop_status"] == "finish_validation_exhausted"
    assert loaded["goal"] == "研究 WebGL portfolio"


def test13_loop_has_no_research_step_budget() -> None:
    print("=== T13: loop has no 28-step research budget ===")
    import inspect

    from agent import loop as agent_loop

    src = inspect.getsource(agent_loop.run_agent)
    assert "while True:" in src
    assert "for step in range(1, MAX_STEPS + 1)" not in src
    assert agent_loop.EMERGENCY_STEP_CEILING >= 200
    assert "MAX_STEPS = 28" not in inspect.getsource(agent_loop)


def test11_no_secrets_in_artifact() -> None:
    print("=== T11: artifact has no raw secrets ===")
    state = AgentState(
        goal="g",
        run_id="run_secret_check",
        stop_status="finished",
        started_at="2026-09-17T00:00:00+00:00",
        ended_at="2026-09-17T00:00:01+00:00",
        report_errors=[
            {
                "step": 1,
                "error": "boom",
                "detail": "DEEPSEEK_API_KEY=sk-shouldnotleak1234567890",
                "case_ids": [],
            }
        ],
        final_result={"summary": "ok", "ok": True, "status": "finished"},
    )
    art = build_run_artifact(state)
    blob = json.dumps(art, ensure_ascii=False)
    assert "sk-shouldnotleak" not in blob
    assert "DEEPSEEK_API_KEY" not in blob
    assert "[redacted" in blob
    assert art["ok"] is True
    print("scrubbed detail:", art["report_errors"][0]["detail"])


def test12_ok_follows_finished_with_report_errors() -> None:
    print("=== T12: ok follows finished even with report_errors (decision A) ===")
    state = AgentState(
        goal="g",
        run_id="run_ok_with_errors",
        stop_status="finished",
        started_at="2026-09-17T00:00:00+00:00",
        ended_at="2026-09-17T00:00:02+00:00",
        report_paths=[],
        report_errors=[{"step": 3, "error": "no_cases", "detail": None, "case_ids": []}],
        final_result={"ok": True, "status": "finished", "summary": "done without report"},
    )
    art = build_run_artifact(state)
    assert art["ok"] is True
    assert art["report_errors"]
    print(json.dumps({"ok": art["ok"], "errors": len(art["report_errors"])}, ensure_ascii=False))


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass

    results = {}
    art = test1_build_schema()
    results["artifact_path"] = test2_write_artifact(art)
    test3_unique_run_ids()
    test4_format_progress_with_reports()
    test5_format_progress_empty_reports()
    test6_track_report_failure()
    test7_track_report_success()
    test8_failed_report_not_synthesis_evidence()
    test9_successful_report_synthesis_finish()
    test10_run_agent_writes_artifact_on_safety_stop()
    test11_no_secrets_in_artifact()
    test12_ok_follows_finished_with_report_errors()
    test13_loop_has_no_research_step_budget()

    out = ROOT / "data" / "ticket17_test_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "passed",
        "sample_artifact": results.get("artifact_path"),
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nALL TICKET 17 TESTS PASSED")
    print("Wrote", out)


if __name__ == "__main__":
    main()
