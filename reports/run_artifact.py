"""Research Run packaging — build and persist a local Run Artifact.

Never raises to the Agent Loop.
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "reports" / "runs"
SCHEMA_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_run_id(now: datetime | None = None) -> str:
    """Unique run id: run_YYYYMMDD_HHMMSS_<6hex>."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d_%H%M%S")
    suffix = secrets.token_hex(3)
    return f"run_{stamp}_{suffix}"


def _safe_error(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    for secret_name in (
        "SUPABASE_KEY",
        "DEEPSEEK_API_KEY",
        "TAVILY_API_KEY",
        "OPENAI_API_KEY",
        "EMBEDDING_API_KEY",
    ):
        text = text.replace(secret_name, "[redacted]")
    text = re.sub(
        r"eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}",
        "[redacted-jwt]",
        text,
    )
    text = re.sub(r"sb_publishable_[A-Za-z0-9_\-]+", "[redacted-key]", text)
    text = re.sub(r"sk-[A-Za-z0-9]{8,}", "[redacted-key]", text)
    return text


def _rel_posix(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _tool_ok(result: Any) -> bool | None:
    if not isinstance(result, dict):
        return None
    if "ok" in result:
        return bool(result.get("ok"))
    if result.get("status") == "finished":
        return True
    if result.get("status") in {
        "finish_rejected",
        "finish_validation_exhausted",
        "stopped_repeated_actions",
        "max_steps_reached",
        "emergency_step_ceiling",
        "llm_error",
        "cancelled",
    }:
        return False
    return None


def _tool_trace(history: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        entry: dict[str, Any] = {
            "step": item.get("step"),
            "tool": item.get("tool") or "",
        }
        ok = _tool_ok(item.get("result"))
        if ok is not None:
            entry["ok"] = ok
        rows.append(entry)
    return rows


def _summary_preview(state: Any) -> str:
    final = getattr(state, "final_result", None) or {}
    if isinstance(final, dict):
        text = str(final.get("summary") or final.get("message") or "")
    else:
        text = str(final)
    text = " ".join(text.split())
    return text[:400]


def _scrub_text(text: str) -> str:
    out = text or ""
    for secret_name in (
        "SUPABASE_KEY",
        "DEEPSEEK_API_KEY",
        "TAVILY_API_KEY",
        "OPENAI_API_KEY",
        "EMBEDDING_API_KEY",
    ):
        out = out.replace(secret_name, "[redacted]")
    out = re.sub(
        r"eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}",
        "[redacted-jwt]",
        out,
    )
    out = re.sub(r"sb_publishable_[A-Za-z0-9_\-]+", "[redacted-key]", out)
    out = re.sub(r"sk-[A-Za-z0-9]{8,}", "[redacted-key]", out)
    return out


def _scrub_report_errors(errors: list) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for item in errors or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        if row.get("error") is not None:
            row["error"] = _scrub_text(str(row.get("error")))
        if row.get("detail") is not None:
            row["detail"] = _scrub_text(str(row.get("detail")))
        cleaned.append(row)
    return cleaned


def build_run_artifact(
    state: Any,
    *,
    model: str = "",
    max_steps: int | None = None,
) -> dict[str, Any]:
    """Build a schema_version=1 Run Artifact dict from AgentState-like object."""
    stop_status = getattr(state, "stop_status", None)
    run_id = str(getattr(state, "run_id", "") or "") or new_run_id()
    report_paths = list(getattr(state, "report_paths", None) or [])
    report_errors = _scrub_report_errors(list(getattr(state, "report_errors", None) or []))
    history = list(getattr(state, "history", None) or [])

    artifact: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "goal": str(getattr(state, "goal", "") or ""),
        "started_at": getattr(state, "started_at", None),
        "ended_at": getattr(state, "ended_at", None) or utc_now_iso(),
        "stop_status": stop_status,
        "ok": stop_status == "finished",
        "steps": int(getattr(state, "step", 0) or getattr(state, "step_count", 0) or 0),
        "max_steps": max_steps,
        "model": model or "",
        "researched_urls": list(getattr(state, "researched_urls", None) or []),
        "skipped_urls": list(getattr(state, "skipped_urls", None) or []),
        "saved_case_ids": list(getattr(state, "saved_case_ids", None) or []),
        "report_paths": report_paths,
        "report_errors": report_errors,
        "finish_validation": {
            "attempts": int(getattr(state, "finish_validation_attempts", 0) or 0),
            "last": getattr(state, "last_finish_validation", None),
        },
        "final_summary_preview": _summary_preview(state),
        "tool_trace": _tool_trace(history),
        "task_id": getattr(state, "task_id", "") or None,
        "batch_id": getattr(state, "batch_id", "") or None,
        "trace_path": getattr(state, "trace_path", None),
        "json_parse_failures": getattr(state, "json_parse_failures", 0),
        "token_usage": getattr(state, "token_usage", None),
        "artifact_path": None,
    }
    return artifact


def write_run_artifact(artifact: dict[str, Any] | None) -> dict[str, Any]:
    """
    Persist artifact under reports/runs/.
    Returns {ok, path, error} and never raises.
    """
    try:
        if not isinstance(artifact, dict):
            return {"ok": False, "path": None, "error": "missing_artifact"}

        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        run_id = str(artifact.get("run_id") or "").strip() or new_run_id()
        # Prefer stable filename from run_id.
        safe_id = re.sub(r"[^a-zA-Z0-9_\-]+", "_", run_id)
        path = RUNS_DIR / f"{safe_id}.json"
        rel = _rel_posix(path)

        payload = dict(artifact)
        payload["run_id"] = run_id
        payload["artifact_path"] = rel

        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"ok": True, "path": rel, "error": None, "artifact": payload}
    except Exception as exc:
        return {"ok": False, "path": None, "error": _safe_error(exc)}


def persist_run_artifact(
    state: Any,
    *,
    model: str = "",
    max_steps: int | None = None,
) -> dict[str, Any]:
    """Build + write. Attaches artifact_path onto state when possible. Never raises."""
    try:
        if getattr(state, "ended_at", None) in (None, ""):
            try:
                state.ended_at = utc_now_iso()
            except Exception:
                pass
        artifact = build_run_artifact(state, model=model, max_steps=max_steps)
        written = write_run_artifact(artifact)
        if written.get("ok") and written.get("path"):
            try:
                state.artifact_path = written["path"]
            except Exception:
                pass
        return written
    except Exception as exc:
        return {"ok": False, "path": None, "error": _safe_error(exc)}
