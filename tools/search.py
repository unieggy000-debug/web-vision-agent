"""Search tool — real web search via Tavily API."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urldefrag, urlparse, urlunparse

PLACEHOLDER_KEYS = {"", "your_api_key_here"}
ENV_PATH = Path(os.environ.get("VISION_AGENT_ENV_FILE") or (Path(__file__).resolve().parent.parent / ".env"))
DEFAULT_LIMIT = 3
HARD_MAX_LIMIT = 8
FILE_SUFFIXES = (
    ".pdf",
    ".zip",
    ".rar",
    ".7z",
    ".gz",
    ".tgz",
    ".tar",
    ".exe",
    ".dmg",
    ".pkg",
    ".msi",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
)


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


def _tavily_api_key() -> str | None:
    key = _project_env().get("TAVILY_API_KEY") or ""
    if key in PLACEHOLDER_KEYS:
        return None
    return key


def _clamp_limit(limit: int) -> int:
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = DEFAULT_LIMIT
    return max(1, min(n, HARD_MAX_LIMIT))


def _normalize_url(url: str) -> str | None:
    """Return a canonical http(s) URL, or None if unsuitable for open."""
    raw = (url or "").strip()
    if not raw:
        return None

    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        return None
    if not parsed.netloc:
        return None

    path = parsed.path or ""
    lower_path = path.lower()
    # Drop obvious file downloads (ignore query string for suffix check).
    for suffix in FILE_SUFFIXES:
        if lower_path.endswith(suffix):
            return None

    # Drop fragment; lowercase host; strip trailing slash (except root).
    no_frag, _ = urldefrag(urlunparse(parsed))
    parsed = urlparse(no_frag)
    path = parsed.path or ""
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    if path == "":
        path = "/"

    normalized = urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            parsed.query,
            "",
        )
    )
    return normalized


def _fail(query: str, error: str) -> dict:
    return {
        "ok": False,
        "query": query or "",
        "results": [],
        "error": error,
    }


def search(query: str, limit: int = DEFAULT_LIMIT) -> dict:
    """
    Real search with Tavily.

    Returns:
      {"ok": bool, "query": str, "results": [...], "error": str|None}
    Never raises to the Agent Loop.
    """
    q = (query or "").strip()
    if not q:
        return _fail(query or "", "Empty query.")

    api_key = _tavily_api_key()
    if not api_key:
        return _fail(
            q,
            "Missing TAVILY_API_KEY. Put a real key in .env then run again.",
        )

    capped = _clamp_limit(limit)

    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=api_key)
        # Request a few extras so filtering/dedupe can still fill `limit`.
        response = client.search(
            query=q,
            max_results=min(HARD_MAX_LIMIT, capped + 4),
            search_depth="basic",
            include_answer=False,
            include_images=False,
            include_raw_content=False,
        )
    except Exception as exc:
        return _fail(q, f"{type(exc).__name__}: {exc}")

    raw_results = []
    if isinstance(response, dict):
        raw_results = response.get("results") or []

    results: list[dict] = []
    seen: set[str] = set()

    for item in raw_results:
        if not isinstance(item, dict):
            continue
        url = _normalize_url(str(item.get("url") or ""))
        if not url:
            continue
        if url in seen:
            continue
        seen.add(url)

        title = (item.get("title") or "").strip() or url
        note = (item.get("content") or item.get("snippet") or "").strip()
        if len(note) > 280:
            note = note[:280] + "..."

        results.append(
            {
                "url": url,
                "title": title,
                "source": "tavily",
                "note": note,
            }
        )
        if len(results) >= capped:
            break

    return {
        "ok": True,
        "query": q,
        "results": results,
        "error": None,
    }
