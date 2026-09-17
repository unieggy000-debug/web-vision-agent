"""Ticket 39 — after a run (including cancel), saved cards are classified into Index only."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.state import AgentState
from library.index import configure_index_path, load_index
from library.session import configure_session, get_session, reset_session, start_research


def _wait(status: str, timeout: float = 3.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if get_session().get("status") == status:
            return
        time.sleep(0.02)
    raise AssertionError(get_session())


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    reset_session()
    tmp = ROOT / "data" / "_tmp_index_t39.json"
    configure_index_path(tmp)
    if tmp.exists():
        tmp.unlink()

    card = {
        "id": "case_x",
        "title": "Internal",
        "url": "https://romanjeanelie.com/",
        "created_at": "2026-09-17T00:00:00+00:00",
        "screenshots": [],
        "visual": {"style": "Dark cinematic stage"},
        "interaction": {},
        "frontend": {},
        "replication": {},
    }
    snapshot = json.dumps(card["visual"])
    classified: list[list] = []

    def fake_run(goal: str, cancel_event=None):
        st = AgentState(goal=goal, run_id="run_x")
        st.stop_status = "finished"
        st.saved_case_ids = ["case_x"]
        return st

    def fake_classify(cards):
        classified.append(list(cards))
        from library.classify import classify_and_upsert_index

        return classify_and_upsert_index(
            cards,
            classify_fn=lambda _c: {
                "ok": True,
                "assignments": {"case_x": "dark_cinematic"},
            },
            index_path=tmp,
        )

    configure_session(
        run_agent_fn=fake_run,
        classify_fn=fake_classify,
        card_loader=lambda cid: {"ok": True, "case": card},
    )
    start_research("find cinematic sites")
    _wait("completed")
    assert classified
    assert json.dumps(card["visual"]) == snapshot
    index = load_index(tmp)
    by_id = {s["case_id"]: s for s in index["sites"]}
    assert by_id["case_x"]["category_id"] == "dark_cinematic"

    def cancel_run(goal: str, cancel_event=None):
        st = AgentState(goal=goal, run_id="run_y")
        st.stop_status = "cancelled"
        st.saved_case_ids = ["case_x"]
        return st

    configure_session(
        run_agent_fn=cancel_run,
        classify_fn=fake_classify,
        card_loader=lambda cid: {"ok": True, "case": card},
    )
    start_research("again")
    _wait("idle")
    assert json.dumps(card["visual"]) == snapshot
    print("ok")
    reset_session()
    configure_session()
    configure_index_path(None)
    if tmp.exists():
        tmp.unlink()


if __name__ == "__main__":
    main()
