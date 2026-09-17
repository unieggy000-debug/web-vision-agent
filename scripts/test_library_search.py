"""Ticket 36 — Home Search / Filter / Sort never starts the Agent."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import library.search as search_mod
from library.index import rebuild_index
from library.pages import render_home, render_style_page
from library.search import filter_sites
from library.session import reset_session


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    reset_session()
    src = inspect.getsource(search_mod)
    assert "run_agent" not in src
    tmp = ROOT / "data" / "_tmp_index_search.json"
    index = rebuild_index(
        [
            {
                "id": "case_a",
                "title": "Internal A",
                "url": "https://romanjeanelie.com/",
                "created_at": "2026-09-17T00:00:00+00:00",
                "screenshots": [],
                "visual": {"style": "Dark cinematic stage"},
                "interaction": {},
                "frontend": {
                    "framework": {"name": "Next.js", "evidence": ["__NEXT_DATA__"]}
                },
                "replication": {},
            },
            {
                "id": "case_b",
                "title": "Internal B",
                "url": "https://jordan-breton.com/",
                "created_at": "2026-09-10T00:00:00+00:00",
                "screenshots": [],
                "visual": {"style": "Futuristic sci-fi world"},
                "interaction": {},
                "frontend": {},
                "replication": {},
            },
        ],
        {"case_a": "dark_cinematic", "case_b": "futuristic"},
        path=tmp,
    )
    hits = filter_sites(index, q="romanjeanelie")
    assert [s["domain"] for s in hits] == ["romanjeanelie.com"]
    fut = filter_sites(index, style="futuristic")
    assert [s["case_id"] for s in fut] == ["case_b"]
    recent = filter_sites(index, sort="recent")
    oldest = filter_sites(index, sort="oldest")
    assert recent[0]["case_id"] == "case_a"
    assert oldest[0]["case_id"] == "case_b"
    ev = filter_sites(index, has_frontend_evidence=True)
    assert [s["case_id"] for s in ev] == ["case_a"]

    home = render_home(index, q="romanjeanelie", session={"status": "idle"})
    assert "romanjeanelie.com" in home
    assert 'name="q"' in home
    assert 'action="/research"' in home
    assert 'method="get" action="/"' in home.replace("\n", " ") or 'action="/"' in home
    style = render_style_page("futuristic", index)
    assert style is not None
    assert '<input type="search"' not in style
    print("ok")
    if tmp.exists():
        tmp.unlink()
    reset_session()


if __name__ == "__main__":
    main()
