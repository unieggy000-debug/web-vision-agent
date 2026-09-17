"""Ticket 40 — Home Input vs Search, status/Cancel, browse while running."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from library.app import make_server
from library.index import configure_index_path, rebuild_index
from library.session import (
    STATUS_RUNNING,
    configure_session,
    get_session,
    reset_session,
    start_research,
)


def _get(url: str) -> tuple[int, str]:
    with urlopen(url, timeout=5) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def _post(url: str, data: bytes) -> int:
    req = Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urlopen(req, timeout=5) as resp:
        return resp.status


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    reset_session()
    tmp = ROOT / "data" / "_tmp_index_t40.json"
    configure_index_path(tmp)
    rebuild_index(
        [
            {
                "id": "case_a",
                "title": "Internal",
                "url": "https://romanjeanelie.com/",
                "created_at": "2026-09-17T00:00:00+00:00",
                "screenshots": [],
                "visual": {"style": "Dark cinematic"},
                "interaction": {},
                "frontend": {},
                "replication": {},
            }
        ],
        {"case_a": "dark_cinematic"},
        path=tmp,
    )

    starts: list[str] = []
    gate = threading.Event()
    running = threading.Event()

    def fake_run(goal: str, cancel_event=None):
        starts.append(goal)
        running.set()
        gate.wait(timeout=3)
        from agent.state import AgentState

        st = AgentState(goal=goal, run_id="ui")
        st.stop_status = "cancelled" if cancel_event is not None and cancel_event.is_set() else "finished"
        return st

    configure_session(run_agent_fn=fake_run, classify_fn=lambda cards: {"ok": True})
    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        base = f"http://{host}:{port}"
        code, home = _get(base + "/")
        assert code == 200
        assert 'action="/research"' in home
        assert 'name="goal"' in home
        assert 'name="q"' in home
        assert "search-form" in home
        assert "research-form" in home

        code, searched = _get(base + "/?q=romanjeanelie")
        assert code == 200
        assert starts == []
        assert "romanjeanelie.com" in searched

        _post(base + "/research", b"goal=find+architecture+portfolios")
        running.wait(timeout=2)
        assert starts == ["find architecture portfolios"]
        assert get_session()["status"] == STATUS_RUNNING
        code, running_home = _get(base + "/")
        assert code == 200
        assert "research/cancel" in running_home
        code, still_search = _get(base + "/?q=romanjeanelie")
        assert code == 200
        code, style = _get(base + "/style/dark_cinematic")
        assert code == 200
        assert '<input type="search"' not in style

        _post(base + "/research/cancel", b"")
        assert get_session()["status"] in {"stopping", "idle"}
        with urlopen(base + "/api/status", timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload["status"] in {"stopping", "idle", "running"}
        gate.set()
        print("ok")
    finally:
        gate.set()
        server.shutdown()
        configure_index_path(None)
        if tmp.exists():
            tmp.unlink()
        reset_session()
        configure_session()


if __name__ == "__main__":
    main()
