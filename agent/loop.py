"""Minimal Agent Loop: LLM chooses tools until finish / safe stop."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any

from openai import OpenAI

from agent.prompts import SYSTEM_PROMPT, build_turn_prompt
from agent.state import AgentState
from tools.browser import open_page
from tools.frontend import inspect_frontend
from tools.interaction import inspect_interaction
from tools.memory import get_research_cases, normalize_url, save_case, search_memory
from tools.screenshot import screenshot
from tools.search import search
from tools.vision import analyze_visual
from reports.generate_report import generate_research_report
from reports.run_artifact import new_run_id, persist_run_artifact, utc_now_iso

MAX_FINISH_VALIDATION_REJECTS = 1
# Stop when the next action would be the 3rd consecutive identical fingerprint.
REPEAT_LIMIT = 3
# Not a research budget. Hard stop only if the loop is clearly runaway.
EMERGENCY_STEP_CEILING = 500
MAX_CONSECUTIVE_LLM_ERRORS = 3
ANALYSIS_TOOLS = {"analyze_visual", "inspect_interaction", "inspect_frontend"}
PLACEHOLDER_KEYS = {"", "your_api_key_here"}
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _project_env() -> dict[str, str]:
    """Read weekly-web-research-agent/.env without depending on process env vars."""
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip("'\"")
    return values


def _api_key() -> str:
    """Prefer DeepSeek key; fall back to OPENAI_API_KEY if that's what you set."""
    env = _project_env()
    key = env.get("DEEPSEEK_API_KEY") or env.get("OPENAI_API_KEY") or ""
    if key in PLACEHOLDER_KEYS:
        names = ", ".join(env.keys()) or "(none)"
        raise RuntimeError(
            "No real API key loaded from "
            f"{ENV_PATH}. Keys found: {names}. "
            "Save .env (Ctrl+S) and replace your_api_key_here with the DeepSeek key."
        )
    return key


def _model() -> str:
    return _project_env().get("OPENAI_MODEL") or "deepseek-flash"


def _base_url() -> str:
    return _project_env().get("OPENAI_BASE_URL") or "https://api.deepseek.com"


def _action_fingerprint(tool: str, arguments: dict[str, Any]) -> str:
    """Stable fingerprint for repeat detection (tool + key args)."""
    tool = (tool or "").strip().lower()
    args = arguments if isinstance(arguments, dict) else {}
    parts = [tool]
    if tool == "search":
        parts.append("q=" + str(args.get("query") or "").strip().lower())
    elif tool == "search_memory":
        parts.append("q=" + str(args.get("query") or "").strip().lower())
    elif tool in {"open", "screenshot", "inspect_interaction", "inspect_frontend"}:
        parts.append("url=" + normalize_url(str(args.get("url") or "")))
    elif tool == "analyze_visual":
        parts.append("path=" + str(args.get("screenshot_path") or "").strip().lower())
    elif tool == "save_case":
        case = args.get("case") if isinstance(args.get("case"), dict) else args
        url = ""
        if isinstance(case, dict):
            url = str(case.get("url") or "")
        parts.append("url=" + normalize_url(url))
    elif tool == "get_research_cases":
        parts.append("ids=" + ",".join(sorted(str(x) for x in (args.get("case_ids") or []))))
        parts.append("limit=" + str(args.get("limit") or 10))
    elif tool == "generate_research_report":
        parts.append("ids=" + ",".join(sorted(str(x) for x in (args.get("case_ids") or []))))
        parts.append("limit=" + str(args.get("limit") or 10))
    elif tool == "finish":
        parts.append("finish")
    else:
        # Fallback: stringify sorted shallow keys (no secrets expected).
        try:
            parts.append(json.dumps(args, sort_keys=True, ensure_ascii=False)[:300].lower())
        except Exception:
            parts.append(str(args)[:300].lower())
    return "|".join(parts)


