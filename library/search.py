"""Home Search / Filter / Sort over the Library Index. Never starts the Agent."""

from __future__ import annotations

from typing import Any

from library.index import _clamp_category
from reports.style_categories import STYLE_CATEGORY_IDS


def filter_sites(
    index: dict[str, Any],
    *,
    q: str = "",
    style: str | list[str] = "",
    sort: str = "recent",
    has_screenshot: bool | None = None,
    has_frontend_evidence: bool | None = None,
) -> list[dict[str, Any]]:
    sites = [
        s for s in (index.get("sites") or []) if isinstance(s, dict) and s.get("case_id")
    ]
    query = " ".join(str(q or "").split()).lower()
    if query:
        sites = [s for s in sites if query in str(s.get("search_text") or "").lower()]

    styles: list[str] = []
    if isinstance(style, list):
        styles = [_clamp_category(x) for x in style if str(x).strip()]
    elif str(style or "").strip():
        styles = [_clamp_category(style)]
    styles = [s for s in styles if s in STYLE_CATEGORY_IDS]
    if styles:
        sites = [s for s in sites if str(s.get("category_id") or "") in styles]

    if has_screenshot is True:
        sites = [s for s in sites if s.get("has_screenshot")]
    elif has_screenshot is False:
        sites = [s for s in sites if not s.get("has_screenshot")]

    if has_frontend_evidence is True:
        sites = [s for s in sites if s.get("has_frontend_evidence")]
    elif has_frontend_evidence is False:
        sites = [s for s in sites if not s.get("has_frontend_evidence")]

    reverse = str(sort or "recent").lower() != "oldest"
    sites.sort(key=lambda s: str(s.get("created_at") or ""), reverse=reverse)
    return sites


def filter_categories(
    index: dict[str, Any],
    *,
    q: str = "",
    style: str | list[str] = "",
) -> list[dict[str, Any]]:
    """Home style directory: full closed vocab, including empty classes."""
    from library.index import style_directory

    rows = style_directory(index)
    styles: list[str] = []
    if isinstance(style, list):
        styles = [_clamp_category(x) for x in style if str(x).strip()]
    elif str(style or "").strip():
        styles = [_clamp_category(style)]
    styles = [s for s in styles if s in STYLE_CATEGORY_IDS]
    if styles:
        rows = [row for row in rows if str(row.get("id") or "") in styles]
    query = " ".join(str(q or "").split()).lower()
    if query:
        matched_site_cats = {
            str(s.get("category_id") or "")
            for s in filter_sites(index, q=q, style=style)
        }
        rows = [
            row
            for row in rows
            if str(row.get("id") or "") in matched_site_cats
            or query in str(row.get("id") or "").lower()
            or query in str(row.get("label_en") or "").lower()
            or query in str(row.get("label_zh") or "")
        ]
    return rows
