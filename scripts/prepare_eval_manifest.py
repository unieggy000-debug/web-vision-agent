"""Convert the Langfuse V0.2 mixed CSV into a live-only task manifest.

This script never calls the Agent or APIs.
"""
import argparse
import csv
import json
from pathlib import Path

def build_manifest(csv_path):
    tasks = []
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            inp = json.loads(row.get("input") or "{}")
            meta = json.loads(row.get("metadata") or "{}")
            if meta.get("execution_mode") != "controlled_live":
                continue
            goal = inp.get("goal")
            tid = meta.get("task_id")
            url = inp.get("target_url")
            if not isinstance(goal, str) or not goal.strip() or not tid:
                continue
            tasks.append({
                "task_id": tid,
                "goal": goal.strip() + (f"\n目标 URL: {url}" if url else ""),
                "target_url": url or "",
            })
    return {"tasks": tasks}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("csv")
    p.add_argument("--output", default="reports/eval_live_manifest.json")
    a = p.parse_args()
    out = build_manifest(a.csv)
    path = Path(a.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Prepared {len(out['tasks'])} live-only tasks at {path}")

if __name__ == "__main__":
    main()
