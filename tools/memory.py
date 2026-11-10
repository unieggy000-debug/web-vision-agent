"""Research memory — Supabase + optional pgvector semantic search."""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urldefrag, urlparse, urlunparse

from tools.embedding import (
    EMBEDDING_DIMENSION,
    EmbeddingUnavailableError,
    build_case_text,
    embed_text,
)
from tools.supabase_client import get_supabase

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = PROJECT_ROOT / "data" / "cases"
MAX_RESULTS = 5
TABLE = "research_cases"
FETCH_LIMIT = 500
DEFAULT_MATCH_THRESHOLD = 0.25
MAX_GET_CASES = 30
CASE_FIELD_CHAR_LIMIT = 900

# Keep legacy helpers available for older skeletons / offline fallback inspection.
MEMORY_PATH = PROJECT_ROOT / "data" / "memory.json"


def load_memory() -> list:
    if not MEMORY_PATH.exists():
        return []
    try:
        with MEMORY_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_memory(records: list) -> None:
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MEMORY_PATH.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def add_record(record: dict) -> None:
    records = load_memory()
    records.append(record)
    save_memory(records)


def _ensure_cases_dir() -> None:
    CASES_DIR.mkdir(parents=True, exist_ok=True)


def normalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    no_frag, _ = urldefrag(raw)
    parsed = urlparse(no_frag)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return raw.lower().rstrip("/")
    path = parsed.path or ""
    if path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            parsed.query,
            "",
        )
    )


def _safe_error(exc: BaseException) -> str:
    """Format errors without leaking secrets from env/messages."""
    text = f"{type(exc).__name__}: {exc}"
    for secret_name in (
        "SUPABASE_KEY",
        "DEEPSEEK_API_KEY",
        "TAVILY_API_KEY",
        "OPENAI_API_KEY",
        "EMBEDDING_API_KEY",
    ):
        text = text.replace(secret_name, "[redacted]")
    text = re.sub(
        r"eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}",
        "[redacted-jwt]",
        text,
    )
    text = re.sub(r"sb_publishable_[A-Za-z0-9_\-]+", "[redacted-key]", text)
    return text


def _has_research_content(case: dict) -> bool:
    visual = case.get("visual") or {}
    interaction = case.get("interaction") or {}
    frontend = case.get("frontend") or {}
    if isinstance(visual, dict) and any(str(v).strip() for v in visual.values()):
        return True
    if isinstance(interaction, dict) and any(
        bool(v) for k, v in interaction.items() if k != "visual_analysis"
    ):
        return True
    if isinstance(interaction, dict) and interaction.get("visual_analysis"):
        return True
    if isinstance(frontend, dict):
        fw = frontend.get("framework") or {}
        libs = frontend.get("libraries") or []
        clues = frontend.get("frontend_clues") or {}
        anim = frontend.get("animation_clues") or []
        if fw.get("name") and fw.get("name") != "unknown":
            return True
        if libs or anim:
            return True
        if any(clues.get(k) for k in ("css", "dom", "media", "scripts")):
            return True
    screenshots = case.get("screenshots") or []
    if screenshots:
        return True
    return False


def _normalize_case(raw: dict, case_id: str, url_normalized: str) -> dict:
    visual = raw.get("visual") if isinstance(raw.get("visual"), dict) else {}
    interaction = raw.get("interaction") if isinstance(raw.get("interaction"), dict) else {}
    frontend = raw.get("frontend") if isinstance(raw.get("frontend"), dict) else {}
    replication = raw.get("replication") if isinstance(raw.get("replication"), dict) else {}
    screenshots = raw.get("screenshots") if isinstance(raw.get("screenshots"), list) else []

    out = {
        "id": case_id,
        "title": str(raw.get("title") or "").strip(),
        "url": url_normalized,
        "screenshots": screenshots,
        "visual": {
            "style": str(visual.get("style") or ""),
            "layout": str(visual.get("layout") or ""),
            "typography": str(visual.get("typography") or ""),
            "color": str(visual.get("color") or ""),
            "spacing": str(visual.get("spacing") or ""),
            "imagery": str(visual.get("imagery") or ""),
            "visual_effects": str(visual.get("visual_effects") or ""),
        },
        "interaction": {
            "scroll": str(interaction.get("scroll") or ""),
            "hover": str(interaction.get("hover") or ""),
            "cursor": str(interaction.get("cursor") or ""),
            "transition": str(interaction.get("transition") or ""),
            "visual_analysis": interaction.get("visual_analysis")
            if isinstance(interaction.get("visual_analysis"), list)
            else [],
        },
        "frontend": {
            "framework": frontend.get("framework")
            if isinstance(frontend.get("framework"), dict)
            else {},
            "libraries": frontend.get("libraries")
            if isinstance(frontend.get("libraries"), list)
            else [],
            "frontend_clues": frontend.get("frontend_clues")
            if isinstance(frontend.get("frontend_clues"), dict)
            else {},
            "animation_clues": frontend.get("animation_clues")
            if isinstance(frontend.get("animation_clues"), list)
            else [],
        },
        "replication": {
            "prompt": str(replication.get("prompt") or ""),
            "difficulty": str(replication.get("difficulty") or ""),
        },
    }

    related_cases = raw.get("related_cases")
    if related_cases is None:
        related_cases = replication.get("related_cases")
    relation = raw.get("relation")
    if relation is None:
        relation = replication.get("relation")
    if isinstance(related_cases, list) and related_cases:
        out["replication"]["related_cases"] = related_cases
    if relation:
        out["replication"]["relation"] = str(relation)
    return out


