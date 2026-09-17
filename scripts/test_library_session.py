"""Ticket 37 — Agent session Idle / Running / Completed / Failed (no Cancel)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.state import AgentState
from library.session import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_IDLE,
    STATUS_RUNNING,
    configure_session,
    get_session,
    reset_session,
    start_research,
)


def _wait_status(*wanted: str, timeout: float = 3.0) -> str:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        last = str(get_session().get("status") or "")
        if last in wanted:
            return last
        time.sleep(0.02)
    raise AssertionError(f"status stayed {last!r}, wanted {wanted}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    reset_session()
    calls: list[str] = []

    def fake_run(goal: str, cancel_event=None):
        calls.append(goal)
        time.sleep(0.05)
        state = AgentState(goal=goal, run_id="run_test")
        state.stop_status = "finished"
        state.saved_case_ids = []
        return state

    configure_session(run_agent_fn=fake_run, classify_fn=lambda cards: {"ok": True})
    started = start_research("find dark cinematic portfolios")
    assert started["ok"] is True
    assert get_session()["status"] == STATUS_RUNNING
    busy = start_research("another")
    assert busy["ok"] is False
    assert busy["error"] == "busy"
    _wait_status(STATUS_COMPLETED)
    assert calls == ["find dark cinematic portfolios"]
    assert get_session()["run_id"] == "run_test"
    assert get_session()["message_key"] == "msg_completed_none"

    def boom(goal: str, cancel_event=None):
        raise RuntimeError("no key")

    configure_session(run_agent_fn=boom, classify_fn=lambda cards: {"ok": True})
    failed = start_research("retry")
    assert failed["ok"] is True
    _wait_status(STATUS_FAILED)
    assert "RuntimeError" in str(get_session().get("error") or "")

    empty = start_research("  ")
    assert empty["ok"] is False
    print("ok")
    reset_session()
    configure_session()


if __name__ == "__main__":
    main()
