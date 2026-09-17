"""Ticket 28 — Library Index is a derived projection of Research Cards."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from library.index import (
    build_index_entry,
    configure_index_path,
    load_index,
    rebuild_index,
)
from reports.style_categories import STYLE_CATEGORY_IDS


def _card(**kwargs) -> dict:
    base = {
        "id": "case_a",
        "title": "Roman Jean-Elie — Next.js + R3F internal title",
        "url": "https://www.romanjeanelie.com/?ref=1",
        "created_at": "2026-09-17T10:00:00+00:00",
        "screenshots": [],
        "visual": {"style": "Dark cinematic full-viewport stage"},
        "interaction": {"hover": "Shape scales on hover."},
        "frontend": {
            "framework": {"name": "Next.js", "evidence": ["__NEXT_DATA__"]},
            "libraries": [{"name": "GuessLib", "evidence": []}],
        },
        "replication": {},
    }
    base.update(kwargs)
    return base


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    tmp = ROOT / "data" / "_tmp_index_t28.json"
    configure_index_path(tmp)
    try:
        if tmp.exists():
            tmp.unlink()

        cards = [
            _card(),
            _card(
                id="case_b",
                title="Editorial Studio",
                url="https://studiofreight.com/",
                created_at="2026-09-16T10:00:00+00:00",
                visual={"style": "Minimal editorial portfolio"},
                frontend={},
            ),
        ]
        snapshot = json.dumps(cards, ensure_ascii=False)
        assignments = {"case_a": "dark_cinematic", "case_b": "editorial"}
        index = rebuild_index(cards, assignments, path=tmp)
        assert json.dumps(cards, ensure_ascii=False) == snapshot
        assert tmp.exists()

        by_id = {s["case_id"]: s for s in index["sites"]}
        assert by_id["case_a"]["domain"] == "romanjeanelie.com"
        assert by_id["case_a"]["category_id"] == "dark_cinematic"
        assert "dark cinematic" in by_id["case_a"]["search_text"].lower()
        assert "roman jean-elie" in by_id["case_a"]["search_text"].lower()
        assert "GuessLib" not in by_id["case_a"]["search_text"]
        assert "Next.js" in by_id["case_a"]["search_text"]
        assert by_id["case_a"]["has_frontend_evidence"] is True
        cat_ids = [c["id"] for c in index["categories"]]
        assert "dark_cinematic" in cat_ids
        assert "editorial" in cat_ids
        assert "brutalist" not in cat_ids
        assert "immersive_3d" not in cat_ids
        assert set(cat_ids) <= set(STYLE_CATEGORY_IDS)

        loaded = load_index(tmp)
        assert len(loaded["sites"]) == 2

        loaded["sites"][0]["search_text"] = "CORRUPT"
        loaded["sites"][0]["category_id"] = "playful"
        tmp.write_text(json.dumps(loaded), encoding="utf-8")
        rebuilt = rebuild_index(cards, assignments, path=tmp)
        assert json.dumps(cards, ensure_ascii=False) == snapshot
        again = {s["case_id"]: s for s in rebuilt["sites"]}
        assert again["case_a"]["category_id"] == "dark_cinematic"
        assert "CORRUPT" not in again["case_a"]["search_text"]

        tmp.unlink()
        assert not tmp.exists()
        rebuilt2 = rebuild_index(cards, assignments, path=tmp)
        assert {s["case_id"] for s in rebuilt2["sites"]} == {"case_a", "case_b"}

        bad = build_index_entry(cards[0], "not-a-style")
        assert bad is not None
        assert bad["category_id"] == "other"
        print("ok")
    finally:
        configure_index_path(None)
        if tmp.exists():
            tmp.unlink()


if __name__ == "__main__":
    main()
