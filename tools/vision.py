"""Vision tool — analyze a saved screenshot with DeepSeek multimodal."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path

from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = Path(os.environ.get("VISION_AGENT_ENV_FILE") or (PROJECT_ROOT / ".env"))
PLACEHOLDER_KEYS = {"", "your_api_key_here"}

ANALYSIS_KEYS = (
    "style",
    "layout",
    "typography",
    "color",
    "spacing",
    "imagery",
    "visual_effects",
)

ALLOWED_ANIMATION_TYPES = {
    "scale",
    "opacity",
    "color change",
    "position change",
    "reveal",
    "overlay",
    "sticky navigation",
    "parallax-like movement",
    "transition",
    "none",
    "unknown",
}

VISION_SYSTEM = """
You are a web design visual analyst.
Inspect the screenshot and return ONLY a JSON object with these string fields:
style, layout, typography, color, spacing, imagery, visual_effects.

Rules:
- Focus on visual design only (not code, not interaction).
- Be concrete and short (1-3 sentences per field).
- If unsure, say so; do not invent details you cannot see.
- For style, you may mention labels like minimal/editorial/brutalist/futuristic/playful/corporate only when justified.
- Observe layout (hero, grid, columns, cards, nav), typography (serif/sans, hierarchy, weight), color (dominant/accent/contrast), spacing (whitespace/density), imagery (photo/illustration/3D/gradient/texture), visual_effects (blur/grain/glass/shadow/overlay/oversized type).
- No markdown fences. JSON object only.
""".strip()

INTERACTION_VISION_SYSTEM = """
You compare BEFORE and AFTER screenshots of the same webpage interaction.
Return ONLY a JSON object with:
changed (boolean),
effect (string),
elements_changed (string),
animation_type (string),
confidence (string: high|medium|low),
evidence (string).