def _result_case_fields(case: dict) -> dict:
    """Fields that help the Agent compare a candidate against history."""
    return {
        "id": case.get("id") or "",
        "title": case.get("title") or "",
        "url": case.get("url") or "",
        "visual": case.get("visual") if isinstance(case.get("visual"), dict) else {},
        "interaction": case.get("interaction")
        if isinstance(case.get("interaction"), dict)
        else {},
        "frontend": case.get("frontend") if isinstance(case.get("frontend"), dict) else {},
        "replication": case.get("replication")
        if isinstance(case.get("replication"), dict)
        else {},
    }


def _fetch_all_cases() -> list[dict]:
    client = get_supabase()
    response = (
        client.table(TABLE)
        .select("id,title,url,screenshots,visual,interaction,frontend,replication,created_at")
        .order("created_at", desc=True)
        .limit(FETCH_LIMIT)
        .execute()
    )
    rows = response.data or []
    out: list[dict] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(row)
    return out


def _find_by_url(url: str) -> dict | None:
    target = normalize_url(url)
    if not target:
        return None
    try:
        client = get_supabase()
        response = (
            client.table(TABLE)
            .select("id,title,url")
            .eq("url", target)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if rows and isinstance(rows[0], dict):
            return rows[0]
    except Exception:
        pass

    for case in _fetch_all_cases():
        try:
            if normalize_url(str(case.get("url") or "")) == target:
                return case
        except Exception:
            continue
    return None


def _next_case_id() -> str:
    """Randomized ID avoids check-then-insert collisions under parallel workers.

    Legacy numeric IDs remain readable; only new IDs change shape.
    """
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"case_{day}_{secrets.token_hex(6)}"


def _vector_literal(vec: list[float]) -> str:
    """pgvector / PostgREST-friendly literal."""
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


def update_case_embedding(case_id: str, case: dict | None = None) -> dict:
    """
    Build text → embed → write embedding for an existing case.
    Used by save_case and by backfill tests. Never raises.
    """
    try:
        cid = (case_id or "").strip()
        if not cid:
            return {"ok": False, "error": "embedding_unavailable", "detail": "missing case_id"}

        payload = case if isinstance(case, dict) else None
        if payload is None:
            client = get_supabase()
            rows = (
                client.table(TABLE)
                .select("id,title,url,visual,interaction,frontend,replication")
                .eq("id", cid)
                .limit(1)
                .execute()
                .data
                or []
            )
            if not rows:
                return {"ok": False, "error": "embedding_unavailable", "detail": "case not found"}
            payload = rows[0]

        text = build_case_text(payload)
        vec = embed_text(text)
        if len(vec) != EMBEDDING_DIMENSION:
            return {
                "ok": False,
                "error": "embedding_unavailable",
                "detail": f"bad dimension {len(vec)}",
            }

        client = get_supabase()
        client.table(TABLE).update({"embedding": _vector_literal(vec)}).eq("id", cid).execute()
        return {
            "ok": True,
            "case_id": cid,
            "dimension": len(vec),
            "error": None,
        }
    except EmbeddingUnavailableError as exc:
        return {"ok": False, "error": "embedding_unavailable", "detail": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": "embedding_unavailable", "detail": _safe_error(exc)}


def save_case(case: dict | None = None, **kwargs) -> dict:
    """
    Save one researched case to Supabase, then store its embedding.
    Never raises to the Agent Loop. Does not write to local JSON.
    """
    try:
        payload = case if isinstance(case, dict) else None
        if payload is None and isinstance(kwargs.get("case"), dict):
            payload = kwargs["case"]
        if payload is None and kwargs:
            payload = dict(kwargs)
        if not isinstance(payload, dict):
            return {
                "ok": False,
                "saved": False,
                "error": "Missing case object.",
            }

        url = str(payload.get("url") or "").strip()
        if not url:
            return {
                "ok": False,
                "saved": False,
                "error": "Case must include a non-empty url.",
            }
        if not _has_research_content(payload):
            return {
                "ok": False,
                "saved": False,
                "error": (
                    "Case is too incomplete to save. "
                    "Include visual and/or interaction and/or frontend findings."
                ),
            }

        url_normalized = normalize_url(url)
        if not url_normalized:
            return {
                "ok": False,
                "saved": False,
                "error": "Case url could not be normalized.",
            }

        existing = _find_by_url(url_normalized)
        if existing:
            # Do not recompute embedding from a partial id/title/url row:
            # doing so can overwrite an existing full-quality vector.
            return {
                "ok": True,
                "saved": False,
                "reason": "duplicate_url",
                "existing_case_id": existing.get("id") or "",
                "embedding_ok": None,  # existing embedding was not revalidated
                "embedding_error": None,
                "error": None,
            }

        case_id = str(payload.get("id") or "").strip() or _next_case_id()
        try:
            client = get_supabase()
            id_check = (
                client.table(TABLE).select("id").eq("id", case_id).limit(1).execute()
            )
            if id_check.data:
                case_id = _next_case_id()
        except Exception:
            case_id = _next_case_id()

        normalized = _normalize_case(payload, case_id, url_normalized)
        client = get_supabase()
        try:
            client.table(TABLE).insert(normalized).execute()
        except Exception as exc:
            msg = str(exc).lower()
            if "duplicate" in msg or "unique" in msg or "23505" in msg:
                again = _find_by_url(url_normalized)
                return {
                    "ok": True,
                    "saved": False,
                    "reason": "duplicate_url",
                    "existing_case_id": (again or {}).get("id") or "",
                    "error": None,
                }
            raise

        emb = update_case_embedding(case_id, normalized)
        result = {
            "ok": True,
            "saved": True,
            "case_id": case_id,
            "storage": "supabase",
            "embedding_ok": bool(emb.get("ok")),
            "error": None,
        }
        if not emb.get("ok"):
            result["embedding_error"] = emb.get("error") or "embedding_unavailable"
        return result
    except Exception as exc:
        return {
            "ok": False,
            "saved": False,
            "error": _safe_error(exc),
        }


def _case_blob(case: dict) -> str:
    try:
        return json.dumps(case, ensure_ascii=False).lower()
    except Exception:
        return str(case).lower()


def _keyword_search(query: str, limit: int) -> dict:
    words = [w.lower() for w in re.split(r"\s+", query) if len(w) > 1]
    if not words:
        words = [query.lower()]

    cases = _fetch_all_cases()
    scored: list[tuple[int, dict]] = []
    for case in cases:
        try:
            blob = _case_blob(
                {
                    "title": case.get("title"),
                    "url": case.get("url"),
                    "visual": case.get("visual"),
                    "interaction": case.get("interaction"),
                    "frontend": case.get("frontend"),
                    "replication": case.get("replication"),
                }
            )
            hits = [w for w in words if w in blob]
            if not hits:
                continue
            score = len(hits)
            title = str(case.get("title") or "").lower()
            url = str(case.get("url") or "").lower()
            if any(w in title or w in url for w in hits):
                score += 2
            scored.append(
                (
                    score,
                    {
                        **_result_case_fields(case),
                        "similarity": None,
                        "similarity_reason": "Matched keywords: " + ", ".join(hits),
                    },
                )
            )
        except Exception:
            continue

    scored.sort(key=lambda x: x[0], reverse=True)
    return {
        "ok": True,
        "query": query,
        "search_mode": "keyword_fallback",
        "results": [item for _, item in scored[:limit]],
        "error": None,
    }


def _semantic_search(query: str, limit: int, threshold: float) -> dict:
    vec = embed_text(query)
    client = get_supabase()
    response = client.rpc(
        "match_research_cases",
        {
            "query_embedding": _vector_literal(vec),
            "match_threshold": threshold,
            "match_count": limit,
        },
    ).execute()
    rows = response.data or []
    results = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            sim = row.get("similarity")
            similarity = float(sim) if sim is not None else None
        except (TypeError, ValueError):
            similarity = None
        results.append(
            {
                **_result_case_fields(row),
                "similarity": similarity,
                "similarity_reason": (
                    f"Semantic cosine similarity={similarity:.3f}"
                    if similarity is not None
                    else "Semantic match"
                ),
            }
        )
    return {
        "ok": True,
        "query": query,
        "search_mode": "semantic",
        "results": results,
        "error": None,
    }


def search_memory(
    query: str,
    limit: int = MAX_RESULTS,
    match_threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> dict:
    """
    Prefer pgvector semantic search; fall back to keyword search.
    Never raises.
    """
    q = (query or "").strip()
    if not q:
        return {
            "ok": False,
            "query": query or "",
            "search_mode": None,
            "results": [],
            "error": "Empty query.",
        }

    try:
        capped = max(1, min(int(limit), MAX_RESULTS))
    except (TypeError, ValueError):
        capped = MAX_RESULTS

    try:
        thr = float(match_threshold)
    except (TypeError, ValueError):
        thr = DEFAULT_MATCH_THRESHOLD

    try:
        return _semantic_search(q, capped, thr)
    except EmbeddingUnavailableError:
        fallback = _keyword_search(q, capped)
        fallback["embedding_error"] = "embedding_unavailable"
        return fallback
    except Exception as exc:
        fallback = _keyword_search(q, capped)
        fallback["embedding_error"] = _safe_error(exc)
        return fallback


def _truncate_for_llm(value: object, limit: int = CASE_FIELD_CHAR_LIMIT) -> object:
    """Truncate nested text for LLM context only (does not mutate DB rows)."""
    if value is None:
        return value
    if isinstance(value, str):
        text = value.strip()
        return text if len(text) <= limit else text[:limit] + "…"
    if isinstance(value, list):
        return [_truncate_for_llm(v, max(200, limit // 2)) for v in value[:20]]
    if isinstance(value, dict):
        out = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= 24:
                break
            out[str(k)] = _truncate_for_llm(v, max(200, limit // 2))
        return out
    return value


def _public_case_view(row: dict, *, truncate: bool = True) -> dict:
    case = {
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
    }
    if truncate:
        return {
            "id": case["id"],
            "title": case["title"],
            "url": case["url"],
            "screenshots": case["screenshots"][:8],
            "visual": _truncate_for_llm(case["visual"]),
            "interaction": _truncate_for_llm(case["interaction"]),
            "frontend": _truncate_for_llm(case["frontend"]),
            "replication": _truncate_for_llm(case["replication"]),
        }
    return case


def get_research_cases(
    case_ids: list[str] | None = None,
    limit: int = 20,
    *,
    truncate: bool = True,
) -> dict:
    """
    Fetch saved Research Cards from Supabase for synthesis / reporting.
    Never raises. Caps limit at 30. Truncates long fields for LLM context only.
    """
    try:
        try:
            capped = max(1, min(int(limit), MAX_GET_CASES))
        except (TypeError, ValueError):
            capped = 20

        ids: list[str] = []
        if isinstance(case_ids, list):
            ids = [str(x).strip() for x in case_ids if str(x).strip()]
        elif isinstance(case_ids, str) and case_ids.strip():
            ids = [case_ids.strip()]

        client = get_supabase()
        query = client.table(TABLE).select(
            "id,title,url,screenshots,visual,interaction,frontend,replication,created_at"
        )
        if ids:
            query = query.in_("id", ids[:MAX_GET_CASES])
        response = query.order("created_at", desc=True).limit(capped).execute()
        rows = response.data or []
        cases = [
            _public_case_view(row, truncate=truncate)
            for row in rows
            if isinstance(row, dict)
        ]
        if ids and not cases:
            return {
                "ok": False,
                "cases": [],
                "count": 0,
                "error": "no_cases",
                "detail": "No research cases matched the requested ids.",
            }
        if not cases:
            return {
                "ok": False,
                "cases": [],
                "count": 0,
                "error": "no_cases",
                "detail": "No research cases available in memory.",
            }
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
