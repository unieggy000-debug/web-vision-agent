"""Library-only Research Card readers.

Not an Agent tool. Does not change get_research_cases MAX_GET_CASES=30.
Never writes to Research Cards.
"""

from __future__ import annotations

from typing import Any

from tools.memory import FETCH_LIMIT, TABLE
from tools.supabase_client import get_supabase

_SELECT = (
    "id,title,url,screenshots,visual,interaction,frontend,replication,created_at"
)


def _safe_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _card_view(row: dict[str, Any]) -> dict[str, Any]:
    """Full card for Library pages. Includes created_at. No LLM truncation."""
    return {
        "id": row.get("id") or "",
        "title": row.get("title") or "",
        "url": row.get("url") or "",
        "screenshots": row.get("screenshots")
        if isinstance(row.get("screenshots"), list)
        else [],
        "visual": row.get("visual") if isinstance(row.get("visual"), dict) else {},
        "interaction": row.get("interaction")
        if isinstance(row.get("interaction"), dict)
        else {},
        "frontend": row.get("frontend") if isinstance(row.get("frontend"), dict) else {},
        "replication": row.get("replication")
        if isinstance(row.get("replication"), dict)
        else {},
        "created_at": row.get("created_at") or "",
    }


def list_all_research_cards() -> dict[str, Any]:
    """Fetch all Research Cards for Index rebuild. Library path only."""
    try:
        client = get_supabase()
        response = (
            client.table(TABLE)
            .select(_SELECT)
            .order("created_at", desc=True)
            .limit(FETCH_LIMIT)
            .execute()
        )
        rows = response.data or []
        cases = [_card_view(row) for row in rows if isinstance(row, dict)]
        return {
            "ok": True,
            "cases": cases,
            "count": len(cases),
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "cases": [],
            "count": 0,
            "error": _safe_error(exc),
        }


def get_research_card(case_id: str) -> dict[str, Any]:
    """Fetch one full Research Card for Case Page. Library path only."""
    cid = str(case_id or "").strip()
    if not cid:
        return {"ok": False, "case": None, "error": "missing_id"}
    try:
        client = get_supabase()
        response = (
            client.table(TABLE)
            .select(_SELECT)
            .eq("id", cid)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if not rows or not isinstance(rows[0], dict):
            return {"ok": False, "case": None, "error": "not_found"}
        return {"ok": True, "case": _card_view(rows[0]), "error": None}
    except Exception as exc:
        return {"ok": False, "case": None, "error": _safe_error(exc)}
