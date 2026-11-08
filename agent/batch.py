"""Bounded batch runner. Each website uses an isolated Python worker process.

Dry run is the default. Live execution requires a separate test .env file.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
BATCH_DIR = ROOT / "reports" / "batches"
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
MAX_SITES, MAX_WORKERS = 100, 4


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def validate_tasks(raw):
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_SITES:
        raise ValueError("tasks must be a list of 1..100 items")
    tasks, seen = [], set()
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ValueError("each task must be an object")
        task_id = str(item.get("task_id") or f"site_{i:03d}")
        goal = item.get("goal")
        url = str(item.get("target_url") or "")
        if not ID_RE.fullmatch(task_id) or task_id in seen:
            raise ValueError(f"invalid or duplicate task_id: {task_id!r}")
        if not isinstance(goal, str) or not goal.strip() or len(goal) > 4000:
            raise ValueError(f"{task_id}: goal must contain 1..4000 characters")
        if url:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError(f"{task_id}: invalid URL")
        seen.add(task_id)
        tasks.append({"task_id": task_id, "goal": goal.strip(), "target_url": url})
    return tasks


def atomic_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{secrets.token_hex(4)}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def run_worker(directory, batch_id, task, timeout_s, env_file):
    task_id = task["task_id"]
    output = directory / f"{task_id}.result.json"
    log = directory / f"{task_id}.log"
    command = [sys.executable, "-m", "agent.batch_worker", "--batch-id", batch_id,
               "--task-id", task_id, "--goal", task["goal"], "--result-file", str(output)]
    env = os.environ.copy()
    env["VISION_AGENT_ENV_FILE"] = str(Path(env_file).resolve())
    start = now_iso()
    started_mono = time.monotonic()
    code, payload, error = None, {}, None
    try:
        with log.open("w", encoding="utf-8") as handle:
            result = subprocess.run(command, cwd=ROOT, env=env,
                                    stdout=handle, stderr=subprocess.STDOUT,
                                    timeout=timeout_s, check=False)
        code = result.returncode
        if output.exists():
            payload = json.loads(output.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            payload = {}
    except subprocess.TimeoutExpired:
        error = "timeout"
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        error = type(exc).__name__

    status = str(payload.get("stop_status") or ("timeout" if error == "timeout" else "worker_error"))
    if code not in (None, 0) and status == "finished":
        status = "worker_error"
    return {
        "task_id": task_id, "target_url": task["target_url"],
        "status": status, "technical_finish": status == "finished",
        "business_pass": None,  # must be evaluated independently
        "run_id": payload.get("run_id"),
        "artifact_path": payload.get("artifact_path"),
        "trace_path": payload.get("trace_path"),
        "saved_case_ids": payload.get("saved_case_ids", []),
        "started_at": start, "ended_at": now_iso(),
        "duration_ms": round((time.monotonic() - started_mono) * 1000),
        "exit_code": code, "error_type": error or payload.get("error_type"),
        "log_path": str(log.relative_to(ROOT)).replace("\\", "/"),
    }


def run_batch(tasks, *, max_workers=2, timeout_s=600, env_file=None, execute=False):
    validated = validate_tasks(tasks)
    if not 1 <= max_workers <= MAX_WORKERS:
        raise ValueError(f"max_workers must be 1..{MAX_WORKERS}")
    if not 30 <= timeout_s <= 3600:
        raise ValueError("timeout_s must be 30..3600")
    batch_id = f"batch_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{secrets.token_hex(4)}"
    if not execute:
        return {"batch_id": batch_id, "mode": "dry_run", "tasks": validated,
                "max_workers": max_workers, "note": "No external calls made."}
    if not env_file or not Path(env_file).is_file():
        raise ValueError("Live execution requires --env-file with an isolated test Supabase project")
    if Path(env_file).resolve() == (ROOT / ".env").resolve():
        raise ValueError("Default .env is not allowed in live batch mode")
    # Explicit different Supabase endpoint avoids accidental use of the production DB.
    def parse_env(path):
        values = {}
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.partition("=")[::2]
                values[k.strip()] = v.strip().strip("'\"")
        return values
    prod = parse_env(ROOT / ".env") if (ROOT / ".env").is_file() else {}
    test = parse_env(env_file)
    if not test.get("SUPABASE_URL") or not test.get("SUPABASE_KEY"):
        raise ValueError("Test env must contain SUPABASE_URL and SUPABASE_KEY")
    if prod.get("SUPABASE_URL") and prod["SUPABASE_URL"] == test["SUPABASE_URL"]:
        raise ValueError("Test and default Supabase projects must be different")

    directory = BATCH_DIR / batch_id
    directory.mkdir(parents=True, exist_ok=False)
    manifest = {"schema_version": 1, "batch_id": batch_id, "mode": "live",
                "created_at": now_iso(), "task_count": len(validated),
                "max_workers": max_workers,
                "statuses": {task["task_id"]: "pending" for task in validated},
                "tasks": validated,
                "results": {}, "completed_at": None}
    path = directory / "manifest.json"
    atomic_json(path, manifest)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(run_worker, directory, batch_id, t, timeout_s, env_file): t for t in validated}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            manifest["results"][result["task_id"]] = result
            manifest["statuses"][result["task_id"]] = result["status"]
            atomic_json(path, manifest)
    manifest["completed_at"] = now_iso()
    manifest["manifest_path"] = str(path.relative_to(ROOT)).replace("\\", "/")
    atomic_json(path, manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", help="JSON with tasks array")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--env-file")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    obj = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    result = run_batch(obj.get("tasks") if isinstance(obj, dict) else obj,
                       max_workers=args.workers, timeout_s=args.timeout,
                       env_file=args.env_file, execute=args.execute)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
