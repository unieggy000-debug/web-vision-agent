"""Closed style taxonomy and visual-only classification helpers.

Does not write back to Research Cards. Does not inspect title / URL / frontend.
Ticket 27: visual-style vocabulary (10 classes + other). immersive_3d is not a style.
"""

from __future__ import annotations

import json
from typing import Any

# (id, label_en, label_zh) — Home / Style labels only. Definitions live alongside.
STYLE_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("minimal", "Minimal", "极简"),
    ("editorial", "Editorial", "编辑排版"),
    ("brutalist", "Brutalist", "粗野主义"),
    ("corporate", "Corporate", "商务品牌"),
    ("luxury", "Luxury", "奢侈精致"),
    ("futuristic", "Futuristic", "未来感"),
    ("playful", "Playful", "趣味玩法"),
    ("experimental", "Experimental", "实验艺术"),
    ("organic", "Organic", "自然有机"),
    ("dark_cinematic", "Dark Cinematic", "暗黑电影感"),
    ("other", "Other", "其他"),
)

STYLE_CATEGORY_IDS: frozenset[str] = frozenset(item[0] for item in STYLE_CATEGORIES)
DEFAULT_STYLE_CATEGORY = "other"

# Spec definitions: whole-site visual atmosphere, not technique / type / layout.
STYLE_DEFINITIONS: dict[str, tuple[str, str]] = {
    "minimal": (
        "Sparse decoration, generous whitespace, restrained; the interface almost disappears.",
        "少装饰、大留白、克制、界面几乎隐形。",
    ),
    "editorial": (
        "Magazine / content narrative; hierarchy and typesetting are the main event.",
        "杂志/内容叙事、图文层级、排版是主角。",
    ),
    "brutalist": (
        "Raw, exposed, anti-polish; deliberately not conventionally pretty.",
        "粗、裸、反精致、故意不「好看」。",
    ),
    "corporate": (
        "Clean, credible, product- or company-site atmosphere.",
        "干净、可信、产品/公司官网气质。",
    ),
    "luxury": (
        "Fashion, material, refined density; haute-couture calm.",
        "时尚、材质、精致疏密，偏高定。",
    ),
    "futuristic": (
        "Tech, sci-fi, digital light (including neon / cyber leanings).",
        "科技、科幻、数字光感（含霓虹/赛博倾向）。",
    ),
    "playful": (
        "Toy-like, gameful, cheeky — not a serious portfolio.",
        "玩具感、游戏化、俏皮，不像严肃作品集。",
    ),
    "experimental": (
        "Unconventional narrative, art-installation feel; not playful, not a cinematic epic.",
        "非常规叙事、艺术装置感，但不趣味、不电影大片。",
    ),
    "organic": (
        "Natural materials, architecture / landscape, organic form (including architecture portfolios).",
        "自然材质、建筑/风景、有机形态（含建筑作品集方向）。",
    ),
    "dark_cinematic": (
        "Dark ground, dramatic light, cinematic framing.",
        "暗背景、戏剧光、电影镜头感。",
    ),
    "other": (
        "Does not clearly match any class above, or visual evidence is too thin.",
        "不够像上面任何一类，或视觉证据不足。",
    ),
}

VISUAL_CLASSIFY_KEYS: tuple[str, ...] = (
    "style",
    "layout",
    "typography",
    "color",
    "spacing",
    "imagery",
    "visual_effects",
)

CLASSIFY_SYSTEM_PROMPT = """
You assign each research case to exactly one web-design style category.

Use only the visual fields provided (style, layout, typography, color, spacing,
imagery, visual_effects). Do not infer from site names, URLs, frameworks, or libraries.
If those appear inside visual text as a seen effect (for example a WebGL scene),
you may use that as a visual clue. Do not invent categories.
A visible 3D scene is a visual clue, not its own category.

Choose one id from this closed list:
minimal, editorial, brutalist, corporate, luxury, futuristic, playful,
experimental, organic, dark_cinematic, other.

Guidance:
- dark_cinematic: dramatic dark light, film-still atmosphere.
- futuristic: sci-fi / tech world (including neon / cyber leanings).
- playful: fun, toy-like, gameful.
- experimental: hard-to-read art experiment, not playful and not a cinematic epic.
- editorial: magazine / content-led typesetting (including sport-editorial graphics).
- When unsure, or visual fields are empty, use other.

Return ONLY a JSON object:
{"assignments": [{"id": "<case id>", "category": "<id>"}]}
""".strip()


def category_labels(category_id: str) -> tuple[str, str]:
    for key, label_en, label_zh in STYLE_CATEGORIES:
        if key == category_id:
            return label_en, label_zh
    return "Other", "其他"


def category_definition(category_id: str) -> tuple[str, str]:
    pair = STYLE_DEFINITIONS.get(category_id) or STYLE_DEFINITIONS[DEFAULT_STYLE_CATEGORY]
    return pair[0], pair[1]


def build_visual_classify_payload(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build LLM input: case id + visual analysis fields only."""
    rows: list[dict[str, Any]] = []
    for case in cases or []:
        if not isinstance(case, dict):
            continue
        cid = str(case.get("id") or "").strip()
        if not cid:
            continue
        visual = case.get("visual") if isinstance(case.get("visual"), dict) else {}
        visual_out: dict[str, str] = {}
        for key in VISUAL_CLASSIFY_KEYS:
            text = str(visual.get(key) or "").strip()
            if text:
                visual_out[key] = text
        rows.append({"id": cid, "visual": visual_out})
    return rows


def _parse_raw_assignments(raw: Any) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    if isinstance(raw, dict) and "assignments" in raw:
        raw = raw.get("assignments")
    if isinstance(raw, dict):
        for cid, category in raw.items():
            items.append((str(cid).strip(), str(category or "").strip()))
        return items
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("id") or item.get("case_id") or "").strip()
            category = str(item.get("category") or item.get("style") or "").strip()
            if cid:
                items.append((cid, category))
    return items


def normalize_style_assignments(
    raw: Any,
    case_ids: list[str],
) -> dict[str, str]:
    """Clamp LLM output onto the closed vocab. One category per case; invalid → other."""
    wanted = [str(cid).strip() for cid in case_ids if str(cid).strip()]
    wanted_set = set(wanted)
    seen: dict[str, set[str]] = {cid: set() for cid in wanted}

    for cid, category in _parse_raw_assignments(raw):
        if cid not in wanted_set:
            continue
        key = category.lower().replace(" ", "_").replace("-", "_")
        if key in STYLE_CATEGORY_IDS:
            seen[cid].add(key)
        else:
            seen[cid].add(DEFAULT_STYLE_CATEGORY)

    out: dict[str, str] = {}
    for cid in wanted:
        labels = seen.get(cid) or set()
        labels.discard("")
        if len(labels) == 1:
            out[cid] = next(iter(labels))
        else:
            # missing, invalid-only, or multiple distinct classes → other
            out[cid] = DEFAULT_STYLE_CATEGORY
    return out


def build_classify_user_prompt(payload: list[dict[str, Any]]) -> str:
    return (
        "Classify each case into one closed style id.\n"
        "Visual-only cases:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
