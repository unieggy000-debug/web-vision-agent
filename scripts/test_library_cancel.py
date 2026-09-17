"""Ticket 38 — Cooperative cancel before each _ask_llm. No cancel tool."""

from __future__ import annotations

import inspect
import sys
import threading
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.loop import _run_tool, run_agent
from library.session import (
    STATUS_IDLE,
    STATUS_RUNNING,
    STATUS_STOPPING,
    configure_session,
    get_session,
    request_cancel,
    reset_session,
    start_research,
)
import time
from agent.state import AgentState


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    source = inspect.getsource(_run_tool)
    assert "cancel" not in source
    assert 'name == "cancel"' not in source

    asks: list[int] = []
    event = threading.Event()

    def fake_ask(client, goal, history, progress):
        asks.append(1)
        event.set()
        return {
            "tool": "search_memory",
            "arguments": {"query": "x"},
            "thought": "step",
        }

    with patch("agent.loop._ask_llm", side_effect=fake_ask), patch(
        "agent.loop._api_key", return_value="test"
    ), patch("agent.loop.OpenAI"), patch(
        "agent.loop._run_tool", return_value={"ok": True, "results": []}
    ), patch("agent.loop._finalize_run"):
        state = run_agent("research portfolios", cancel_event=event)

    assert state.stop_status == "cancelled"
    assert len(asks) == 1
    assert state.saved_case_ids == []

    # CLI / tests without a flag keep asking until finish.
    finish_asks: list[int] = []

    def finish_once(client, goal, history, progress):
        finish_asks.append(1)
        return {
            "tool": "finish",
            "arguments": {"summary": "done", "references": []},
            "thought": "done",
        }

    with patch("agent.loop._ask_llm", side_effect=finish_once), patch(
        "agent.loop._api_key", return_value="test"
    ), patch("agent.loop.OpenAI"), patch("agent.loop.validate_finish") as vf, patch(
        "agent.loop._finalize_run"
    ):
        vf.return_value = {"valid": True, "reason": "ok"}
        plain = run_agent("cli goal")
    assert plain.stop_status == "finished"
    assert len(finish_asks) == 1

    reset_session()
    gate = threading.Event()
    started_run = threading.Event()

    def slow_run(goal: str, cancel_event=None):
        started_run.set()
        gate.wait(timeout=2)
        if cancel_event is not None and cancel_event.is_set():
            st = AgentState(goal=goal, run_id="c1")
            st.stop_status = "cancelled"
            st.saved_case_ids = ["case_kept"]
            return st
        st = AgentState(goal=goal, run_id="c1")
        st.stop_status = "finished"
        return st

    configure_session(
        run_agent_fn=slow_run,
        classify_fn=lambda cards: {"ok": True},
        card_loader=lambda cid: {"ok": True, "case": {"id": cid, "visual": {"style": "x"}}},
    )
    start_research("long run")
    started_run.wait(timeout=2)
    assert get_session()["status"] == STATUS_RUNNING
    cancelled = request_cancel()
    assert cancelled["ok"] is True
    assert get_session()["status"] == STATUS_STOPPING
    busy = start_research("nope")
    assert busy["ok"] is False
    gate.set()
    deadline = time.time() + 3
    while time.time() < deadline and get_session()["status"] != STATUS_IDLE:
        time.sleep(0.02)
    assert get_session()["status"] == STATUS_IDLE
    assert get_session()["saved_case_ids"] == ["case_kept"]
    print("ok")
    reset_session()
    configure_session()


if __name__ == "__main__":
    main()
