"""Child process: runs one independent AgentState and writes a tiny result manifest."""
import argparse
import json
from pathlib import Path
from agent.loop import run_agent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--result-file", required=True)
    args = parser.parse_args()
    try:
        state = run_agent(args.goal, task_id=args.task_id, batch_id=args.batch_id)
        payload = {
            "run_id": state.run_id, "stop_status": state.stop_status,
            "artifact_path": state.artifact_path, "trace_path": state.trace_path,
            "saved_case_ids": list(state.saved_case_ids),
        }
    except Exception as exc:
        payload = {"stop_status": "worker_error", "error_type": type(exc).__name__}
    Path(args.result_file).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    if payload["stop_status"] == "worker_error":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