Rules:
- Base every claim ONLY on visible differences between the two images.
- If no clear difference, set changed=false, effect="No obvious visual change detected", animation_type="none".
- animation_type must be one of: scale, opacity, color change, position change, reveal, overlay, sticky navigation, parallax-like movement, transition, none, unknown.
- Describe visual phenomena only. Do NOT invent libraries or implementation (no GSAP, CSS, WebGL, Three.js guesses).
- Prefer "not detected" / "unknown" over speculation.
- No markdown fences. JSON object only.
""".strip()


def _project_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip("'\"")
    return values


def _api_key() -> str | None:
    key = _project_env().get("DEEPSEEK_API_KEY") or _project_env().get("OPENAI_API_KEY") or ""
    if key in PLACEHOLDER_KEYS:
        return None
    return key


def _model() -> str:
    return _project_env().get("OPENAI_MODEL") or "deepseek-flash"


def _base_url() -> str:
    return _project_env().get("OPENAI_BASE_URL") or "https://api.deepseek.com"


def _resolve_path(screenshot_path: str) -> Path | None:
    raw = (screenshot_path or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _to_data_url(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    if mime not in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
        mime = "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _empty_analysis() -> dict[str, str]:
    return {key: "" for key in ANALYSIS_KEYS}


def _normalize_analysis(raw: dict) -> dict[str, str]:
    out = _empty_analysis()
    for key in ANALYSIS_KEYS:
        value = raw.get(key, "")
        if value is None:
            out[key] = ""
        else:
            out[key] = str(value).strip()
    return out


def _fail(screenshot_path: str, error: str) -> dict:
    return {
        "ok": False,
        "screenshot_path": screenshot_path or "",
        "analysis": None,
        "error": error,
    }


def _normalize_interaction_analysis(raw: dict) -> dict:
    changed = bool(raw.get("changed", False))
    effect = str(raw.get("effect") or "").strip()
    elements_changed = str(raw.get("elements_changed") or "").strip()
    animation_type = str(raw.get("animation_type") or "unknown").strip().lower()
    confidence = str(raw.get("confidence") or "low").strip().lower()
    evidence = str(raw.get("evidence") or "").strip()

    if animation_type not in ALLOWED_ANIMATION_TYPES:
        animation_type = "unknown"
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    if not changed:
        if not effect:
            effect = "No obvious visual change detected"
        if animation_type not in {"none", "unknown"}:
            animation_type = "none"
    if not evidence:
        evidence = (
            "not detected"
            if not changed
            else "Visible difference between before and after frames."
        )

    return {
        "changed": changed,
        "effect": effect,
        "elements_changed": elements_changed or "not detected",
        "animation_type": animation_type,
        "confidence": confidence,
        "evidence": evidence,
    }


def analyze_visual(screenshot_path: str) -> dict:
    """Analyze a local PNG screenshot with DeepSeek vision. Never raises."""
    display_path = (screenshot_path or "").strip()
    path = _resolve_path(display_path)
    if path is None:
        return _fail(display_path, "Empty screenshot_path.")
    if not path.is_file():
        return _fail(display_path, f"Screenshot file not found: {display_path}")

    api_key = _api_key()
    if not api_key:
        return _fail(
            display_path,
            "Missing DEEPSEEK_API_KEY. Put a real key in .env then run again.",
        )

    try:
        data_url = _to_data_url(path)
        client = OpenAI(api_key=api_key, base_url=_base_url())
        response = client.chat.completions.create(
            model=_model(),
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": VISION_SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Analyze this webpage screenshot for visual design. "
                                "Return JSON with keys: style, layout, typography, "
                                "color, spacing, imagery, visual_effects."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url, "detail": "high"},
                        },
                    ],
                },
            ],
            extra_body={"thinking": {"type": "disabled"}},
        )
        raw_text = response.choices[0].message.content or "{}"
        parsed = json.loads(raw_text)
        if not isinstance(parsed, dict):
            return _fail(display_path, "Vision model returned non-object JSON.")

        return {
            "ok": True,
            "screenshot_path": display_path,
            "analysis": _normalize_analysis(parsed),
            "error": None,
        }
    except Exception as exc:
        return _fail(display_path, f"{type(exc).__name__}: {exc}")


def analyze_interaction(
    before_path: str,
    after_path: str,
    interaction_type: str = "hover",
) -> dict:
    """Compare before/after interaction screenshots. Never raises."""
    before_display = (before_path or "").strip()
    after_display = (after_path or "").strip()
    itype = (interaction_type or "unknown").strip().lower() or "unknown"

    before = _resolve_path(before_display)
    after = _resolve_path(after_display)
    if before is None or after is None:
        return {
            "ok": False,
            "interaction_type": itype,
            "before_path": before_display,
            "after_path": after_display,
            "analysis": None,
            "error": "Empty before_path or after_path.",
        }
    if not before.is_file() or not after.is_file():
        return {
            "ok": False,
            "interaction_type": itype,
            "before_path": before_display,
            "after_path": after_display,
            "analysis": None,
            "error": "Before/after screenshot file not found.",
        }

    api_key = _api_key()
    if not api_key:
        return {
            "ok": False,
            "interaction_type": itype,
            "before_path": before_display,
            "after_path": after_display,
            "analysis": None,
            "error": "Missing DEEPSEEK_API_KEY. Put a real key in .env then run again.",
        }

    try:
        client = OpenAI(api_key=api_key, base_url=_base_url())
        response = client.chat.completions.create(
            model=_model(),
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": INTERACTION_VISION_SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"Interaction type: {itype}. "
                                "Image 1 is BEFORE. Image 2 is AFTER. "
                                "Compare only visible differences. "
                                "Return JSON with changed, effect, elements_changed, "
                                "animation_type, confidence, evidence."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": _to_data_url(before),
                                "detail": "high",
                            },
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": _to_data_url(after),
                                "detail": "high",
                            },
                        },
                    ],
                },
            ],
            extra_body={"thinking": {"type": "disabled"}},
        )
        raw_text = response.choices[0].message.content or "{}"
        parsed = json.loads(raw_text)
        if not isinstance(parsed, dict):
            return {
                "ok": False,
                "interaction_type": itype,
                "before_path": before_display,
                "after_path": after_display,
                "analysis": None,
                "error": "Vision model returned non-object JSON.",
            }

        return {
            "ok": True,
            "interaction_type": itype,
            "before_path": before_display,
            "after_path": after_display,
            "analysis": _normalize_interaction_analysis(parsed),
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "interaction_type": itype,
            "before_path": before_display,
            "after_path": after_display,
            "analysis": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def analyze_screenshot(image_path: str) -> dict:
    return analyze_visual(image_path)