def _would_form_repeat_loop(history: list[dict[str, Any]], tool: str, arguments: dict[str, Any]) -> bool:
    """
    True when the next action would create REPEAT_LIMIT identical consecutive actions.
    One accidental repeat is allowed; a clear loop is not.
    """
    if tool == "finish":
        return False
    fp = _action_fingerprint(tool, arguments)
    if not fp:
        return False
    streak = 1
    for item in reversed(history):
        prev = _action_fingerprint(str(item.get("tool") or ""), item.get("arguments") or {})
        if prev == fp:
            streak += 1
            if streak >= REPEAT_LIMIT:
                return True
        else:
            break
    return False


def _tool_counts(history: list[dict[str, Any]]) -> dict[str, int]:
    tools = [str(h.get("tool") or "") for h in history or []]
    return {
        "research_tool_calls": sum(1 for t in tools if t in ANALYSIS_TOOLS),
        "screenshots": sum(1 for t in tools if t == "screenshot"),
        "searches": sum(1 for t in tools if t == "search"),
        "opens": sum(1 for t in tools if t == "open"),
    }


def _is_specific_url_goal(goal: str) -> bool:
    g = goal or ""
    return "http://" in g.lower() or "https://" in g.lower()


def _goal_expects_saved_cases(goal: str) -> bool:
    """True only when the goal clearly asks to keep / produce research cases."""
    g = (goal or "").lower()
    markers = [
        "save_case",
        "保存",
        "案例",
        "research card",
        "research cases",
        "saved case",
        "save case",
        "存档",
    ]
    return any(m in g or m in (goal or "") for m in markers)


def _summary_claims_cases(summary: str) -> bool:
    """Detect summaries that claim cases were found/saved without checking a count."""
    s = (summary or "").lower()
    patterns = [
        "saved case",
        "save_case",
        "research case",
        "research card",
        "案例",
        "已保存",
        "保存了",
        "找到了",
        "找到 ",
        "found 1",
        "found 2",
        "found 3",
        "two cases",
        "2 cases",
        "2 个",
        "两个",
        "case_20",
    ]
    return any(p in s or p in (summary or "") for p in patterns)


