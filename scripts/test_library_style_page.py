"""Ticket 33 — Style Page has no Search; name, definition, cards, Sort only."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from library.index import rebuild_index
from library.pages import render_style_page


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    tmp = ROOT / "data" / "_tmp_index_style.json"
    index = rebuild_index(
        [
            {
                "id": "case_new",
                "title": "Internal New",
                "url": "https://newer.example/",
                "created_at": "2026-09-18T00:00:00+00:00",
                "screenshots": [],
                "visual": {"style": "Editorial magazine"},
                "interaction": {},
                "frontend": {},
                "replication": {},
            },
            {
                "id": "case_old",
                "title": "Internal Old",
                "url": "https://older.example/",
                "created_at": "2026-09-01T00:00:00+00:00",
                "screenshots": [],
                "visual": {"style": "Editorial magazine"},
                "interaction": {},
                "frontend": {},
                "replication": {},
            },
        ],
        {"case_new": "editorial", "case_old": "editorial"},
        path=tmp,
    )
    recent = render_style_page("editorial", index, sort="recent")
    oldest = render_style_page("editorial", index, sort="oldest")
    assert recent and oldest
    assert '<input type="search"' not in recent
    assert 'name="q"' not in recent
    assert 'class="search-form"' not in recent
    assert "class=\"zoomable\"" not in recent
    assert "newer.example" in recent
    assert "older.example" in recent
    assert recent.index("newer.example") < recent.index("older.example")
    assert oldest.index("older.example") < oldest.index("newer.example")
    assert "Magazine" in recent or "杂志" in recent or "content narrative" in recent
    empty = render_style_page("brutalist", index)
    assert empty is not None
    assert "Brutalist" in empty
    assert "empty_style" in empty or "No sites" in empty or "还没有网站" in empty
    print("ok")
    if tmp.exists():
        tmp.unlink()


if __name__ == "__main__":
    main()
