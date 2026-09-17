"""Library Index: derived projection of Research Cards.

Research Cards are the source of truth. Index is read/search/view only.
Deleting the Index file and rebuilding from cards + assignments is supported.
Never writes back to Research Cards.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reports.presentation import (
    _evidence_strings,
    _user_facing_analysis,
    pick_hero_screenshot,
    site_domain,
)
from reports.style_categories import (
    DEFAULT_STYLE_CATEGORY,
    STYLE_CATEGORIES,
    STYLE_CATEGORY_IDS,
    category_definition,
    category_labels,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INDEX_PATH = PROJECT_ROOT / "data" / "library_index.json"
SCHEMA_VERSION = 1

_INDEX_PATH_OVERRIDE: Path | None = None


def configure_index_path(path: Path | None) -> None:
    global _INDEX_PATH_OVERRIDE
    _INDEX_PATH_OVERRIDE = path


def index_path() -> Path:
    return _INDEX_PATH_OVERRIDE or DEFAULT_INDEX_PATH


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clamp_category(category_id: str) -> str:
    key = str(category_id or "").strip()
    if key in STYLE_CATEGORY_IDS:
        return key
    return DEFAULT_STYLE_CATEGORY


def _frontend_evidence_text(frontend: dict[str, Any]) -> list[str]:
    bits: list[str] = []
    fw = frontend.get("framework") if isinstance(frontend.get("framework"), dict) else {}
    name = str(fw.get("name") or "").strip()
    evidence = _evidence_strings(fw.get("evidence"))
    if name and name.lower() != "unknown" and evidence:
        bits.append(name)
        bits.extend(evidence)
    for lib in frontend.get("libraries") or []:
        if not isinstance(lib, dict):
            continue
        lib_name = str(lib.get("name") or "").strip()
        lib_ev = _evidence_strings(lib.get("evidence"))
        if lib_name and lib_ev:
            bits.append(lib_name)
            bits.extend(lib_ev)
    return bits


def _visual_text(visual: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in (
        "style",
        "layout",
        "typography",
        "color",
        "spacing",
        "imagery",
        "visual_effects",
    ):
        text = _user_facing_analysis(str(visual.get(key) or ""))
        if text:
            out.append(text)
    return out


def _interaction_text(interaction: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("scroll", "hover", "cursor", "transition"):
        text = _user_facing_analysis(str(interaction.get(key) or ""))
        if text:
            out.append(text)
    return out


def build_search_text(card: dict[str, Any], category_id: str) -> str:
    """Derived query blob. Title may be included for search but is not a display name."""
    url = str(card.get("url") or "")
    domain = site_domain(url)
    label_en, label_zh = category_labels(category_id)
    def_en, def_zh = category_definition(category_id)
    visual = card.get("visual") if isinstance(card.get("visual"), dict) else {}
    interaction = card.get("interaction") if isinstance(card.get("interaction"), dict) else {}
    frontend = card.get("frontend") if isinstance(card.get("frontend"), dict) else {}
    parts = [
        domain,
        url,
        str(card.get("title") or ""),
        category_id,
        label_en,
        label_zh,
        def_en,
        def_zh,
        *_visual_text(visual),
        *_interaction_text(interaction),
        *_frontend_evidence_text(frontend),
    ]
    seen: set[str] = set()
    kept: list[str] = []
    for part in parts:
        text = " ".join(str(part or "").split())
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        kept.append(text)
    return " ".join(kept)


def build_index_entry(
    card: dict[str, Any],
    category_id: str,
) -> dict[str, Any] | None:
    if not isinstance(card, dict):
        return None
    cid = str(card.get("id") or card.get("case_id") or "").strip()
    if not cid:
        return None
    cat = _clamp_category(category_id)
    url = str(card.get("url") or "")
    hero = pick_hero_screenshot(card)
    frontend = card.get("frontend") if isinstance(card.get("frontend"), dict) else {}
    return {
        "case_id": cid,
        "url": url,
        "domain": site_domain(url),
        "category_id": cat,
        "hero": hero,
        "created_at": str(card.get("created_at") or ""),
        "search_text": build_search_text(card, cat),
        "has_screenshot": bool(hero),
        "has_frontend_evidence": bool(_frontend_evidence_text(frontend)),
    }


def _project_categories(sites: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key, _en, _zh in STYLE_CATEGORIES}
    for site in sites:
        cat = _clamp_category(str(site.get("category_id") or ""))
        grouped.setdefault(cat, []).append(site)
    categories: list[dict[str, Any]] = []
    for key, label_en, label_zh in STYLE_CATEGORIES:
        group = grouped.get(key) or []
        if not group:
            continue
        def_en, def_zh = category_definition(key)
        cover = next((s.get("hero") for s in group if s.get("hero")), None)
        categories.append(
            {
                "id": key,
                "label_en": label_en,
                "label_zh": label_zh,
                "definition_en": def_en,
                "definition_zh": def_zh,
                "cover": cover,
                "count": len(group),
                "case_ids": [str(s.get("case_id") or "") for s in group],
            }
        )
    return categories


def empty_index() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "sites": [],
        "categories": [],
    }


def load_index(path: Path | None = None) -> dict[str, Any]:
    target = path or index_path()
    if not target.exists():
        return empty_index()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return empty_index()
    if not isinstance(data, dict):
        return empty_index()
    sites = data.get("sites") if isinstance(data.get("sites"), list) else []
    data["sites"] = [s for s in sites if isinstance(s, dict)]
    data["categories"] = _project_categories(data["sites"])
    data["schema_version"] = SCHEMA_VERSION
    return data


def save_index(index: dict[str, Any], path: Path | None = None) -> Path:
    target = path or index_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": str(index.get("generated_at") or _utc_now()),
        "sites": list(index.get("sites") or []),
        "categories": _project_categories(list(index.get("sites") or [])),
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def rebuild_index(
    cards: list[dict[str, Any]],
    assignments: dict[str, str] | None = None,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Rebuild Index from cards + assignments. Does not mutate cards."""
    assigned = assignments or {}
    sites: list[dict[str, Any]] = []
    for card in cards or []:
        if not isinstance(card, dict):
            continue
        cid = str(card.get("id") or "").strip()
        entry = build_index_entry(card, assigned.get(cid, DEFAULT_STYLE_CATEGORY))
        if entry:
            sites.append(entry)
    index = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "sites": sites,
        "categories": _project_categories(sites),
    }
    save_index(index, path=path)
    return index


