"""Build a new task manifest containing only technically failed batch tasks.

For race reproduction, use the original full task manifest instead.
This does not contact external APIs or the database.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def failed_tasks(manifest):
    tasks = manifest.get("tasks") or []
    results = manifest.get("results") or {}
    selected = []
    for task in tasks:
        row = results.get(task["task_id"], {})
        if row.get("status") != "finished":
            selected.append(task)
    return {"tasks": selected, "retry_of_batch_id": manifest.get("batch_id")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("batch_manifest")
    parser.add_argument("--output", default="reports/retry_failed_tasks.json")
    args = parser.parse_args()
    parent = json.loads(Path(args.batch_manifest).read_text(encoding="utf-8"))
    result = failed_tasks(parent)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Selected {len(result['tasks'])} unfinished/failed tasks; {target}")


if __name__ == "__main__":
    main()
