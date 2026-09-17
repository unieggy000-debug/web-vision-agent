"""Ticket 13 — autonomous finish + safety stop tests (A/B/C)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.loop import run_agent


TESTS = [
    (
        "A",
        "调查 https://bruno-simon.com/",
    ),
    (
        "B",
        "找一些具有 WebGL 交互的 portfolio，研究它们的视觉和交互设计",
    ),
    (
        "C",
        "找 2 个 web design cases",
    ),
]


def _summarize(name: str, goal: str, state) -> dict:
    final = state.final_result or {}
    tools = [h.get("tool") for h in state.history]
    return {
        "test": name,
        "goal": goal,
        "steps": state.step,
        "stop_status": state.stop_status,
        "ok": final.get("ok"),
        "status": final.get("status") or state.stop_status,
        "called_finish": "finish" in tools,
        "tools": tools,
        "researched_urls": list(state.researched_urls),
        "saved_case_ids": list(state.saved_case_ids),
        "summary_preview": str(final.get("summary") or final.get("message") or "")[:400],
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass

    only = sys.argv[1].upper() if len(sys.argv) > 1 else None
    results = []
    for name, goal in TESTS:
        if only and name != only:
            continue
        print("\n" + "#" * 60)
        print(f"# TEST {name}")
        print("#" * 60 + "\n")
        state = run_agent(goal)
        row = _summarize(name, goal, state)
        results.append(row)
        print("\n--- TEST SUMMARY ---")
        print(json.dumps(row, ensure_ascii=False, indent=2))

    out = ROOT / "data" / "ticket13_test_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nWrote", out)


if __name__ == "__main__":
    main()
