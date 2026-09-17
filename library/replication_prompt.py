"""Deterministic Full Replication Prompt. No LLM expansion."""

from __future__ import annotations

from typing import Any

from reports.presentation import (
    _evidence_strings,
    _framework_code,
    _library_code,
    _pair_facet,
    _user_facing_analysis,
    extract_before_after_pairs,
    site_domain,
)

_SECTION_ORDER = (
    ("overall", "Overall style", "整体风格"),
    ("layout", "Layout and spacing", "布局与留白"),
    ("typography", "Typography", "字体"),
    ("color", "Color", "配色"),
    ("imagery", "Imagery and visual effects", "画面与视觉效果"),
    ("motion", "Motion", "动效"),
    ("scroll", "Scroll", "滚动"),
    ("hover", "Hover and cursor", "悬停与光标"),
    ("other", "Other interaction", "其他互动"),
    ("frontend", "Frontend evidence (confirmed only)", "已确认的前端证据"),
)


def _clean(text: Any) -> str:
    return _user_facing_analysis(str(text or ""))


def _join(*parts: Any) -> str:
    bits: list[str] = []
    for part in parts:
        text = _clean(part)
        if text and text not in bits:
            bits.append(text)
    return " ".join(bits)


def _pair_notes(pairs: list[dict[str, Any]], facet: str) -> str:
    notes: list[str] = []
    for pair in pairs:
        if not isinstance(pair, dict) or not pair.get("content_ok"):
            continue
        if _pair_facet(pair) != facet:
            continue
        obs = _clean(pair.get("observation") or "")
        if obs and obs not in notes:
            notes.append(obs)
    return " ".join(notes)


def _frontend_block(frontend: dict[str, Any], lang: str) -> str:
    lines: list[str] = []
    fw = _framework_code(frontend)
    libs = _library_code(frontend)
    snippets: list[str] = []
    if fw:
        snippets.extend(str(s) for s in (fw.get("snippets") or []) if s)
    if libs:
        snippets.extend(str(s) for s in (libs.get("snippets") or []) if s)
    # Names with evidence only (already gated by _framework_code / _library_code).
    fw_dict = frontend.get("framework") if isinstance(frontend.get("framework"), dict) else {}
    fw_name = str(fw_dict.get("name") or "").strip()
    if fw_name and fw_name.lower() != "unknown" and _evidence_strings(fw_dict.get("evidence")):
        lines.append(fw_name)
    for lib in frontend.get("libraries") or []:
        if not isinstance(lib, dict):
            continue
        name = str(lib.get("name") or "").strip()
        if name and _evidence_strings(lib.get("evidence")):
            lines.append(name)
    if snippets:
        lines.extend(snippets)
    if not lines:
        return ""
    unique: list[str] = []
    for item in lines:
        if item not in unique:
            unique.append(item)
    disclaimer = (
        "If a library is not listed here, do not assume it."
        if lang == "en"
        else "未列出的库不要自行假设。"
    )
    return "\n".join(unique + [disclaimer])


def assemble_replication_prompt(card: dict[str, Any], *, lang: str = "en") -> str:
    """Build one full prompt from a Research Card. Empty sections omitted."""
    if not isinstance(card, dict):
        return ""
    url = str(card.get("url") or "").strip()
    domain = site_domain(url) or url or "this site"
    visual = card.get("visual") if isinstance(card.get("visual"), dict) else {}
    interaction = card.get("interaction") if isinstance(card.get("interaction"), dict) else {}
    frontend = card.get("frontend") if isinstance(card.get("frontend"), dict) else {}
    replication = card.get("replication") if isinstance(card.get("replication"), dict) else {}
    pairs = extract_before_after_pairs(card)

    style = _clean(visual.get("style"))
    extra = _clean(replication.get("prompt"))
    if style and extra and extra not in style:
        overall = _join(style, extra)
    else:
        overall = style or extra

    sections: dict[str, str] = {
        "overall": overall,
        "layout": _join(visual.get("layout"), visual.get("spacing")),
        "typography": _clean(visual.get("typography")),
        "color": _clean(visual.get("color")),
        "imagery": _join(visual.get("imagery"), visual.get("visual_effects")),
        "motion": _join(interaction.get("transition"), _pair_notes(pairs, "animation")),
        "scroll": _join(interaction.get("scroll"), _pair_notes(pairs, "scroll")),
        "hover": _join(
            interaction.get("hover"),
            interaction.get("cursor"),
            _pair_notes(pairs, "hover_cursor"),
        ),
        "other": _pair_notes(pairs, "interaction"),
        "frontend": _frontend_block(frontend, lang),
    }

    if lang == "zh":
        header = (
            f"按 {domain}（{url or '无 URL'}）完整复刻这个网站。\n"
            "只使用下列已观察事实。不要编造库、CSS 或内容。"
        )
    else:
        header = (
            f"Replicate the website at {domain} ({url or 'no url'}) as a complete page.\n"
            "Use only the observed facts below. Do not invent libraries, CSS, or content."
        )

    lines = [header, ""]
    for key, label_en, label_zh in _SECTION_ORDER:
        body = str(sections.get(key) or "").strip()
        if not body:
            continue
        label = label_zh if lang == "zh" else label_en
        lines.append(f"## {label}")
        lines.append(body)
        lines.append("")
    return "\n".join(lines).strip() + "\n"
