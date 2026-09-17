"""
Weekly Web Research Agent — entry point.

Usage:
  python main.py
  python main.py "调查 https://bruno-simon.com/"
"""

import json
import sys

from agent.loop import run_agent


DEFAULT_GOAL = """
找一些值得参考的 web design cases，研究视觉与交互，保存有价值的案例，信息足够后 finish。
""".strip()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass

    if len(sys.argv) > 1:
        goal = " ".join(sys.argv[1:]).strip()
    else:
        goal = DEFAULT_GOAL

    state = run_agent(goal)

    print()
    print("--- Final result ---")
    if state.final_result:
        # Avoid dumping full history twice in the console for stop cases.
        payload = dict(state.final_result)
        if "history" in payload and payload.get("status") in {
            "max_steps_reached",
            "emergency_step_ceiling",
            "llm_error",
            "stopped_repeated_actions",
        }:
            payload = {
                k: v for k, v in payload.items() if k != "history"
            }
            payload["history_steps"] = state.step
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"Run ID: {state.run_id}")
    print(f"Run artifact: {state.artifact_path or '(none)'}")
    print(f"Total steps: {state.step}")
    print(f"Stop status: {state.stop_status}")
    print(f"Researched URLs: {state.researched_urls}")
    print(f"Saved cases: {state.saved_case_ids}")
    print(f"Report paths: {state.report_paths}")
    if state.report_errors:
        print(f"Report errors: {len(state.report_errors)}")


if __name__ == "__main__":
    main()
