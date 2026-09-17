"""Research Report / Synthesis helpers.

Turns Research Cards → synthesis JSON → Markdown + HTML.
HTML is the Style Library product surface (Ticket 20).
Markdown keeps Ticket 16 section headings as a compatible archive (Ticket 21).
Never raises to the Agent Loop.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

from agent.prompts import SYNTHESIS_SYSTEM_PROMPT, build_synthesis_prompt
from reports.presentation import (
    build_report_model,
    render_html,
    render_markdown,
    truncate_cases_for_llm,
)
from reports.style_categories import (
    CLASSIFY_SYSTEM_PROMPT,
    build_classify_user_prompt,
    build_visual_classify_payload,
    normalize_style_assignments,
)
from tools.memory import get_research_cases

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"
HTML_DIR = REPORTS_DIR / "html"
ENV_PATH = PROJECT_ROOT / ".env"
PLACEHOLDER_KEYS = {"", "your_api_key_here"}
# Maps case-id key → {"path": md_rel, "html_path": html_rel|None}
_REPORT_CACHE: dict[str, dict[str, str | None]] = {}


def _read_env() -> dict[str, str]:
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


def _llm_client() -> OpenAI:
    env = _read_env()
    key = env.get("DEEPSEEK_API_KEY") or env.get("OPENAI_API_KEY") or ""
    if key in PLACEHOLDER_KEYS:
        raise RuntimeError("Missing API key for synthesis.")
    base = env.get("OPENAI_BASE_URL") or "https://api.deepseek.com"
    return OpenAI(api_key=key, base_url=base)


def _model() -> str:
    return _read_env().get("OPENAI_MODEL") or "deepseek-flash"


def _slugify(text: str) -> str:
    raw = (text or "research").lower()
    raw = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", raw)
    raw = re.sub(r"-+", "-", raw).strip("-")
    return (raw or "research")[:48]


def _case_lookup(cases: list[dict]) -> dict[str, dict]:
    return {str(c.get("id") or ""): c for c in cases if c.get("id")}


def _title_for_id(case_id: str, lookup: dict[str, dict]) -> str:
    case = lookup.get(case_id) or {}
    return str(case.get("title") or case_id)


def _rel(path: Path) -> str:
    return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")


def synthesize_cases(
    cases: list[dict[str, Any]],
    *,
    goal: str = "",
) -> dict[str, Any]:
    """Ask the LLM to compare Research Cards. Returns synthesis JSON or error dict."""
    if not cases:
        return {
            "ok": False,
            "error": "no_cases",
            "synthesis": None,
        }
    try:
        client = _llm_client()
        response = client.chat.completions.create(
            model=_model(),
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_synthesis_prompt(goal=goal, cases=cases),
                },
            ],
            extra_body={"thinking": {"type": "disabled"}},
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {"ok": False, "error": "invalid_synthesis_payload", "synthesis": None}
        for key in (
            "cases_analyzed",
            "common_patterns",
            "key_differences",
            "interaction_patterns",
            "frontend_patterns",
            "notable_findings",
            "replication_ideas",
        ):
            if key not in data or data[key] is None:
                data[key] = []
        if not data.get("title"):
            data["title"] = "Research Synthesis"
        if not data.get("scope"):
            data["scope"] = goal or "Cross-case synthesis of saved research cards."
        if not data.get("cases_analyzed"):
            data["cases_analyzed"] = [
                {"id": c.get("id"), "title": c.get("title")} for c in cases
            ]
        return {"ok": True, "error": None, "synthesis": data}
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "synthesis": None,
        }


def classify_style_categories(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Assign each case to one closed style id from visual analysis only.
    Never writes to Research Cards. Never raises.
    """
    payload = build_visual_classify_payload(cases)
    case_ids = [str(row.get("id") or "") for row in payload if row.get("id")]
    fallback = normalize_style_assignments({}, case_ids)
    if not case_ids:
        return {
            "ok": False,
            "error": "no_cases",
            "assignments": {},
            "payload": [],
        }
    try:
        client = _llm_client()
        response = client.chat.completions.create(
            model=_model(),
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_classify_user_prompt(payload),
                },
            ],
            extra_body={"thinking": {"type": "disabled"}},
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        assignments = normalize_style_assignments(data, case_ids)
        return {
            "ok": True,
            "error": None,
            "assignments": assignments,
            "payload": payload,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "assignments": fallback,
            "payload": payload,
        }


