"""Classify Research Cards into the Library Index only.

Never writes assignments onto Research Cards.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from library.cards import list_all_research_cards
from library.index import rebuild_index, upsert_sites
from reports.generate_report import classify_style_categories
from reports.style_categories import DEFAULT_STYLE_CATEGORY

ClassifyFn = Callable[[list[dict[str, Any]]], dict[str, Any]]


def _assignments_from(result: dict[str, Any], cards: list[dict[str, Any]]) -> dict[str, str]:
    assigned = result.get("assignments") if isinstance(result, dict) else {}
    if not isinstance(assigned, dict):
        assigned = {}
    out: dict[str, str] = {}
    for card in cards:
        cid = str(card.get("id") or "").strip()
        if not cid:
            continue
        out[cid] = str(assigned.get(cid) or DEFAULT_STYLE_CATEGORY)
    return out


def classify_and_rebuild_index(
    cards: list[dict[str, Any]] | None = None,
    *,
    classify_fn: ClassifyFn | None = None,
    index_path: Path | None = None,
) -> dict[str, Any]:
    """Delete-equivalent rebuild: cards + visual classify → new Index."""
    loaded = cards
    fetch_error = None
    if loaded is None:
        fetched = list_all_research_cards()
        loaded = list(fetched.get("cases") or [])
        if not fetched.get("ok"):
            fetch_error = fetched.get("error")
            loaded = []
    fn = classify_fn or classify_style_categories
    result = fn(loaded) if loaded else {"ok": False, "assignments": {}, "error": "no_cases"}
    assignments = _assignments_from(result if isinstance(result, dict) else {}, loaded)
    index = rebuild_index(loaded, assignments, path=index_path)
    return {
        "ok": True,
        "index": index,
        "assignments": assignments,
        "classify_ok": bool(isinstance(result, dict) and result.get("ok")),
        "classify_error": (result.get("error") if isinstance(result, dict) else None)
        or fetch_error,
        "count": len(loaded),
    }


def classify_and_upsert_index(
    cards: list[dict[str, Any]],
    *,
    classify_fn: ClassifyFn | None = None,
    index_path: Path | None = None,
) -> dict[str, Any]:
    """Classify the given cards and upsert only those rows into Index."""
    loaded = [c for c in (cards or []) if isinstance(c, dict) and c.get("id")]
    if not loaded:
        return {
            "ok": True,
            "index": None,
            "assignments": {},
            "classify_ok": False,
            "classify_error": "no_cases",
            "count": 0,
        }
    fn = classify_fn or classify_style_categories
    result = fn(loaded)
    assignments = _assignments_from(result if isinstance(result, dict) else {}, loaded)
    index = upsert_sites(loaded, assignments, path=index_path)
    return {
        "ok": True,
        "index": index,
        "assignments": assignments,
        "classify_ok": bool(isinstance(result, dict) and result.get("ok")),
        "classify_error": result.get("error") if isinstance(result, dict) else None,
        "count": len(loaded),
    }
