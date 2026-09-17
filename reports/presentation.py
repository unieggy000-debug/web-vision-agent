"""Evidence-rich report presentation helpers (Ticket 18).

Resolves screenshots / before-after pairs from Research Cards,
renders Markdown + designed static HTML. Never raises to callers
when individual assets are missing.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from reports.style_categories import (
    DEFAULT_STYLE_CATEGORY,
    STYLE_CATEGORIES,
    STYLE_CATEGORY_IDS,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_VERSION = "evidence-v1"
INTERACTION_NAME_RE = re.compile(r"interaction_|_before_|_after_|scroll_y\d+", re.I)


def _posix(rel: str) -> str:
    return (rel or "").replace("\\", "/").lstrip("./")


def project_file(rel: str) -> Path | None:
    rel = _posix(rel)
    if not rel or ".." in rel.split("/"):
        return None
    path = PROJECT_ROOT / rel
    try:
        if path.is_file() and path.stat().st_size > 0:
            return path
    except Exception:
        return None
    return None


def exists_rel(rel: str) -> bool:
    return project_file(rel) is not None


def image_content_score(rel: str) -> dict[str, Any]:
    """
    Lightweight brightness probe for hero selection.
    Returns ok/avg/dark_ratio. Never raises.
    """
    path = project_file(rel)
    if path is None:
        return {"ok": False, "avg": 0.0, "dark_ratio": 1.0, "size": 0}
    size = 0
    try:
        size = int(path.stat().st_size)
    except Exception:
        size = 0
    try:
        from PIL import Image

        with Image.open(path) as im:
            rgb = im.convert("RGB")
            w, h = rgb.size
            sample = rgb.copy()
            sample.thumbnail((160, 160))
            pixels = list(sample.getdata())
        if not pixels:
            return {"ok": True, "avg": 0.0, "dark_ratio": 1.0, "size": size, "width": w, "height": h}
        means = [(r + g + b) / 3.0 for r, g, b in pixels]
        avg = sum(means) / len(means)
        dark_ratio = sum(1 for m in means if m < 18.0) / len(means)
        # Large viewport + tiny file is a classic empty WebGL frame signal.
        if w * h >= 200_000 and size < 12_000:
            avg = min(avg, 1.0)
            dark_ratio = max(dark_ratio, 0.99)
        return {
            "ok": True,
            "avg": float(avg),
            "dark_ratio": float(dark_ratio),
            "size": size,
            "width": w,
            "height": h,
        }
    except Exception:
        # Without Pillow: large-ish files are treated as usable; tiny files as empty.
        return {
            "ok": True,
            "avg": 128.0 if size >= 12_000 else 0.0,
            "dark_ratio": 0.0 if size >= 12_000 else 1.0,
            "size": size,
        }


def is_mostly_black(
    rel: str,
    *,
    avg_max: float = 12.0,
    dark_ratio_min: float = 0.92,
) -> bool:
    """True when the image is effectively an empty/black capture."""
    stats = image_content_score(rel)
    if not stats.get("ok"):
        return True
    return float(stats.get("avg") or 0) <= avg_max and float(
        stats.get("dark_ratio") or 0
    ) >= dark_ratio_min


def md_asset_href(rel: str) -> str:
    """Relative href from reports/*.md → screenshots/."""
    return "../" + _posix(rel)


def html_asset_href(rel: str) -> str:
    """Relative href from reports/html/*.html → screenshots/."""
    return "../../" + _posix(rel)


def case_anchor(case_id: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9_-]+", "-", (case_id or "case").strip())
    return f"case-{raw or 'unknown'}"


def resolve_evidence_ids(ids: list | None, lookup: dict[str, dict]) -> list[str]:
    out: list[str] = []
    for raw in ids or []:
        cid = str(raw).strip()
        if cid and cid in lookup and cid not in out:
            out.append(cid)
    return out


def _as_path_list(screenshots: Any) -> list[str]:
    paths: list[str] = []
    for item in screenshots or []:
        if isinstance(item, str) and item.strip():
            paths.append(_posix(item.strip()))
        elif isinstance(item, dict):
            for key in ("before", "after", "path", "screenshot_path"):
                val = item.get(key)
                if isinstance(val, str) and val.strip():
                    paths.append(_posix(val.strip()))
    # dedupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _url_screenshot_variants(url: str) -> list[str]:
    raw = str(url or "").strip()
    if not raw:
        return []
    variants: list[str] = []
    for item in (raw, raw.rstrip("/"), raw if raw.endswith("/") else raw + "/"):
        if item and item not in variants:
            variants.append(item)
    return variants


def disk_screenshots_for_url(url: str) -> list[str]:
    """Find screenshot files named with the URL hash used by the screenshot tool."""
    shots_dir = PROJECT_ROOT / "screenshots"
    if not shots_dir.is_dir():
        return []
    found: list[str] = []
    seen: set[str] = set()
    for variant in _url_screenshot_variants(url):
        digest = hashlib.sha1(variant.encode("utf-8")).hexdigest()[:8]
        for path in sorted(shots_dir.glob(f"*{digest}.png")):
            rel = f"screenshots/{path.name}".replace("\\", "/")
            if rel not in seen and path.is_file() and path.stat().st_size > 0:
                seen.add(rel)
                found.append(rel)
    return found


def pick_hero_screenshot(case: dict[str, Any]) -> str | None:
    """
    Prefer a page screenshot with visible content.
    Skip near-black WebGL empty frames; fall back to interaction frames
    that have content; only then accept a black frame as last resort.
    """
    candidates = _as_path_list(case.get("screenshots"))
    candidates.extend(disk_screenshots_for_url(str(case.get("url") or "")))
    # Also consider before/after paths from visual_analysis.
    interaction = case.get("interaction") if isinstance(case.get("interaction"), dict) else {}
    for item in interaction.get("visual_analysis") or []:
        if not isinstance(item, dict):
            continue
        for key in ("after", "before"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                candidates.append(_posix(val.strip()))
    # Dedupe
    seen: set[str] = set()
    ordered: list[str] = []
    for p in candidates:
        if p not in seen:
            seen.add(p)
            ordered.append(p)

    page_shots = [p for p in ordered if not INTERACTION_NAME_RE.search(p)]
    other_shots = [p for p in ordered if INTERACTION_NAME_RE.search(p)]

    def _first_existing(pool: list[str], *, skip_black: bool) -> str | None:
        for rel in pool:
            if not exists_rel(rel):
                continue
            if skip_black and is_mostly_black(rel):
                continue
            return rel
        return None

    return (
        _first_existing(page_shots, skip_black=True)
        or _first_existing(other_shots, skip_black=True)
        or _first_existing(page_shots, skip_black=False)
        or _first_existing(other_shots, skip_black=False)
    )


def extract_before_after_pairs(case: dict[str, Any]) -> list[dict[str, Any]]:
    """Recover before/after pairs from visual_analysis, structured screenshots, or filenames."""
    pairs: list[dict[str, Any]] = []
    interaction = case.get("interaction") if isinstance(case.get("interaction"), dict) else {}

    for item in interaction.get("visual_analysis") or []:
        if not isinstance(item, dict):
            continue
        before = _posix(str(item.get("before") or ""))
        after = _posix(str(item.get("after") or ""))
        if not before or not after:
            continue
        pairs.append(
            {
                "kind": str(item.get("interaction") or "interaction"),
                "before": before,
                "after": after,
                "before_exists": exists_rel(before),
                "after_exists": exists_rel(after),
                "observation": str(
                    item.get("effect")
                    or item.get("evidence")
                    or ""
                ).strip(),
                "animation_type": str(item.get("animation_type") or ""),
                "confidence": str(item.get("confidence") or ""),
            }
        )

    for item in case.get("screenshots") or []:
        if not isinstance(item, dict):
            continue
        before = _posix(str(item.get("before") or ""))
        after = _posix(str(item.get("after") or ""))
        if before and after:
            pairs.append(
                {
                    "kind": str(item.get("kind") or "interaction"),
                    "before": before,
                    "after": after,
                    "before_exists": exists_rel(before),
                    "after_exists": exists_rel(after),
                    "observation": "",
                    "animation_type": "",
                    "confidence": "",
                }
            )

    # Filename heuristic for flat lists
    flats = [p for p in _as_path_list(case.get("screenshots")) if exists_rel(p)]
    by_stem: dict[str, dict[str, str]] = {}
    for path in flats:
        name = Path(path).name
        if "_before_" in name:
            key = name.split("_before_")[0]
            by_stem.setdefault(key, {})["before"] = path
        elif "_after_" in name:
            key = name.split("_after_")[0]
            by_stem.setdefault(key, {})["after"] = path
    for key, ends in by_stem.items():
        if ends.get("before") and ends.get("after"):
            kind = "hover" if "hover" in key.lower() else "interaction"
            pairs.append(
                {
                    "kind": kind,
                    "before": ends["before"],
                    "after": ends["after"],
                    "before_exists": True,
                    "after_exists": True,
                    "observation": "",
                    "animation_type": "",
                    "confidence": "",
                }
            )

    # Scroll y0 / y500 style pairing
    scroll_map: dict[str, str] = {}
    for path in flats:
        m = re.search(r"scroll_y(\d+)", path, re.I)
        if m:
            scroll_map[m.group(1)] = path
    if "0" in scroll_map and "500" in scroll_map:
        pairs.append(
            {
                "kind": "scroll",
                "before": scroll_map["0"],
                "after": scroll_map["500"],
                "before_exists": True,
                "after_exists": True,
                "observation": str(interaction.get("scroll") or "").strip(),
                "animation_type": "",
                "confidence": "",
            }
        )

        # Dedupe by before|after
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for p in pairs:
        key = f"{p.get('before')}|{p.get('after')}"
        if key in seen:
            continue
        seen.add(key)
        both_black = False
        if p.get("before_exists") and p.get("after_exists"):
            both_black = is_mostly_black(str(p["before"])) and is_mostly_black(str(p["after"]))
        p["both_black"] = both_black
        p["content_ok"] = bool(p.get("before_exists") and p.get("after_exists") and not both_black)
        unique.append(p)
    return unique


def truncate_cases_for_llm(cases: list[dict[str, Any]], limit: int = 900) -> list[dict[str, Any]]:
    """Keep screenshot paths; truncate long text blobs for synthesis context."""

    def trunc(value: Any, depth: int = 0) -> Any:
        if depth > 4:
            return "…"
        if isinstance(value, str):
            text = value.strip()
            return text if len(text) <= limit else text[:limit] + "…"
        if isinstance(value, list):
            return [trunc(v, depth + 1) for v in value[:20]]
        if isinstance(value, dict):
            return {str(k): trunc(v, depth + 1) for k, v in list(value.items())[:24]}
        return value

    out: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        row = {
            "id": case.get("id"),
            "title": case.get("title"),
            "url": case.get("url"),
            "screenshots": list(case.get("screenshots") or [])[:8],
            "visual": trunc(case.get("visual") or {}),
            "interaction": trunc(case.get("interaction") or {}),
            "frontend": trunc(case.get("frontend") or {}),
            "replication": trunc(case.get("replication") or {}),
        }
        out.append(row)
    return out


def build_case_views(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    views: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        cid = str(case.get("id") or "")
        hero = pick_hero_screenshot(case)
        pairs = extract_before_after_pairs(case)
        interaction = case.get("interaction") if isinstance(case.get("interaction"), dict) else {}
        frontend = case.get("frontend") if isinstance(case.get("frontend"), dict) else {}
        visual = case.get("visual") if isinstance(case.get("visual"), dict) else {}
        views.append(
            {
                "id": cid,
                "anchor": case_anchor(cid),
                "title": str(case.get("title") or cid or "Untitled"),
                "url": str(case.get("url") or ""),
                "hero": hero,
                "hero_exists": bool(hero),
                "pairs": pairs,
                "visual": visual,
                "interaction": interaction,
                "frontend": frontend,
                "replication": case.get("replication")
                if isinstance(case.get("replication"), dict)
                else {},
                "all_shots": [p for p in _as_path_list(case.get("screenshots")) if exists_rel(p)],
            }
        )
    return views


# ---------------------------------------------------------------------------
# Ticket 19 — Style Library projection (one Style → sites → details)
# ---------------------------------------------------------------------------

def site_domain(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.netloc or "").split("@")[-1].lower()
    if ":" in host:
        host = host.rsplit(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def _prompt_site_name(domain: str, url: str) -> str:
    return (domain or str(url or "").strip() or "this site").strip()


STYLE_FACETS: tuple[tuple[str, str, str], ...] = (
    ("overview", "Look and feel", "整体感觉"),
    ("typography", "Fonts", "字体"),
    ("layout", "Page layout", "页面布局"),
    ("color", "Colors", "配色"),
    ("imagery", "Images and scenes", "画面"),
    ("animation", "How it moves", "动效"),
    ("scroll", "Scrolling", "滚动"),
    ("hover_cursor", "Hover", "悬停"),
    ("interaction", "Other interactions", "其他互动"),
)

PROMPT_TEMPLATES = {
    "en": (
        "Recreate the {facet} of {title} ({url}). {analysis} "
        "Copy only what you can see. Do not invent libraries or CSS."
    ),
    "zh": (
        "请按 {title}（{url}）的{facet}来做。{analysis} "
        "只复刻能看见的效果，不要编造库或 CSS。"
    ),
}

_METRIC_PAREN_RE = re.compile(
    r"\([^)]*(?:scrollHeight|scrollY|sampled|fixed/sticky|nodes with|"
    r"opacity\s*!=|CSS transforms|CSS animations|WebGL context|"
    r"overlay/pointer|score\s+\d)[^)]*\)",
    re.I,
)
_SCORE_RE = re.compile(r"\(score\s+\d+(?:\.\d+)?/\d+\)", re.I)
_METRIC_CLAUSE_RE = re.compile(
    r"(?:,\s*)?(?:(?:and|plus)\s+)?(?:\d+\s+(?:canvases? total|"
    r"inline SVGs?(?:\s+for UI)?|sampled nodes|"
    r"nodes with(?:\s+CSS)?[^,.]*|fixed/sticky elements)"
    r"|CSS animations?\s*\(\d+\s*nodes?\)"
    r"|transforms?\s*\(\d+\s*nodes?\))",
    re.I,
)
_INSPECTOR_HINTS = (
    "scrollheight",
    "scrolly",
    "sampled",
    "bodytextlen",
    "inspector",
    "nodes with",
    "css transitions present",
    "css transforms present",
    "css animations present",
    "webgl context",
    "data-engine",
    "__next_data__",
    "checkpoints",
    "pointer interception",
    "measurable class/style",
    "measurable css",
    "measurable hover",
    "no custom cursor detected",
    "timed out",
)

_EMPTY_ANIMATION_TYPES = {"", "none", "unknown"}
_ANIMATION_LIBRARY_NAMES = frozenset(
    {
        "GSAP",
        "Three.js",
        "Lenis",
        "Lottie",
        "Anime.js",
        "Locomotive Scroll",
        "Barba.js",
        "Framer Motion",
        "Swiper",
    }
)
_SCROLL_LIBRARY_NAMES = frozenset({"Lenis", "Locomotive Scroll"})
_HOVER_LIBRARY_NAMES = frozenset({"GSAP", "Framer Motion", "Anime.js"})


def _join_analysis(*parts: Any) -> str:
    bits: list[str] = []
    for part in parts:
        if isinstance(part, list):
            for item in part:
                text = str(item or "").strip()
                if text and text not in bits:
                    bits.append(text)
            continue
        text = str(part or "").strip()
        if text and text not in bits:
            bits.append(text)
    return " ".join(bits)


def _user_facing_analysis(text: str) -> str:
    """Drop inspector metrics so category copy stays readable. Does not invent facts."""
    raw = " ".join(str(text or "").split())
    if not raw:
        return ""
    raw = _SCORE_RE.sub("", raw)
    raw = _METRIC_PAREN_RE.sub("", raw)
    raw = _METRIC_CLAUSE_RE.sub("", raw)
    parts = re.split(r"(?<=[.!?])\s+|(?<=—)\s+|(?<=–)\s+|;\s+", raw)
    kept: list[str] = []
    for part in parts:
        sentence = " ".join(part.split()).strip(" ,;.-")
        if not sentence:
            continue
        low = sentence.lower()
        if any(hint in low for hint in _INSPECTOR_HINTS):
            continue
        if kept and sentence[:1].islower():
            kept[-1] = f"{kept[-1]}; {sentence}"
            continue
        if sentence[:1].islower():
            sentence = sentence[:1].upper() + sentence[1:]
        kept.append(sentence)
    out = ". ".join(kept)
    out = re.sub(r"\s+,", ",", out)
    out = re.sub(r",\s*,+", ",", out)
    out = re.sub(r"(?:,\s*|\s+)(?:and|plus)\.?$", "", out, flags=re.I)
    return " ".join(out.split()).strip(" ,;.")


def _evidence_strings(values: Any) -> list[str]:
    out: list[str] = []
    for item in values or []:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _code_payload(snippets: list[str], *, source: str = "frontend") -> dict[str, Any] | None:
    cleaned = [s for s in snippets if s]
    if not cleaned:
        return None
    return {"source": source, "snippets": cleaned}


def _framework_code(frontend: dict[str, Any]) -> dict[str, Any] | None:
    fw = frontend.get("framework") if isinstance(frontend.get("framework"), dict) else {}
    name = str(fw.get("name") or "").strip()
    if not name or name.lower() == "unknown":
        return None
    evidence = _evidence_strings(fw.get("evidence"))
    if not evidence:
        return None
    return _code_payload([f"{name}: {item}" for item in evidence])


def _library_code(
    frontend: dict[str, Any],
    allowed_names: frozenset[str] | None = None,
) -> dict[str, Any] | None:
    snippets: list[str] = []
    for lib in frontend.get("libraries") or []:
        if not isinstance(lib, dict):
            continue
        name = str(lib.get("name") or "").strip()
        evidence = _evidence_strings(lib.get("evidence"))
        if not name or not evidence:
            continue
        if allowed_names is not None and name not in allowed_names:
            continue
        for item in evidence:
            snippets.append(f"{name}: {item}")
    return _code_payload(snippets)


def _detail_prompt(
    *,
    facet_label: str,
    site_name: str,
    url: str,
    analysis: str,
    fallback: str = "",
    lang: str = "en",
) -> str:
    text = (analysis or "").strip() or (fallback or "").strip()
    if not text:
        return ""
    template = PROMPT_TEMPLATES.get(lang) or PROMPT_TEMPLATES["en"]
    return template.format(
        facet=facet_label,
        title=site_name or "this site",
        url=url or "(no url)",
        analysis=text,
    )


def _pair_facet(pair: dict[str, Any]) -> str:
    kind = str(pair.get("kind") or "").lower()
    anim = str(pair.get("animation_type") or "").strip().lower()
    if "scroll" in kind:
        return "scroll"
    if "hover" in kind or "cursor" in kind:
        return "hover_cursor"
    if anim not in _EMPTY_ANIMATION_TYPES:
        return "animation"
    return "interaction"


def _public_pair(pair: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": str(pair.get("kind") or "interaction"),
        "before": pair.get("before") or "",
        "after": pair.get("after") or "",
        "observation": _user_facing_analysis(str(pair.get("observation") or "").strip()),
        "animation_type": str(pair.get("animation_type") or ""),
        "content_ok": True,
    }


def _make_detail(
    *,
    facet: str,
    label_en: str,
    label_zh: str,
    site_name: str,
    url: str,
    analysis: str = "",
    shots: list[str] | None = None,
    pairs: list[dict[str, Any]] | None = None,
    code: dict[str, Any] | None = None,
    prompt_fallback: str = "",
) -> dict[str, Any] | None:
    usable_pairs = [_public_pair(p) for p in (pairs or []) if p.get("content_ok")]
    usable_shots = [p for p in (shots or []) if p]
    analysis_text = _user_facing_analysis(analysis)
    if not analysis_text and not usable_pairs and not usable_shots and not code:
        return None
    name = (site_name or "this site").strip()
    fallback_en = prompt_fallback or name or label_en
    fallback_zh = prompt_fallback or name or label_zh
    prompt_en = _detail_prompt(
        facet_label=label_en,
        site_name=name,
        url=url,
        analysis=analysis_text,
        fallback=fallback_en,
        lang="en",
    )
    prompt_zh = _detail_prompt(
        facet_label=label_zh,
        site_name=name,
        url=url,
        analysis=analysis_text,
        fallback=fallback_zh,
        lang="zh",
    )
    if not prompt_en:
        prompt_en = _detail_prompt(
            facet_label=label_en,
            site_name=name,
            url=url,
            analysis=name or label_en,
            lang="en",
        )
    if not prompt_zh:
        prompt_zh = _detail_prompt(
            facet_label=label_zh,
            site_name=name,
            url=url,
            analysis=name or label_zh,
            lang="zh",
        )
    return {
        "facet": facet,
        "label": label_en,
        "label_en": label_en,
        "label_zh": label_zh,
        "analysis": analysis_text,
        "shots": usable_shots,
        "pairs": usable_pairs,
        "prompt": prompt_en,
        "prompt_en": prompt_en,
        "prompt_zh": prompt_zh,
        "code": code,
    }


def project_style_library(
    cases: list[dict[str, Any]],
    *,
    style_label: str = "",
    case_views: list[dict[str, Any]] | None = None,
    assignments: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Project Research Cards into sites and style categories.
    Does not invent CSS/JS. Empty facets are omitted. Code is evidence-only.
    Classification is report-only; Research Cards are not mutated.
    """
    views = case_views if case_views is not None else build_case_views(cases)
    assigned = {
        str(cid): str(cat)
        for cid, cat in (assignments or {}).items()
        if str(cid).strip()
    }
    sites: list[dict[str, Any]] = []

    for view in views:
        visual = view.get("visual") if isinstance(view.get("visual"), dict) else {}
        interaction = (
            view.get("interaction") if isinstance(view.get("interaction"), dict) else {}
        )
        frontend = view.get("frontend") if isinstance(view.get("frontend"), dict) else {}
        replication = (
            view.get("replication") if isinstance(view.get("replication"), dict) else {}
        )
        title = str(view.get("title") or view.get("id") or "Untitled")
        url = str(view.get("url") or "")
        domain = site_domain(url)
        site_name = _prompt_site_name(domain, url)
        hero = view.get("hero") or None
        replication_prompt = str(replication.get("prompt") or "").strip()
        cid = str(view.get("id") or "")
        category_id = assigned.get(cid, DEFAULT_STYLE_CATEGORY)
        if category_id not in STYLE_CATEGORY_IDS:
            category_id = DEFAULT_STYLE_CATEGORY

        pairs_by_facet: dict[str, list[dict[str, Any]]] = {
            key: [] for key, _en, _zh in STYLE_FACETS
        }
        for pair in view.get("pairs") or []:
            if not isinstance(pair, dict) or not pair.get("content_ok"):
                continue
            pairs_by_facet[_pair_facet(pair)].append(pair)

        facet_inputs: dict[str, dict[str, Any]] = {
            "overview": {
                "analysis": _join_analysis(visual.get("style")),
                "shots": [hero] if hero else [],
                "pairs": [],
                "code": _framework_code(frontend),
                "prompt_fallback": replication_prompt,
            },
            "typography": {"analysis": _join_analysis(visual.get("typography"))},
            "layout": {
                "analysis": _join_analysis(visual.get("layout"), visual.get("spacing")),
            },
            "color": {"analysis": _join_analysis(visual.get("color"))},
            "imagery": {
                "analysis": _join_analysis(visual.get("imagery"), visual.get("visual_effects")),
            },
            "animation": {
                "analysis": _join_analysis(interaction.get("transition")),
                "pairs": pairs_by_facet["animation"],
                "code": _library_code(frontend, _ANIMATION_LIBRARY_NAMES),
            },
            "scroll": {
                "analysis": _join_analysis(interaction.get("scroll")),
                "pairs": pairs_by_facet["scroll"],
                "code": _library_code(frontend, _SCROLL_LIBRARY_NAMES),
            },
            "hover_cursor": {
                "analysis": _join_analysis(interaction.get("hover"), interaction.get("cursor")),
                "pairs": pairs_by_facet["hover_cursor"],
                "code": _library_code(frontend, _HOVER_LIBRARY_NAMES),
            },
            "interaction": {
                "analysis": "",
                "pairs": pairs_by_facet["interaction"],
            },
        }

        details: list[dict[str, Any]] = []
        for facet, label_en, label_zh in STYLE_FACETS:
            spec = facet_inputs.get(facet) or {}
            detail = _make_detail(
                facet=facet,
                label_en=label_en,
                label_zh=label_zh,
                site_name=site_name,
                url=url,
                analysis=str(spec.get("analysis") or ""),
                shots=list(spec.get("shots") or []),
                pairs=list(spec.get("pairs") or []),
                code=spec.get("code"),
                prompt_fallback=str(spec.get("prompt_fallback") or ""),
            )
            if detail:
                details.append(detail)

        sites.append(
            {
                "id": cid,
                "anchor": str(view.get("anchor") or case_anchor(cid)),
                "title": title,
                "url": url,
                "domain": domain,
                "category_id": category_id,
                "hero": hero,
                "details": details,
            }
        )

    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key, _en, _zh in STYLE_CATEGORIES}
    for site in sites:
        grouped[str(site.get("category_id") or DEFAULT_STYLE_CATEGORY)].append(site)

    categories: list[dict[str, Any]] = []
    for key, label_en, label_zh in STYLE_CATEGORIES:
        group = grouped.get(key) or []
        if not group:
            continue
        cover = next(
            (
                s.get("hero")
                for s in group
                if s.get("hero") and exists_rel(str(s.get("hero")))
            ),
            None,
        )
        categories.append(
            {
                "id": key,
                "anchor": f"cat-{key}",
                "label_en": label_en,
                "label_zh": label_zh,
                "cover": cover,
                "sites": group,
            }
        )

    label = (style_label or "").strip() or "Style Library"
    return {"label": label, "sites": sites, "categories": categories}


def build_report_model(
    synthesis: dict[str, Any],
    cases: list[dict[str, Any]],
    *,
    goal: str = "",
    run_id: str = "",
    style_assignments: dict[str, str] | None = None,
) -> dict[str, Any]:
    lookup = {str(c.get("id") or ""): c for c in cases if isinstance(c, dict) and c.get("id")}
    case_views = build_case_views(cases)
    view_by_id = {v["id"]: v for v in case_views if v.get("id")}

    def evidence_block(ids: list | None) -> list[dict[str, Any]]:
        resolved = resolve_evidence_ids(ids, lookup)
        rows = []
        for cid in resolved:
            view = view_by_id.get(cid) or {}
            rows.append(
                {
                    "id": cid,
                    "title": view.get("title") or lookup[cid].get("title") or cid,
                    "anchor": view.get("anchor") or case_anchor(cid),
                    "url": view.get("url") or lookup[cid].get("url") or "",
                    "hero": view.get("hero"),
                }
            )
        return rows

    def enrich_list(items: list | None, id_key: str, text_key: str) -> list[dict[str, Any]]:
        out = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            ids = item.get(id_key) or []
            out.append(
                {
                    **item,
                    "text": item.get(text_key) or item.get("pattern") or item.get("finding") or "",
                    "evidence_cases": evidence_block(ids),
                }
            )
        return out

    title = str(synthesis.get("title") or "").strip()
    scope = str(synthesis.get("scope") or goal or "").strip()
    style_label = title or scope or "Style Library"
    style_library = project_style_library(
        cases,
        style_label=style_label,
        case_views=case_views,
        assignments=style_assignments,
    )

    return {
        "report_version": REPORT_VERSION,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "run_id": run_id or "",
        "goal": goal or str(synthesis.get("scope") or ""),
        "title": title or "Research Report",
        "scope": scope or goal or "",
        "cases_count": len(cases),
        "case_ids": [str(c.get("id") or "") for c in cases if c.get("id")],
        "synthesis": synthesis,
        "style_library": style_library,
        "cases": case_views,
        "lookup": lookup,
        "common_patterns": enrich_list(synthesis.get("common_patterns"), "evidence_case_ids", "pattern"),
        "interaction_patterns": enrich_list(
            synthesis.get("interaction_patterns"), "evidence_case_ids", "pattern"
        ),
        "frontend_patterns": enrich_list(
            synthesis.get("frontend_patterns"), "evidence_case_ids", "pattern"
        ),
        "notable_findings": enrich_list(
            synthesis.get("notable_findings"), "evidence_case_ids", "finding"
        ),
        "key_differences": enrich_list(synthesis.get("key_differences"), "case_ids", "comparison"),
        "replication_ideas": enrich_list(
            synthesis.get("replication_ideas"), "source_case_ids", "idea"
        ),
    }


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def render_markdown(model: dict[str, Any]) -> str:
    synthesis = model.get("synthesis") or {}
    lines: list[str] = []
    title = model.get("title") or "Research Report"
    lines += [f"# {title}", ""]
    lines += [
        f"_Report version: {model.get('report_version')} · "
        f"Generated: {model.get('generated_at')} · "
        f"Cases: {model.get('cases_count')}_",
        "",
    ]
    if model.get("run_id"):
        lines += [f"_Run ID: `{model['run_id']}`_", ""]

    lines += ["## Research Scope", "", model.get("scope") or "(not specified)", ""]

    lines += ["## Cases Analyzed", ""]
    analyzed = synthesis.get("cases_analyzed") or []
    if not analyzed:
        for c in model.get("cases") or []:
            lines.append(f"- {c.get('title')}")
    else:
        for item in analyzed:
            if isinstance(item, dict):
                lines.append(f"- {item.get('title') or item.get('id')}")
            else:
                lines.append(f"- {item}")
    lines.append("")

    def evidence_md(cases: list[dict]) -> str:
        if not cases:
            return "(none)"
        parts = []
        for ev in cases:
            parts.append(f"[{ev.get('title')}](#{ev.get('anchor')})")
        return ", ".join(parts)

    lines += ["## Notable Findings", ""]
    findings = model.get("notable_findings") or []
    if not findings:
        lines += ["_None._", ""]
    else:
        for item in findings:
            lines.append(f"- **Synthesis:** {item.get('text')}")
            lines.append(f"  - Evidence cases: {evidence_md(item.get('evidence_cases') or [])}")
        lines.append("")

    lines += ["## Common Patterns", ""]
    patterns = model.get("common_patterns") or []
    if not patterns:
        lines += ["_No common patterns with multi-case evidence._", ""]
    else:
        for i, item in enumerate(patterns, 1):
            lines += [
                f"### Pattern {i}",
                "",
                f"**Synthesis:** {item.get('text') or ''}",
                "",
                f"**Evidence:** {evidence_md(item.get('evidence_cases') or [])}",
                "",
            ]
            for ev in item.get("evidence_cases") or []:
                hero = ev.get("hero")
                if hero and exists_rel(hero):
                    lines += [f"![{ev.get('title')}]({md_asset_href(hero)})", ""]

    lines += ["## Key Differences", ""]
    diffs = model.get("key_differences") or []
    if not diffs:
        lines += ["_No key differences recorded._", ""]
    else:
        for item in diffs:
            topic = str(item.get("topic") or "Difference")
            lines += [
                f"### {topic}",
                "",
                f"**Synthesis:** {item.get('text') or ''}",
                "",
                f"**Cases:** {evidence_md(item.get('evidence_cases') or [])}",
                "",
            ]

    lines += ["## Interaction Patterns", ""]
    ip = model.get("interaction_patterns") or []
    if not ip:
        lines += ["_None._", ""]
    else:
        for item in ip:
            lines.append(f"- **Synthesis:** {item.get('text')}")
            lines.append(f"  - Evidence: {evidence_md(item.get('evidence_cases') or [])}")
        lines.append("")

    lines += ["## Frontend Patterns", ""]
    fp = model.get("frontend_patterns") or []
    if not fp:
        lines += ["_None._", ""]
    else:
        for item in fp:
            lines.append(f"- **Synthesis:** {item.get('text')}")
            lines.append(f"  - Evidence: {evidence_md(item.get('evidence_cases') or [])}")
        lines.append("")

    lines += ["## Case Studies", ""]
    for case in model.get("cases") or []:
        lines += [
            f"### {case.get('title')}",
            "",
            f"<a id=\"{case.get('anchor')}\"></a>",
            "",
            f"- **Case ID:** `{case.get('id')}`",
            f"- **Original website:** {case.get('url') or '(none)'}",
            "",
        ]
        if case.get("hero"):
            lines += [
                "#### Screenshot",
                "",
                f"![{case.get('title')}]({md_asset_href(case['hero'])})",
                "",
            ]
        else:
            lines += ["#### Screenshot", "", "_No screenshot available._", ""]

        visual = case.get("visual") or {}
        lines += ["#### Visual Analysis", ""]
        if any(str(v).strip() for v in visual.values()):
            for key in ("style", "layout", "typography", "color", "spacing", "imagery", "visual_effects"):
                if visual.get(key):
                    lines.append(f"- **{key}:** {visual.get(key)}")
            lines.append("")
        else:
            lines += ["_No visual analysis stored._", ""]

        lines += ["#### Interaction Evidence", ""]
        inter = case.get("interaction") or {}
        for key in ("scroll", "hover", "cursor", "transition"):
            if inter.get(key):
                lines.append(f"- **Observation ({key}):** {inter.get(key)}")
        pairs = case.get("pairs") or []
        usable = [p for p in pairs if p.get("content_ok")]
        if usable:
            for p in usable[:3]:
                lines += [
                    "",
                    f"**Before / After — {p.get('kind')}**",
                    "",
                    f"Before: ![]({md_asset_href(p['before'])})",
                    "",
                    f"After: ![]({md_asset_href(p['after'])})",
                    "",
                ]
                if p.get("observation"):
                    lines.append(f"- **Observation:** {p['observation']}")
            lines.append("")
        elif pairs and all(p.get("both_black") for p in pairs if p.get("before_exists")):
            lines += ["_Before/after frames were captured but appear empty/black (likely WebGL not ready)._", ""]
        elif not any(inter.get(k) for k in ("scroll", "hover", "cursor", "transition")):
            lines += ["_No interaction evidence stored._", ""]

        lines += ["#### Frontend Clues", ""]
        fe = case.get("frontend") or {}
        fw = fe.get("framework") if isinstance(fe.get("framework"), dict) else {}
        if fw.get("name") and fw.get("name") != "unknown":
            ev = fw.get("evidence") or []
            lines.append(
                f"- **Framework (evidence):** {fw.get('name')} "
                f"(confidence={fw.get('confidence') or 'n/a'})"
            )
            for e in ev[:3]:
                lines.append(f"  - `{e}`")
        libs = fe.get("libraries") if isinstance(fe.get("libraries"), list) else []
        for lib in libs[:8]:
            if not isinstance(lib, dict):
                continue
            name = lib.get("name")
            evidence = lib.get("evidence") or []
            if name and evidence:
                lines.append(f"- **Library (evidence):** {name}")
                for e in evidence[:3]:
                    lines.append(f"  - `{e}`")
            elif name:
                lines.append(f"- **Library (name only, low confidence):** {name}")
        if not fw.get("name") and not libs:
            lines.append("_No frontend evidence stored._")
        lines.append("")

    lines += ["## Replication Ideas", ""]
    ideas = model.get("replication_ideas") or []
    if not ideas:
        lines += ["_None._", ""]
    else:
        for item in ideas:
            diff = item.get("difficulty") or "unknown"
            lines.append(f"- **Idea ({diff}):** {item.get('text')}")
            lines.append(f"  - Source: {evidence_md(item.get('evidence_cases') or [])}")
        lines.append("")

    lines += ["## Source Cases", ""]
    for case in model.get("cases") or []:
        shot = "yes" if case.get("hero_exists") else "no"
        lines.append(
            f"- [{case.get('title')}](#{case.get('anchor')}) — "
            f"`{case.get('id')}` — {case.get('url') or ''} — screenshot:{shot}"
        )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML (designed demo presentation)
# ---------------------------------------------------------------------------


def _esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=True)


def _short(text: Any, n: int = 220) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def render_html(model: dict[str, Any]) -> str:
    library = model.get("style_library") if isinstance(model.get("style_library"), dict) else {}
    sites = library.get("sites") if isinstance(library.get("sites"), list) else []
    categories = library.get("categories") if isinstance(library.get("categories"), list) else []
    if not sites:
        sites = [
            {
                "id": c.get("id"),
                "anchor": c.get("anchor"),
                "title": c.get("title"),
                "url": c.get("url"),
                "domain": site_domain(str(c.get("url") or "")),
                "hero": c.get("hero"),
                "details": [],
            }
            for c in (model.get("cases") or [])
            if isinstance(c, dict)
        ]
    if not categories and sites:
        categories = [
            {
                "id": DEFAULT_STYLE_CATEGORY,
                "anchor": "cat-other",
                "label_en": "Other",
                "label_zh": "其他",
                "cover": next(
                    (s.get("hero") for s in sites if s.get("hero") and exists_rel(str(s.get("hero")))),
                    None,
                ),
                "sites": sites,
            }
        ]
    hero_site = next((s for s in sites if s.get("hero") and exists_rel(str(s.get("hero")))), None)
    hero_src = html_asset_href(str(hero_site["hero"])) if hero_site else ""

    def render_ba(pairs: list) -> str:
        blocks = []
        for p in pairs or []:
            if not isinstance(p, dict) or not p.get("content_ok"):
                continue
            before = str(p.get("before") or "")
            after = str(p.get("after") or "")
            if not exists_rel(before) or not exists_rel(after):
                continue
            obs = (
                f"<p class='obs-line'><span class='tag obs' data-i18n='tag_obs'>Observation</span> "
                f"{_esc(p.get('observation'))}</p>"
                if p.get("observation")
                else ""
            )
            blocks.append(
                f"""
<div class="ba reveal">
  <div class="ba-label"><span data-i18n="ba">Before / After</span></div>
  <div class="ba-grid">
    <figure>
      <img src="{_esc(html_asset_href(before))}" alt="Before" loading="lazy"
           data-full="{_esc(html_asset_href(before))}" class="zoomable" />
      <figcaption data-i18n="before">Before</figcaption>
    </figure>
    <figure>
      <img src="{_esc(html_asset_href(after))}" alt="After" loading="lazy"
           data-full="{_esc(html_asset_href(after))}" class="zoomable" />
      <figcaption data-i18n="after">After</figcaption>
    </figure>
  </div>
  {obs}
</div>"""
            )
        return "".join(blocks)

    def render_shots(paths: list, alt: str) -> str:
        bits = []
        for rel in paths or []:
            if not rel or not exists_rel(str(rel)):
                continue
            href = html_asset_href(str(rel))
            bits.append(
                f'<img class="detail-shot zoomable" src="{_esc(href)}" alt="{_esc(alt)}" '
                f'loading="lazy" data-full="{_esc(href)}" />'
            )
        return "".join(bits)

    def render_code(code: Any) -> str:
        if not isinstance(code, dict):
            return ""
        snippets = [str(s).strip() for s in (code.get("snippets") or []) if str(s).strip()]
        if not snippets:
            return ""
        body = "\n".join(_esc(s) for s in snippets)
        return (
            '<details class="code-fold">'
            '<summary data-i18n="label_code">Code</summary>'
            f'<pre class="code-block"><code>{body}</code></pre>'
            "</details>"
        )

    def render_detail(detail: dict, *, hero_rel: str | None = None) -> str:
        if not isinstance(detail, dict):
            return ""
        analysis = str(detail.get("analysis") or "").strip()
        label_en = str(detail.get("label_en") or detail.get("label") or detail.get("facet") or "")
        label_zh = str(detail.get("label_zh") or label_en)
        prompt_en = str(detail.get("prompt_en") or detail.get("prompt") or "").strip()
        prompt_zh = str(detail.get("prompt_zh") or prompt_en).strip()
        facet = str(detail.get("facet") or "")
        shots = [p for p in (detail.get("shots") or []) if p]
        if hero_rel:
            shots = [p for p in shots if p != hero_rel]
        analysis_html = (
            f'<p class="detail-analysis"><span class="tag obs" data-i18n="label_analysis">'
            f"Note</span> {_esc(analysis)}</p>"
            if analysis
            else ""
        )
        prompt_html = ""
        if prompt_en or prompt_zh:
            prompt_html = (
                '<details class="prompt-fold">'
                '<summary data-i18n="label_prompt">Prompt</summary>'
                f'<blockquote class="js-lang" data-en="{_esc(prompt_en)}" '
                f'data-zh="{_esc(prompt_zh)}">{_esc(prompt_en)}</blockquote>'
                '<button type="button" class="copy-prompt" data-i18n="copy_prompt">Copy</button>'
                "</details>"
            )
        opened = " open" if facet == "overview" else ""
        return f"""
<details class="detail-card reveal" data-facet="{_esc(facet)}"{opened}>
  <summary class="js-lang" data-en="{_esc(label_en)}" data-zh="{_esc(label_zh)}">{_esc(label_en)}</summary>
  {analysis_html}
  {render_shots(shots, label_en)}
  {render_ba(detail.get('pairs') or [])}
  {prompt_html}
  {render_code(detail.get('code'))}
</details>"""

    def site_heading(site: dict) -> str:
        return str(site.get("domain") or "").strip() or "—"

    def render_site(site: dict, idx: int) -> str:
        hero = site.get("hero")
        name = site_heading(site)
        hero_block = (
            f"""
<figure class="case-hero">
  <img src="{_esc(html_asset_href(str(hero)))}" alt="{_esc(name)}"
       loading="lazy" data-full="{_esc(html_asset_href(str(hero)))}" class="zoomable" />
</figure>"""
            if hero and exists_rel(str(hero))
            else (
                '<div class="case-hero missing" data-i18n="no_hero">'
                "No screenshot available</div>"
            )
        )
        details = [d for d in (site.get("details") or []) if isinstance(d, dict)]
        details_html = "".join(
            render_detail(d, hero_rel=str(hero) if hero else None) for d in details
        )
        if not details_html:
            details_html = (
                '<p class="muted" data-i18n="no_details">No design details stored.</p>'
            )
        url = str(site.get("url") or "")
        link_html = (
            f'<a class="ext-link" href="{_esc(url)}" target="_blank" rel="noopener">'
            f'<span data-i18n="original_site">Original website</span> ↗</a>'
            if url
            else '<span class="muted" data-i18n="no_url">No original website</span>'
        )
        return f"""
<article class="case-study reveal" id="{_esc(site.get('anchor'))}">
  <div class="case-index">Site {idx:02d}</div>
  <div class="case-layout">
    <div class="case-media">{hero_block}</div>
    <div class="case-copy">
      <h3>{_esc(name)}</h3>
      {link_html}
    </div>
  </div>
  <div class="detail-grid">{details_html}</div>
</article>"""

    category_cards = []
    category_sections = []
    site_index = 0
    for cat in categories:
        if not isinstance(cat, dict):
            continue
        cat_sites = [s for s in (cat.get("sites") or []) if isinstance(s, dict)]
        if not cat_sites:
            continue
        cover = cat.get("cover")
        cover_html = (
            f'<img src="{_esc(html_asset_href(str(cover)))}" alt="" loading="lazy" />'
            if cover and exists_rel(str(cover))
            else '<div class="ph" data-i18n="no_hero">No screenshot available</div>'
        )
        count = len(cat_sites)
        category_cards.append(
            f"""
<a class="category-card reveal" href="#{_esc(cat.get('anchor'))}">
  <div class="category-cover">{cover_html}</div>
  <h3 class="js-lang" data-en="{_esc(cat.get('label_en'))}" data-zh="{_esc(cat.get('label_zh'))}">{_esc(cat.get('label_en'))}</h3>
  <p><span class="js-count">{count}</span> <span data-i18n="sites_word">sites</span></p>
</a>"""
        )
        site_cards = []
        site_articles = []
        for site in cat_sites:
            site_index += 1
            name = site_heading(site)
            hero = site.get("hero")
            thumb = (
                f'<img src="{_esc(html_asset_href(str(hero)))}" alt="{_esc(name)}" loading="lazy" />'
                if hero and exists_rel(str(hero))
                else '<div class="ph" data-i18n="no_hero">No screenshot available</div>'
            )
            url = str(site.get("url") or "")
            original = (
                f'<a class="ext-link" href="{_esc(url)}" target="_blank" rel="noopener">'
                f'<span data-i18n="original_site">Original website</span></a>'
                if url
                else '<span class="muted" data-i18n="no_url">No original website</span>'
            )
            site_cards.append(
                f"""
<article class="site-card reveal">
  <a class="site-card-media" href="#{_esc(site.get('anchor'))}">{thumb}</a>
  <div class="site-card-copy">
    <a href="#{_esc(site.get('anchor'))}"><strong>{_esc(name)}</strong></a>
    {original}
  </div>
</article>"""
            )
            site_articles.append(render_site(site, site_index))
        category_sections.append(
            f"""
<section class="category-block" id="{_esc(cat.get('anchor'))}">
  <div class="section-head">
    <h2 class="js-lang" data-en="{_esc(cat.get('label_en'))}" data-zh="{_esc(cat.get('label_zh'))}">{_esc(cat.get('label_en'))}</h2>
    <p><span class="js-count">{count}</span> <span data-i18n="sites_word">sites</span></p>
  </div>
  <div class="site-card-grid">{''.join(site_cards)}</div>
  {''.join(site_articles)}
</section>"""
        )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{_esc(model.get('title'))}</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@500;700;800&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet" />
<style>
:root {{
  --bg: #f3f1ec;
  --bg-2: #e8e4db;
  --ink: #14181c;
  --muted: #5c6570;
  --card: rgba(255,255,255,0.72);
  --line: rgba(20,24,28,0.12);
  --accent: #0f6e6a;
  --accent-2: #d97706;
  --hero-ink: #f6f3ee;
  --shadow: 0 18px 50px rgba(20,24,28,0.12);
  --radius: 18px;
  --font-display: "Syne", sans-serif;
  --font-body: "IBM Plex Sans", sans-serif;
  --font-mono: "IBM Plex Mono", monospace;
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0;
  color: var(--ink);
  font-family: var(--font-body);
  background:
    radial-gradient(1200px 600px at 10% -10%, rgba(15,110,106,0.12), transparent 55%),
    radial-gradient(900px 500px at 90% 0%, rgba(217,119,6,0.10), transparent 50%),
    linear-gradient(180deg, #f7f5f0 0%, var(--bg) 40%, #ebe7de 100%);
  line-height: 1.55;
}}
a {{ color: inherit; }}
.topnav {{
  position: sticky; top: 0; z-index: 40;
  display: flex; gap: 0.75rem; align-items: center; justify-content: space-between;
  padding: 0.7rem 1.25rem;
  backdrop-filter: blur(14px);
  background: rgba(243,241,236,0.92);
  border-bottom: 1px solid var(--line);
  flex-wrap: nowrap;
}}
.brand {{ font-family: var(--font-display); font-weight: 700; letter-spacing: -0.03em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 48vw; }}
.nav-style {{ text-decoration: none; color: var(--muted); font-size: 0.85rem; }}
.nav-style:hover {{ color: var(--accent); }}
.category-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 1rem;
  margin-top: 0.5rem;
}}
.category-card {{
  display: block;
  text-decoration: none;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 16px;
  overflow: hidden;
  color: inherit;
}}
.category-card:hover {{ border-color: var(--accent); }}
.category-cover img, .site-card-media img {{
  width: 100%; height: 140px; object-fit: cover; display: block; background: #ddd8ce;
}}
.category-card h3 {{
  font-family: var(--font-display);
  margin: 0.7rem 0.85rem 0.2rem;
  font-size: 1.05rem;
}}
.category-card p {{
  margin: 0 0.85rem 0.9rem;
  color: var(--muted);
  font-size: 0.82rem;
}}
.category-block {{
  max-width: 1200px;
  margin: 0 auto;
  padding: 1.4rem 1.5rem 2rem;
}}
.site-card-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 1rem;
  margin-bottom: 1.4rem;
}}
.site-card {{
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 16px;
  overflow: hidden;
}}
.site-card-copy {{
  padding: 0.7rem 0.85rem 0.9rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}}
.site-card-copy a {{ text-decoration: none; color: inherit; }}
.site-card-copy .ext-link {{ color: var(--accent); font-size: 0.82rem; }}
.hero {{
  min-height: 0;
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  gap: 1.4rem;
  padding: 1.5rem 1.5rem 1.1rem;
  max-width: 1200px;
  margin: 0 auto;
  align-items: end;
}}
.hero-copy h1 {{
  font-family: var(--font-display);
  font-size: clamp(1.7rem, 4vw, 3rem);
  line-height: 1.02;
  letter-spacing: -0.045em;
  margin: 0.3rem 0 0.7rem;
}}
.hero-meta {{
  display: flex; flex-wrap: wrap; gap: 0.5rem 0.75rem;
  color: var(--muted); font-size: 0.92rem;
}}
.pill {{
  border: 1px solid var(--line);
  background: var(--card);
  border-radius: 999px;
  padding: 0.25rem 0.7rem;
  font-family: var(--font-mono);
  font-size: 0.78rem;
}}
.lede {{
  max-width: 38rem;
  font-size: 1rem;
  color: var(--muted);
  margin: 0.7rem 0 0;
}}
.hero-visual {{
  border-radius: 24px;
  overflow: hidden;
  box-shadow: var(--shadow);
  border: 1px solid var(--line);
  background: #ddd8ce;
  min-height: 180px;
  position: relative;
}}
.hero-visual img {{
  width: 100%; height: 100%; object-fit: cover; display: block;
  max-height: 240px;
  transform: scale(1.02);
  transition: transform 0.8s ease;
}}
.hero-visual:hover img {{ transform: scale(1.06); }}
.hero-visual .ph {{
  color: #666; display:grid; place-items:center; height:100%; min-height:180px;
  font-family: var(--font-mono); font-size: 0.85rem;
}}
.section {{
  max-width: 1200px;
  margin: 0 auto;
  padding: 1.6rem 1.5rem 2.4rem;
}}
.section h2 {{
  font-family: var(--font-display);
  font-size: clamp(1.8rem, 3vw, 2.6rem);
  letter-spacing: -0.03em;
  margin: 0 0 1.25rem;
}}
.section-head {{
  display: flex; justify-content: space-between; gap: 1rem; align-items: end;
  margin-bottom: 1.5rem; flex-wrap: wrap;
}}
.section-head p {{ color: var(--muted); max-width: 36rem; margin: 0; }}
.tag {{
  display: inline-block;
  font-size: 0.68rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  border-radius: 6px;
  padding: 0.15rem 0.45rem;
  margin-right: 0.35rem;
}}
.tag.obs {{ background: rgba(217,119,6,0.14); color: #9a5b05; }}
.eyebrow {{
  font-family: var(--font-mono);
  font-size: 0.75rem;
  color: var(--muted);
  margin-bottom: 0.55rem;
}}
.case-rail {{
  display: flex; gap: 0.75rem; overflow-x: auto; padding-bottom: 0.5rem;
  margin-bottom: 1rem;
}}
.case-rail a {{
  flex: 0 0 auto;
  text-decoration: none;
  border: 1px solid var(--line);
  background: #fff;
  border-radius: 999px;
  padding: 0.35rem 0.8rem;
  font-size: 0.82rem;
  color: var(--muted);
}}
.case-rail a:hover {{ color: var(--accent); border-color: var(--accent); }}
.case-study {{
  margin: 1.5rem 0 2.5rem;
  padding: 1.25rem;
  border-radius: 28px;
  background: linear-gradient(160deg, rgba(255,255,255,0.9), rgba(255,255,255,0.55));
  border: 1px solid var(--line);
  box-shadow: var(--shadow);
}}
.case-index {{
  font-family: var(--font-mono);
  color: var(--muted);
  margin-bottom: 0.75rem;
}}
.case-layout {{
  display: grid;
  grid-template-columns: 1.05fr 0.95fr;
  gap: 1.25rem;
}}
@media (max-width: 900px) {{
  .hero {{ grid-template-columns: 1fr; min-height: auto; }}
  .case-layout {{ grid-template-columns: 1fr; }}
}}
.case-hero {{
  margin: 0;
  border-radius: 20px;
  overflow: hidden;
  background: #ddd8ce;
  border: 1px solid var(--line);
  min-height: 180px;
}}
.case-hero img {{
  width: 100%; display: block; aspect-ratio: 16/11; object-fit: cover;
  max-height: 280px;
  transition: transform 0.5s ease;
}}
.case-hero:hover img {{ transform: scale(1.03); }}
.case-hero.missing {{
  display:grid; place-items:center; color:#999; font-family: var(--font-mono);
  min-height: 180px; background: var(--bg-2);
}}
.case-copy h3 {{
  font-family: var(--font-display);
  font-size: 1.7rem;
  letter-spacing: -0.03em;
  margin: 0 0 0.35rem;
}}
.case-id {{ margin: 0 0 0.6rem; }}
.ext-link {{
  display: inline-block;
  color: var(--accent);
  font-weight: 600;
  text-decoration: none;
  margin-bottom: 1rem;
}}
.ext-link:hover {{ text-decoration: underline; }}
.detail-grid {{
  display: grid;
  gap: 0.9rem;
  margin-top: 1.2rem;
}}
.detail-card {{
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 0.15rem 1.1rem 0.35rem;
}}
.detail-card > summary {{
  cursor: pointer;
  list-style: none;
  font-family: var(--font-display);
  font-size: 1.05rem;
  letter-spacing: -0.02em;
  padding: 0.85rem 0;
}}
.detail-card > summary::-webkit-details-marker {{ display: none; }}
.detail-card > summary::after {{
  content: "+";
  float: right;
  color: var(--muted);
  font-weight: 500;
}}
.detail-card[open] > summary::after {{ content: "–"; }}
.detail-card:not([open]) {{ padding-bottom: 0.15rem; }}
.detail-card[open] {{ padding-bottom: 1.05rem; }}
.detail-analysis {{ font-size: 0.95rem; margin: 0 0 0.7rem; }}
.prompt-fold, .code-fold {{
  margin: 0.7rem 0 0.4rem;
  border: 1px dashed var(--line);
  border-radius: 12px;
  padding: 0.35rem 0.7rem 0.55rem;
}}
.prompt-fold summary, .code-fold summary {{
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  color: var(--muted);
  padding: 0.35rem 0;
}}
.prompt-fold blockquote {{
  margin: 0;
  padding: 0.55rem 0.7rem;
  border-left: 3px solid var(--accent);
  background: rgba(15,110,106,0.06);
  font-size: 0.88rem;
  white-space: pre-wrap;
}}
.copy-prompt {{
  margin-top: 0.45rem;
  border: 1px solid var(--line);
  background: #fff;
  border-radius: 999px;
  padding: 0.2rem 0.7rem;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  cursor: pointer;
}}
@media (max-width: 700px) {{
  .topnav {{ padding: 0.65rem 1rem; }}
  .hero {{ padding-top: 1.4rem; }}
}}
.detail-shot {{
  width: 100%;
  max-height: 280px;
  object-fit: cover;
  border-radius: 12px;
  border: 1px solid var(--line);
  margin: 0.35rem 0 0.7rem;
}}
.prompt-block blockquote {{
  margin: 0;
  padding: 0.7rem 0.85rem;
  border-left: 3px solid var(--accent);
  background: rgba(15,110,106,0.06);
  font-size: 0.9rem;
  white-space: pre-wrap;
}}
.code-block {{
  margin: 0;
  padding: 0.75rem 0.85rem;
  border-radius: 10px;
  background: #14181c;
  color: #f6f3ee;
  overflow-x: auto;
  font-family: var(--font-mono);
  font-size: 0.8rem;
  line-height: 1.45;
}}
.ba {{
  margin: 0.9rem 0;
  padding: 0.8rem;
  border-radius: 16px;
  background: rgba(20,24,28,0.03);
  border: 1px solid var(--line);
}}
.ba-label {{
  font-family: var(--font-mono);
  font-size: 0.75rem;
  color: var(--muted);
  margin-bottom: 0.55rem;
}}
.ba-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.65rem;
}}
.ba-grid figure {{ margin: 0; }}
.ba-grid img {{
  width: 100%;
  aspect-ratio: 4/3;
  object-fit: cover;
  border-radius: 12px;
  border: 1px solid var(--line);
  cursor: zoom-in;
}}
.ba-grid figcaption {{
  font-size: 0.75rem;
  color: var(--muted);
  margin-top: 0.25rem;
  font-family: var(--font-mono);
}}
.obs-line {{ font-size: 0.92rem; margin: 0.65rem 0 0; }}
.muted {{ color: var(--muted); }}
code {{
  font-family: var(--font-mono);
  font-size: 0.82em;
  background: rgba(20,24,28,0.06);
  padding: 0.1rem 0.3rem;
  border-radius: 4px;
}}
.footer {{
  max-width: 1200px; margin: 0 auto; padding: 2rem 1.5rem 3.5rem;
  color: var(--muted); font-size: 0.85rem;
  border-top: 1px solid var(--line);
}}
.lightbox {{
  position: fixed; inset: 0; display: none; place-items: center;
  background: rgba(10,12,14,0.82); z-index: 80; padding: 1.5rem;
}}
.lightbox.open {{ display: grid; }}
.lightbox img {{
  max-width: min(1100px, 94vw);
  max-height: 88vh;
  border-radius: 12px;
  box-shadow: 0 20px 80px rgba(0,0,0,0.45);
}}
.lightbox button {{
  position: absolute; top: 1rem; right: 1rem;
  border: 0; border-radius: 999px;
  padding: 0.55rem 0.9rem;
  cursor: pointer;
  font-family: var(--font-body);
}}
.reveal {{
  opacity: 0; transform: translateY(16px);
  transition: opacity 0.55s ease, transform 0.55s ease;
}}
.reveal.in {{ opacity: 1; transform: none; }}
.zoomable {{ cursor: zoom-in; }}
.lang-switch {{
  display: inline-flex; gap: 0.25rem; align-items: center;
  border: 1px solid var(--line); border-radius: 999px; padding: 0.15rem;
  background: #fff;
}}
.lang-switch button {{
  border: 0; background: transparent; cursor: pointer;
  font-family: var(--font-mono); font-size: 0.75rem;
  padding: 0.25rem 0.55rem; border-radius: 999px; color: var(--muted);
}}
.lang-switch button.active {{
  background: var(--ink); color: #fff;
}}
</style>
</head>
<body data-lang="en">
<header class="topnav">
  <div class="brand" data-i18n="brand">Weekly Web Research</div>
  <a class="nav-style" href="#style" data-i18n="nav_style">Styles</a>
  <div class="lang-switch" role="group" aria-label="Language">
    <button type="button" data-lang-btn="en" class="active">EN</button>
    <button type="button" data-lang-btn="zh">中文</button>
  </div>
</header>

<section class="hero">
  <div class="hero-copy">
    <div class="pill"><span data-i18n="hero_pill">Web design style reference library</span> · { _esc(model.get('report_version')) }</div>
    <h1 data-i18n="h_style">Styles</h1>
    <div class="hero-meta">
      <span class="pill"><span class="js-count">{_esc(len(categories))}</span> <span data-i18n="styles_word">styles</span></span>
      <span class="pill"><span class="js-count">{_esc(len(sites))}</span> <span data-i18n="sites_word">sites</span></span>
      <span class="pill">{_esc(model.get('generated_at'))}</span>
    </div>
    <p class="lede">{_esc(model.get('scope') or model.get('goal'))}</p>
  </div>
  <div class="hero-visual">
    {f'<img src="{_esc(hero_src)}" alt="Hero evidence" class="zoomable" data-full="{_esc(hero_src)}" />' if hero_src else '<div class="ph" data-i18n="no_hero">No screenshot available</div>'}
  </div>
</section>

<section class="section" id="style">
  <div class="section-head">
    <h2 data-i18n="h_style">Styles</h2>
    <p data-i18n="p_style">Pick a style, then open the sites in that collection.</p>
  </div>
  <div class="category-grid">{''.join(category_cards)}</div>
</section>
{''.join(category_sections)}

<footer class="footer">
  <span data-i18n="footer">Generated locally by weekly-web-research-agent · images referenced from screenshots/ · missing assets are skipped without failing the report.</span>
</footer>

<div class="lightbox" id="lightbox" aria-hidden="true">
  <button type="button" id="lightbox-close">Close</button>
  <img alt="Preview" id="lightbox-img" />
</div>

<script>
(() => {{
  const I18N = {{
    en: {{
      brand: "Weekly Web Research",
      nav_style: "Styles",
      hero_pill: "Web design style reference library",
      sites_word: "sites",
      styles_word: "styles",
      no_hero: "No screenshot available",
      h_style: "Styles",
      p_style: "Pick a style, then open the sites in that collection.",
      original_site: "Original website",
      no_url: "No original website",
      no_details: "No design details stored.",
      label_analysis: "Note",
      label_prompt: "Prompt",
      label_code: "Code",
      tag_obs: "Observation",
      ba: "Before / After",
      before: "Before",
      after: "After",
      copy_prompt: "Copy",
      footer: "Generated locally by weekly-web-research-agent · images referenced from screenshots/ · missing assets are skipped without failing the report.",
      close: "Close"
    }},
    zh: {{
      brand: "每周网页研究",
      nav_style: "风格",
      hero_pill: "网页设计风格参考库",
      sites_word: "个参考网站",
      styles_word: "种风格",
      no_hero: "暂无截图",
      h_style: "风格分类",
      p_style: "先选风格，再看这一类里的网站。",
      original_site: "原网站",
      no_url: "无原网站链接",
      no_details: "暂无设计细节。",
      label_analysis: "说明",
      label_prompt: "提示词",
      label_code: "代码",
      tag_obs: "观察",
      ba: "对比",
      before: "之前",
      after: "之后",
      copy_prompt: "复制",
      footer: "由 weekly-web-research-agent 本地生成 · 图片引用 screenshots/ · 缺失资源会跳过且不导致整份报告失败。",
      close: "关闭"
    }}
  }};

  const applyLang = (lang) => {{
    const dict = I18N[lang] || I18N.en;
    document.body.setAttribute("data-lang", lang);
    document.documentElement.setAttribute("lang", lang === "zh" ? "zh-CN" : "en");
    document.querySelectorAll("[data-i18n]").forEach((el) => {{
      const key = el.getAttribute("data-i18n");
      if (key && dict[key] != null) el.textContent = dict[key];
    }});
    document.querySelectorAll(".js-lang").forEach((el) => {{
      const text = lang === "zh" ? el.getAttribute("data-zh") : el.getAttribute("data-en");
      if (text != null) el.textContent = text;
    }});
    const closeBtn = document.getElementById("lightbox-close");
    if (closeBtn) closeBtn.textContent = dict.close;
    document.querySelectorAll("[data-lang-btn]").forEach((btn) => {{
      btn.classList.toggle("active", btn.getAttribute("data-lang-btn") === lang);
    }});
    try {{ localStorage.setItem("wwr_report_lang", lang); }} catch (_) {{}}
  }};

  document.querySelectorAll("[data-lang-btn]").forEach((btn) => {{
    btn.addEventListener("click", () => applyLang(btn.getAttribute("data-lang-btn")));
  }});
  let initial = "en";
  try {{
    const saved = localStorage.getItem("wwr_report_lang");
    if (saved === "zh" || saved === "en") initial = saved;
  }} catch (_) {{}}
  applyLang(initial);

  document.querySelectorAll(".copy-prompt").forEach((btn) => {{
    btn.addEventListener("click", async () => {{
      const fold = btn.closest(".prompt-fold");
      const block = fold ? fold.querySelector("blockquote") : null;
      const text = block ? (block.textContent || "") : "";
      if (!text) return;
      try {{
        await navigator.clipboard.writeText(text);
        btn.textContent = "OK";
        setTimeout(() => {{
          const lang = document.body.getAttribute("data-lang") || "en";
          btn.textContent = (I18N[lang] || I18N.en).copy_prompt;
        }}, 900);
      }} catch (_) {{}}
    }});
  }});

  const lb = document.getElementById('lightbox');
  const img = document.getElementById('lightbox-img');
  const close = () => {{ lb.classList.remove('open'); lb.setAttribute('aria-hidden','true'); }};
  document.getElementById('lightbox-close').addEventListener('click', close);
  lb.addEventListener('click', (e) => {{ if (e.target === lb) close(); }});
  document.addEventListener('keydown', (e) => {{ if (e.key === 'Escape') close(); }});
  document.querySelectorAll('.zoomable').forEach((el) => {{
    el.addEventListener('click', () => {{
      const src = el.getAttribute('data-full') || el.getAttribute('src');
      if (!src) return;
      img.src = src;
      lb.classList.add('open');
      lb.setAttribute('aria-hidden','false');
    }});
  }});
  const io = new IntersectionObserver((entries) => {{
    entries.forEach((en) => {{ if (en.isIntersecting) en.target.classList.add('in'); }});
  }}, {{ threshold: 0.12 }});
  document.querySelectorAll('.reveal').forEach((n) => io.observe(n));
}})();
</script>
</body>
</html>
"""
