"""Product-layer Agent session.

Input starts run_agent(goal). Search never uses this module.
Cancel is a cooperative flag read by the loop before each _ask_llm call.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from agent.state import AgentState
from library.cards import get_research_card
from library.classify import classify_and_upsert_index

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_STOPPING = "stopping"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

_BUSY = {STATUS_RUNNING, STATUS_STOPPING}

RunAgentFn = Callable[..., AgentState]
ClassifyUpsertFn = Callable[..., dict[str, Any]]

_lock = threading.Lock()
_cancel_event = threading.Event()
_thread: threading.Thread | None = None
_run_agent_fn: RunAgentFn | None = None
_classify_fn: ClassifyUpsertFn | None = None
_card_loader: Callable[[str], dict[str, Any]] | None = None
_state: dict[str, Any] = {
    "status": STATUS_IDLE,
    "goal": "",
    "run_id": "",
    "saved_case_ids": [],
    "stop_status": "",
    "error": None,
    "message": "",
    "message_key": "",
}


def configure_session(
    *,
    run_agent_fn: RunAgentFn | None = None,
    classify_fn: ClassifyUpsertFn | None = None,
    card_loader: Callable[[str], dict[str, Any]] | None = None,
) -> None:
    global _run_agent_fn, _classify_fn, _card_loader
    _run_agent_fn = run_agent_fn
    _classify_fn = classify_fn
    _card_loader = card_loader


def reset_session() -> None:
    """Test helper. Does not cancel an in-flight real agent."""
    global _thread
    with _lock:
        _cancel_event.clear()
        _thread = None
        _state.update(
            {
                "status": STATUS_IDLE,
                "goal": "",
                "run_id": "",
                "saved_case_ids": [],
                "stop_status": "",
                "error": None,
                "message": "",
                "message_key": "",
            }
        )


def get_session() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def start_research(goal: str) -> dict[str, Any]:
    text = str(goal or "").strip()
    if not text:
        return {"ok": False, "error": "empty_goal", "session": get_session()}
    with _lock:
        if _state["status"] in _BUSY:
            return {"ok": False, "error": "busy", "session": dict(_state)}
        _cancel_event.clear()
        _state.update(
            {
                "status": STATUS_RUNNING,
                "goal": text,
                "run_id": "",
                "saved_case_ids": [],
                "stop_status": "",
                "error": None,
                "message": "Research in progress.",
                "message_key": "msg_running",
            }
        )
        thread = threading.Thread(target=_worker, args=(text,), daemon=True)
        global _thread
        _thread = thread
        thread.start()
        return {"ok": True, "error": None, "session": dict(_state)}


def request_cancel() -> dict[str, Any]:
    with _lock:
        if _state["status"] != STATUS_RUNNING:
            return {"ok": False, "error": "not_running", "session": dict(_state)}
        _cancel_event.set()
        _state["status"] = STATUS_STOPPING
        _state["message"] = "Stopping, please wait."
        _state["message_key"] = "msg_stopping"
        return {"ok": True, "error": None, "session": dict(_state)}


def _ingest_saved_cases(case_ids: list[str]) -> None:
    cards: list[dict[str, Any]] = []
    loader = _card_loader or get_research_card
    for cid in case_ids:
        fetched = loader(str(cid))
        case = fetched.get("case") if isinstance(fetched, dict) else None
        if isinstance(fetched, dict) and fetched.get("ok") and isinstance(case, dict):
            cards.append(case)
        elif isinstance(fetched, dict) and fetched.get("id"):
            cards.append(fetched)
    if not cards:
        return
    fn = _classify_fn or classify_and_upsert_index
    fn(cards)


def _worker(goal: str) -> None:
    from agent.loop import run_agent as default_run_agent

    runner = _run_agent_fn or default_run_agent
    try:
        agent_state = runner(goal, cancel_event=_cancel_event)
    except TypeError:
        # Tests / older stubs that only accept goal.
        try:
            agent_state = runner(goal)
        except Exception as exc:
            _finish_failed(exc)
            return
    except Exception as exc:
        _finish_failed(exc)
        return

    saved = list(getattr(agent_state, "saved_case_ids", None) or [])
    stop_status = str(getattr(agent_state, "stop_status") or "")
    run_id = str(getattr(agent_state, "run_id") or "")
    cancelled = stop_status == "cancelled" or _cancel_event.is_set()
    try:
        _ingest_saved_cases(saved)
        ingest_error = None
    except Exception as exc:
        ingest_error = f"{type(exc).__name__}: {exc}"

    with _lock:
        _state["run_id"] = run_id
        _state["saved_case_ids"] = saved
        _state["stop_status"] = stop_status
        _state["error"] = ingest_error
        if cancelled:
            _state["status"] = STATUS_IDLE
            _state["message"] = "Stopped. Saved cases were kept."
            _state["message_key"] = "msg_cancelled"
        elif stop_status == "llm_error":
            _state["status"] = STATUS_FAILED
            _state["message"] = "Research failed."
            _state["message_key"] = "msg_failed"
        else:
            _state["status"] = STATUS_COMPLETED
            if not saved:
                _state["message"] = (
                    "Finished, but no new sites were saved. "
                    "Try a specific URL, or run again."
                )
                _state["message_key"] = "msg_completed_none"
            elif stop_status in {"max_steps_reached", "emergency_step_ceiling"}:
                _state["message"] = (
                    "Stopped at the emergency ceiling. "
                    "Some requested styles may still be missing."
                )
                _state["message_key"] = "msg_completed_partial"
            else:
                _state["message"] = "Research completed."
                _state["message_key"] = "msg_completed"


def _finish_failed(exc: BaseException) -> None:
    with _lock:
        _state["status"] = STATUS_FAILED
        _state["error"] = f"{type(exc).__name__}: {exc}"
        _state["message"] = "Research failed."
        _state["message_key"] = "msg_failed"