def synthesis_to_markdown(
    synthesis: dict[str, Any],
    cases: list[dict[str, Any]],
    *,
    goal: str = "",
    run_id: str = "",
    style_assignments: dict[str, str] | None = None,
) -> str:
    """Render Markdown archive. Keeps Ticket 16 section headings; not a Style Library."""
    model = build_report_model(
        synthesis,
        cases,
        goal=goal,
        run_id=run_id,
        style_assignments=style_assignments,
    )
    return render_markdown(model)


def synthesis_to_html(
    synthesis: dict[str, Any],
    cases: list[dict[str, Any]],
    *,
    goal: str = "",
    run_id: str = "",
    style_assignments: dict[str, str] | None = None,
) -> str:
    """Render HTML Style Library (categories → sites → details)."""
    model = build_report_model(
        synthesis,
        cases,
        goal=goal,
        run_id=run_id,
        style_assignments=style_assignments,
    )
    return render_html(model)


def write_report_markdown(
    markdown: str,
    *,
    title: str = "research",
    case_ids: list[str] | None = None,
) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = _slugify(title)
    path = REPORTS_DIR / f"report_{stamp}_{slug}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def write_report_html(
    html_text: str,
    *,
    title: str = "research",
    stamp: str | None = None,
) -> Path:
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = _slugify(title)
    path = HTML_DIR / f"report_{stamp}_{slug}.html"
    path.write_text(html_text, encoding="utf-8")
    return path


def generate_research_report(
    case_ids: list[str] | None = None,
    limit: int = 10,
    goal: str = "",
    force: bool = False,
    run_id: str = "",
) -> dict[str, Any]:
    """
    Tool entry: fetch cases → synthesize → write Markdown + HTML report.
    Never raises.
    """
    try:
        try:
            capped = max(1, min(int(limit), 30))
        except (TypeError, ValueError):
            capped = 10

        ids = None
        if isinstance(case_ids, list):
            ids = [str(x).strip() for x in case_ids if str(x).strip()]
        elif isinstance(case_ids, str) and case_ids.strip():
            ids = [case_ids.strip()]

        cache_key = ",".join(sorted(ids or []))
        if cache_key and not force and cache_key in _REPORT_CACHE:
            cached = _REPORT_CACHE[cache_key]
            return {
                "ok": True,
                "reused": True,
                "path": cached.get("path"),
                "html_path": cached.get("html_path"),
                "case_ids": ids or [],
                "error": None,
            }

        fetched = get_research_cases(case_ids=ids, limit=capped, truncate=False)
        if not fetched.get("ok"):
            return {
                "ok": False,
                "path": None,
                "html_path": None,
                "synthesis": None,
                "case_ids": ids or [],
                "error": fetched.get("error") or "no_cases",
                "detail": fetched.get("detail"),
            }

        cases = fetched.get("cases") or []
        llm_cases = truncate_cases_for_llm(cases)
        syn = synthesize_cases(llm_cases, goal=goal)
        if not syn.get("ok") or not isinstance(syn.get("synthesis"), dict):
            return {
                "ok": False,
                "path": None,
                "html_path": None,
                "synthesis": None,
                "case_ids": [c.get("id") for c in cases],
                "error": syn.get("error") or "synthesis_failed",
            }

        synthesis = syn["synthesis"]
        classified = classify_style_categories(cases)
        assignments = classified.get("assignments") if isinstance(classified, dict) else {}
        if not isinstance(assignments, dict):
            assignments = {}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        title = str(synthesis.get("title") or "research")

        md = synthesis_to_markdown(
            synthesis,
            cases,
            goal=goal,
            run_id=run_id,
            style_assignments=assignments,
        )
        path = write_report_markdown(md, title=title)
        rel = _rel(path)

        html_rel = None
        try:
            html_text = synthesis_to_html(
                synthesis,
                cases,
                goal=goal,
                run_id=run_id,
                style_assignments=assignments,
            )
            html_path = write_report_html(html_text, title=title, stamp=stamp)
            html_rel = _rel(html_path)
        except Exception:
            html_rel = None

        id_list = [str(c.get("id") or "") for c in cases]
        if cache_key:
            _REPORT_CACHE[cache_key] = {"path": rel, "html_path": html_rel}

        return {
            "ok": True,
            "reused": False,
            "path": rel,
            "html_path": html_rel,
            "title": synthesis.get("title"),
            "case_ids": id_list,
            "cases_count": len(cases),
            "synthesis": synthesis,
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "path": None,
            "html_path": None,
            "synthesis": None,
            "error": f"{type(exc).__name__}: {exc}",
        }
