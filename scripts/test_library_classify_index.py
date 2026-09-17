"""Ticket 29 — classify writes Index only; Library reader is not the Agent tool."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from library.classify import classify_and_rebuild_index, classify_and_upsert_index
from library.index import configure_index_path, load_index
from tools.memory import MAX_GET_CASES


def _cards() -> list[dict]:
    return [
        {
            "id": "case_a",
            "title": "Internal Title Next.js",
            "url": "https://romanjeanelie.com/",
            "created_at": "2026-09-17T10:00:00+00:00",
            "screenshots": [],
            "visual": {"style": "Dark cinematic stage"},
            "interaction": {},
            "frontend": {},
            "replication": {},
        },
        {
            "id": "case_b",
            "title": "Editorial",
            "url": "https://studiofreight.com/",
            "created_at": "2026-09-16T10:00:00+00:00",
            "screenshots": [],
            "visual": {"style": "Minimal editorial portfolio"},
            "interaction": {},
            "frontend": {},
            "replication": {},
        },
    ]


def _fake_classify(cases):
    return {
        "ok": True,
        "error": None,
        "assignments": {
            "case_a": "dark_cinematic",
            "case_b": "editorial",
        },
        "payload": [{"id": c["id"], "visual": c.get("visual")} for c in cases],
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    assert MAX_GET_CASES == 30
    tmp = ROOT / "data" / "_tmp_index_t29.json"
    configure_index_path(tmp)
    try:
        if tmp.exists():
            tmp.unlink()
        cards = _cards()
        snapshot = json.dumps(cards, ensure_ascii=False)
        result = classify_and_rebuild_index(
            cards, classify_fn=_fake_classify, index_path=tmp
        )
        assert result["ok"] is True
        assert json.dumps(cards, ensure_ascii=False) == snapshot
        index = load_index(tmp)
        by_id = {s["case_id"]: s for s in index["sites"]}
        assert by_id["case_a"]["category_id"] == "dark_cinematic"
        assert by_id["case_b"]["category_id"] == "editorial"

        tmp.unlink()
        with patch(
            "library.classify.list_all_research_cards",
            return_value={"ok": True, "cases": cards, "count": 2},
        ):
            rebuilt = classify_and_rebuild_index(
                classify_fn=_fake_classify, index_path=tmp
            )
        assert json.dumps(cards, ensure_ascii=False) == snapshot
        assert len(rebuilt["index"]["sites"]) == 2

        extra = {
            "id": "case_c",
            "title": "Empty",
            "url": "https://example.com/empty",
            "created_at": "2026-09-15T00:00:00+00:00",
            "screenshots": [],
            "visual": {},
            "interaction": {},
            "frontend": {},
            "replication": {},
        }
        upsert = classify_and_upsert_index(
            [extra],
            classify_fn=lambda _c: {"ok": False, "assignments": {}, "error": "down"},
            index_path=tmp,
        )
        assert extra["visual"] == {}
        ids = {s["case_id"]: s["category_id"] for s in upsert["index"]["sites"]}
        assert ids["case_c"] == "other"
        assert ids["case_a"] == "dark_cinematic"

        import inspect
        from agent.loop import _run_tool

        source = inspect.getsource(_run_tool)
        assert 'name == "list_all_research_cards"' not in source
        print("ok")
    finally:
        configure_index_path(None)
        if tmp.exists():
            tmp.unlink()


if __name__ == "__main__":
    main()