def upsert_sites(
    cards: list[dict[str, Any]],
    assignments: dict[str, str] | None = None,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Insert or replace Index rows for the given cards. Does not mutate cards."""
    current = load_index(path)
    by_id = {
        str(site.get("case_id") or ""): site
        for site in (current.get("sites") or [])
        if isinstance(site, dict) and site.get("case_id")
    }
    assigned = assignments or {}
    for card in cards or []:
        if not isinstance(card, dict):
            continue
        cid = str(card.get("id") or "").strip()
        if not cid:
            continue
        entry = build_index_entry(card, assigned.get(cid, DEFAULT_STYLE_CATEGORY))
        if entry:
            by_id[cid] = entry
    sites = list(by_id.values())
    index = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "sites": sites,
        "categories": _project_categories(sites),
    }
    save_index(index, path=path)
    return index


def sites_for_category(
    index: dict[str, Any],
    category_id: str,
    *,
    sort: str = "recent",
) -> list[dict[str, Any]]:
    cat = _clamp_category(category_id)
    sites = [
        s
        for s in (index.get("sites") or [])
        if isinstance(s, dict) and _clamp_category(str(s.get("category_id") or "")) == cat
    ]
    reverse = str(sort or "recent").lower() != "oldest"
    sites.sort(key=lambda s: str(s.get("created_at") or ""), reverse=reverse)
    return sites


def style_directory(index: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """All closed-vocab styles, including empty ones. Occupied rows carry Index counts."""
    data = index if isinstance(index, dict) else empty_index()
    by_id = {
        str(cat.get("id") or ""): cat
        for cat in (data.get("categories") or [])
        if isinstance(cat, dict) and cat.get("id")
    }
    rows: list[dict[str, Any]] = []
    for key, label_en, label_zh in STYLE_CATEGORIES:
        existing = by_id.get(key) if isinstance(by_id.get(key), dict) else {}
        def_en, def_zh = category_definition(key)
        rows.append(
            {
                "id": key,
                "label_en": label_en,
                "label_zh": label_zh,
                "definition_en": str(existing.get("definition_en") or def_en),
                "definition_zh": str(existing.get("definition_zh") or def_zh),
                "cover": existing.get("cover"),
                "count": int(existing.get("count") or 0),
                "case_ids": list(existing.get("case_ids") or []),
            }
        )
    return rows


def category_record(index: dict[str, Any], category_id: str) -> dict[str, Any] | None:
    wanted = str(category_id or "").strip()
    if wanted not in STYLE_CATEGORY_IDS:
        return None
    for cat in style_directory(index):
        if cat.get("id") == wanted:
            return cat
    return None


def site_by_id(index: dict[str, Any], case_id: str) -> dict[str, Any] | None:
    wanted = str(case_id or "").strip()
    for site in index.get("sites") or []:
        if isinstance(site, dict) and str(site.get("case_id") or "") == wanted:
            return site
    return None
