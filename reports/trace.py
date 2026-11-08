"""Append-only JSONL structured Traces with deliberately minimal safe metadata.

Each run is its own file. No prompt, page contents, credentials or raw tool
arguments are included. Unsupported/unknown costs remain null.
"""
from __future__ import annotations
import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACE_DIR = ROOT / "reports" / "traces"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class TraceSpan:
    def __init__(self, writer, kind, name, step):
        self.writer, self.kind, self.name, self.step = writer, kind, name, step
        self.started_at = now_iso()
        self.started_mono = time.monotonic()
        self.details = {}

    def add(self, **safe_details):
        self.details.update(safe_details)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.writer.emit({
            "event": "span", "kind": self.kind, "name": self.name,
            "step": self.step, "started_at": self.started_at,
            "ended_at": now_iso(),
            "duration_ms": round((time.monotonic() - self.started_mono) * 1000, 2),
            "ok": exc_type is None and self.details.get("ok") is not False,
            "error_type": exc_type.__name__ if exc_type else None,
            **self.details,
        })
        return False


class TraceWriter:
    ALLOWED = {
        "event", "kind", "name", "step", "at", "started_at", "ended_at",
        "duration_ms", "ok", "error_type", "schema_version",
        "prompt_tokens", "completion_tokens", "total_tokens", "parse_status",
        "stop_status", "saved_case_count", "researched_url_count",
    }

    def __init__(self, run_id, *, task_id="", batch_id=""):
        self.run_id, self.task_id, self.batch_id = run_id, task_id, batch_id
        self._lock = threading.Lock()
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        safe_run_id = re.sub(r"[^A-Za-z0-9_-]", "_", run_id)
        self.path = TRACE_DIR / f"{safe_run_id}.jsonl"
        self.relative_path = str(self.path.relative_to(ROOT)).replace("\\", "/")
        self.emit({"event": "run_start", "at": now_iso(), "schema_version": 1})

    def emit(self, record):
        row = {
            "run_id": self.run_id, "task_id": self.task_id or None,
            "batch_id": self.batch_id or None,
            **{k: v for k, v in record.items() if k in self.ALLOWED},
        }
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def span(self, kind, name, step):
        return TraceSpan(self, kind, name, step)

    def finish(self, status, saved_case_count, researched_url_count):
        self.emit({
            "event": "run_end", "at": now_iso(), "stop_status": status,
            "saved_case_count": saved_case_count, "researched_url_count": researched_url_count,
        })