def validate_finish(
    state: AgentState,
    finish_arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Lightweight guardrail against obvious false finishes.
    Does NOT enforce fixed case counts or fixed tool pipelines.
    """
    finish_arguments = finish_arguments if isinstance(finish_arguments, dict) else {}
    goal = state.current_goal or state.goal or ""
    summary = str(finish_arguments.get("summary") or "")
    counts = _tool_counts(state.history or [])
    researched = len(state.researched_urls or [])
    saved = len(state.saved_case_ids or [])
    skipped = len(state.skipped_urls or [])
    research_tool_calls = counts["research_tool_calls"]

    evidence = {
        "researched_urls": researched,
        "research_tool_calls": research_tool_calls,
        "screenshots": counts["screenshots"],
        "saved_case_ids": saved,
        "skipped_urls": skipped,
        "report_paths": len(state.report_paths or []),
    }

    tools = [str(h.get("tool") or "") for h in (state.history or [])]
    fetched_cases = sum(1 for t in tools if t == "get_research_cases")
    # Only a successful report path counts — failed generate_research_report does not.
    made_report = len(state.report_paths or []) > 0

    # Synthesis-only goals: loaded memory cases + generated a report is enough.
    if made_report and fetched_cases >= 1:
        return {
            "valid": True,
            "reason": "Sufficient research evidence exists.",
            "evidence": evidence,
        }

    # Situation 1: completely empty research evidence.
    if researched == 0 and research_tool_calls == 0 and saved == 0 and not made_report:
        return {
            "valid": False,
            "reason": (
                "The agent claims the research is complete, but no research evidence "
                "or saved cases were produced."
            ),
            "evidence": evidence,
        }

    # Claims "found/saved N cases" but nothing was saved — classic false finish.
    # Exception: single-URL investigation goals may analyze without saving.
    if saved == 0 and _summary_claims_cases(summary):
        if _is_specific_url_goal(goal) and researched >= 1 and research_tool_calls >= 1:
            pass  # allowed
        else:
            return {
                "valid": False,
                "reason": (
                    "The finish summary claims research cases were completed, "
                    "but saved_case_ids is empty."
                ),
                "evidence": evidence,
            }

    # Goal clearly asks to save cases, but none were saved and analysis is also missing.
    if (
        _goal_expects_saved_cases(goal)
        and saved == 0
        and research_tool_calls == 0
        and not _is_specific_url_goal(goal)
    ):
        return {
            "valid": False,
            "reason": (
                "The goal asks for research cases, but no analysis tools ran "
                "and no cases were saved."
            ),
            "evidence": evidence,
        }

    # Goal asks to save cases; had some browsing but never analyzed or saved.
    if (
        _goal_expects_saved_cases(goal)
        and saved == 0
        and researched == 0
        and research_tool_calls == 0
    ):
        return {
            "valid": False,
            "reason": "No researched URLs, analysis, or saved cases for a case-research goal.",
            "evidence": evidence,
        }

    # Sufficient patterns:
    # - specific URL (+ analysis) even without save
    # - researched + analysis
    # - at least one saved case with some research signal
    if researched >= 1 and research_tool_calls >= 1:
        return {
            "valid": True,
            "reason": "Sufficient research evidence exists.",
            "evidence": evidence,
        }
    if saved >= 1 and (researched >= 1 or research_tool_calls >= 1 or counts["screenshots"] >= 1):
        return {
            "valid": True,
            "reason": "Sufficient research evidence exists.",
            "evidence": evidence,
        }
    if saved >= 1 and skipped >= 0 and research_tool_calls >= 1:
        return {
            "valid": True,
            "reason": "Sufficient research evidence exists.",
            "evidence": evidence,
        }

    # Opened pages but never analyzed and never saved — still too weak.
    if research_tool_calls == 0 and saved == 0:
        return {
            "valid": False,
            "reason": (
                "Pages may have been opened, but no visual/interaction/frontend "
                "analysis and no saved cases were produced."
            ),
            "evidence": evidence,
        }

    return {
        "valid": True,
        "reason": "Sufficient research evidence exists.",
        "evidence": evidence,
    }


def _progress_dict(state: AgentState) -> dict[str, Any]:
    return {
        "current_goal": state.current_goal or state.goal,
        "researched_urls": list(state.researched_urls),
        "saved_case_ids": list(state.saved_case_ids),
        "skipped_urls": list(state.skipped_urls),
        "step_count": state.step_count or state.step,
        "last_tool": state.last_tool,
        "last_novelty": state.last_novelty,
        "finish_validation_attempts": state.finish_validation_attempts,
        "report_paths": list(state.report_paths),
        "report_errors": list(state.report_errors),
        "run_id": state.run_id,
    }


def _extract_judgment(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "decision": decision.get("decision") or "",
        "novelty": decision.get("novelty") or "",
        "related_cases": decision.get("related_cases") or [],
        "research_focus": decision.get("research_focus") or [],
    }


def _track_progress(
    state: AgentState,
    tool: str,
    arguments: dict[str, Any],
    result: Any,
    judgment: dict[str, Any] | None = None,
) -> None:
    """Update lightweight progress fields after a tool runs."""
    state.last_tool = tool
    state.step_count = state.step

    if isinstance(judgment, dict):
        novelty = str(judgment.get("novelty") or "").strip()
        decision = str(judgment.get("decision") or "").strip()
        if novelty:
            state.last_novelty = novelty
        if decision:
            state.last_decision = decision
        # If LLM marks skip/duplicate, record candidate URL from args when present.
        if decision == "skip" or novelty == "duplicate":
            cand = ""
            if isinstance(arguments, dict):
                cand = str(arguments.get("url") or "")
                if not cand and isinstance(arguments.get("case"), dict):
                    cand = str(arguments["case"].get("url") or "")
            # Also parse from thought-related related_cases URLs is unreliable; keep URL arg path.
            norm = normalize_url(cand) if cand else ""
            if norm and norm not in state.skipped_urls:
                state.skipped_urls.append(norm)

    url = ""
    if isinstance(arguments, dict):
        url = str(arguments.get("url") or "")
    if isinstance(result, dict):
        url = str(result.get("final_url") or result.get("url") or url)

    if tool in {"open", "screenshot", "inspect_interaction", "inspect_frontend"} and url:
        norm = normalize_url(url) or url.strip()
        if norm and norm not in state.researched_urls:
            state.researched_urls.append(norm)

    if tool == "save_case" and isinstance(result, dict):
        case_id = ""
        if result.get("saved") and result.get("case_id"):
            case_id = str(result.get("case_id"))
        elif result.get("reason") == "duplicate_url" and result.get("existing_case_id"):
            case_id = str(result.get("existing_case_id"))
            # Exact URL duplicate from storage layer.
            if url:
                norm = normalize_url(url) or url.strip()
                if norm and norm not in state.skipped_urls:
                    state.skipped_urls.append(norm)
        if case_id and case_id not in state.saved_case_ids:
            state.saved_case_ids.append(case_id)

    if tool == "generate_research_report" and isinstance(result, dict):
        if result.get("ok"):
            for key in ("path", "html_path"):
                path = str(result.get(key) or "").strip()
                if path and path not in state.report_paths:
                    state.report_paths.append(path)
        else:
            err = {
                "step": state.step,
                "error": result.get("error") or "report_failed",
                "detail": result.get("detail"),
                "case_ids": list(result.get("case_ids") or []),
            }
            state.report_errors.append(err)


def _ask_llm(
    client: OpenAI,
    goal: str,
    history: list[dict[str, Any]],
    progress: dict[str, Any],
) -> dict[str, Any]:
    """Ask the LLM which tool to call next. Expects a JSON object."""
    response = client.chat.completions.create(
        model=_model(),
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_turn_prompt(goal, history, progress)},
        ],
        # Thinking is on by default for deepseek-flash; turn it off to keep this loop cheap.
        extra_body={"thinking": {"type": "disabled"}},
    )
    raw = response.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        return {
            "tool": "finish",
            "arguments": {
                "summary": "Model returned a non-object JSON payload; stopping safely.",
                "references": [],
            },
            "thought": "fallback after invalid LLM payload shape",
        }
    except json.JSONDecodeError:
        # Keep the agent loop alive; finish validation will reject empty evidence.
        return {
            "tool": "search_memory",
            "arguments": {"query": goal[:120]},
            "thought": "LLM returned invalid JSON; recovering with a safe memory check.",
        }


def _run_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Execute one tool. Tools should return structured results, not crash the loop."""
    if name == "search":
        query = arguments.get("query", "web design")
        try:
            limit = int(arguments.get("limit", 3))
        except (TypeError, ValueError):
            limit = 3
        return search(query=query, limit=limit)

    if name == "open":
        url = arguments.get("url", "")
        return open_page(url)

    if name == "screenshot":
        url = arguments.get("url", "")
        return screenshot(url)

    if name == "analyze_visual":
        path = arguments.get("screenshot_path", "")
        return analyze_visual(path)

    if name == "inspect_interaction":
        url = arguments.get("url", "")
        return inspect_interaction(url)

    if name == "inspect_frontend":
        url = arguments.get("url", "")
        return inspect_frontend(url)

    if name == "search_memory":
        query = arguments.get("query", "")
        return search_memory(query=query)

    if name == "save_case":
        case = arguments.get("case")
        if case is None and isinstance(arguments, dict):
            case = arguments
        return save_case(case=case if isinstance(case, dict) else None)

    if name == "get_research_cases":
        case_ids = arguments.get("case_ids")
        try:
            limit = int(arguments.get("limit", 10))
        except (TypeError, ValueError):
            limit = 10
        return get_research_cases(case_ids=case_ids, limit=limit)

    if name == "generate_research_report":
        case_ids = arguments.get("case_ids")
        try:
            limit = int(arguments.get("limit", 10))
        except (TypeError, ValueError):
            limit = 10
        goal = str(arguments.get("goal") or "")
        return generate_research_report(case_ids=case_ids, limit=limit, goal=goal)

    if name == "finish":
        return {
            "ok": True,
            "status": "finished",
            "summary": arguments.get("summary", ""),
            "references": arguments.get("references", []),
        }

    return {"ok": False, "error": f"Unknown tool: {name}"}


def _finalize_run(state: AgentState) -> None:
    """Stamp ended_at and persist Run Artifact. Never raises."""
    try:
        if not state.ended_at:
            state.ended_at = utc_now_iso()
        written = persist_run_artifact(
            state,
            model=_model(),
            max_steps=None,
        )
        if written.get("ok") and written.get("path"):
            state.artifact_path = written["path"]
            print(f"Run artifact: {written['path']}")
        elif written.get("error"):
            print(f"Run artifact write failed: {written.get('error')}")
    except Exception as exc:
        print(f"Run artifact finalize error: {type(exc).__name__}")


def run_agent(
    goal: str,
    cancel_event: threading.Event | None = None,
) -> AgentState:
    """
    Core loop:
      goal + progress + history + tools → LLM decision → run tool → update → repeat
    Normal stop: LLM calls finish.
    Safety stops: repeated-action loop, consecutive LLM failures,
    or an emergency runaway ceiling.
    Cooperative cancel: if cancel_event is set, stop before the next _ask_llm.
    """
    client = OpenAI(api_key=_api_key(), base_url=_base_url())
    state = AgentState(
        goal=goal,
        current_goal=goal,
        run_id=new_run_id(),
        started_at=utc_now_iso(),
    )
    history: list[dict[str, Any]] = []

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass

    print("=== Weekly Web Research Agent ===")
    print(f"Run ID: {state.run_id}")
    print(f"Goal: {goal}")
    print(f"Model: {_model()}")
    print(f"API: {_base_url()}")
    print()

    step = 0
    llm_errors = 0
    while True:
        step += 1
        state.step = step
        state.step_count = step
        if step > EMERGENCY_STEP_CEILING:
            message = (
                "Agent stopped at the emergency step ceiling after the loop "
                "failed to finish on its own."
            )
            print(f"=== Stopped: emergency step ceiling ===\n{message}")
            state.stop_status = "emergency_step_ceiling"
            state.final_result = {
                "ok": False,
                "status": "emergency_step_ceiling",
                "message": message,
                "progress": _progress_dict(state),
                "history": history,
            }
            _finalize_run(state)
            return state
        if cancel_event is not None and cancel_event.is_set():
            message = "Agent stopped because cancel was requested."
            print(f"=== Stopped: cancelled ===\n{message}")
            state.stop_status = "cancelled"
            state.final_result = {
                "ok": False,
                "status": "cancelled",
                "message": message,
                "progress": _progress_dict(state),
                "history": history,
            }
            _finalize_run(state)
            return state
        print("=" * 50)
        print(f"Step {step}")
        print("=" * 50)

        try:
            decision = _ask_llm(client, goal, history, _progress_dict(state))
            llm_errors = 0
        except Exception as exc:
            llm_errors += 1
            print(f"LLM error ({llm_errors}/{MAX_CONSECUTIVE_LLM_ERRORS}): {type(exc).__name__}: {exc}")
            if llm_errors >= MAX_CONSECUTIVE_LLM_ERRORS:
                message = (
                    "Agent stopped because the model failed repeatedly."
                )
                print(f"=== Stopped: llm error ===\n{message}")
                state.stop_status = "llm_error"
                state.final_result = {
                    "ok": False,
                    "status": "llm_error",
                    "message": message,
                    "error": f"{type(exc).__name__}: {exc}",
                    "progress": _progress_dict(state),
                    "history": history,
                }
                _finalize_run(state)
                return state
            continue
        tool = decision.get("tool", "")
        arguments = decision.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}
        thought = decision.get("thought", "")

        print(f"Agent decision: {tool}")
        if thought:
            print(f"Thought: {thought}")
        judgment = _extract_judgment(decision)
        if any(judgment.values()):
            print(f"Judgment: {json.dumps(judgment, ensure_ascii=False)}")
        print(f"Tool arguments: {json.dumps(arguments, ensure_ascii=False)}")

        if _would_form_repeat_loop(history, tool, arguments):
            message = (
                "Agent stopped because it repeated the same actions "
                "without producing new information."
            )
            print(f"=== Stopped: repeated actions ===\n{message}")
            state.stop_status = "stopped_repeated_actions"
            state.final_result = {
                "ok": False,
                "status": "stopped_repeated_actions",
                "message": message,
                "last_tool": tool,
                "last_arguments": arguments,
                "progress": _progress_dict(state),
                "history": history,
            }
            _finalize_run(state)
            return state

        result = _run_tool(tool, arguments)
        print(f"Tool result: {json.dumps(result, ensure_ascii=False, indent=2)}")
        print()

        # Finish Validation: reject obvious false finishes once, then continue the loop.
        if tool == "finish":
            validation = validate_finish(state, arguments)
            state.last_finish_validation = validation
            print(f"Finish validation: {json.dumps(validation, ensure_ascii=False)}")

            if not validation.get("valid"):
                if state.finish_validation_attempts < MAX_FINISH_VALIDATION_REJECTS:
                    state.finish_validation_attempts += 1
                    reject_result = {
                        "ok": False,
                        "status": "finish_rejected",
                        "message": (
                            "Finish validation failed. More research evidence is needed."
                        ),
                        "validation": validation,
                    }
                    history.append(
                        {
                            "step": step,
                            "tool": "finish",
                            "arguments": arguments,
                            "thought": thought,
                            "judgment": judgment,
                            "result": reject_result,
                        }
                    )
                    state.history = history
                    state.last_tool = "finish"
                    print("=== Finish rejected; continuing agent ===")
                    continue

                # Already rejected once; do not accept a second false finish.
                # Stop with a clear status so we never loop finish↔reject forever.
                message = (
                    "Agent stopped after finish validation failed more than once "
                    "without producing enough research evidence."
                )
                print(f"=== Stopped: finish validation exhausted ===\n{message}")
                exhausted_result = {
                    "ok": False,
                    "status": "finish_validation_exhausted",
                    "message": message,
                    "validation": validation,
                    "summary": arguments.get("summary", ""),
                    "references": arguments.get("references", []),
                }
                history.append(
                    {
                        "step": step,
                        "tool": "finish",
                        "arguments": arguments,
                        "thought": thought,
                        "judgment": judgment,
                        "result": exhausted_result,
                    }
                )
                state.history = history
                state.stop_status = "finish_validation_exhausted"
                state.final_result = {
                    **exhausted_result,
                    "progress": _progress_dict(state),
                    "history": history,
                }
                _finalize_run(state)
                return state

            # Attach validation evidence to a successful finish.
            if isinstance(result, dict):
                result = dict(result)
                result["finish_validation"] = validation

        history.append(
            {
                "step": step,
                "tool": tool,
                "arguments": arguments,
                "thought": thought,
                "judgment": judgment,
                "result": result,
            }
        )
        state.history = history
        _track_progress(state, tool, arguments, result, judgment)

        if tool == "finish":
            state.stop_status = "finished"
            state.final_result = result if isinstance(result, dict) else {
                "ok": True,
                "status": "finished",
                "summary": str(result),
            }
            print("=== Agent finished ===")
            _finalize_run(state)
            return state
