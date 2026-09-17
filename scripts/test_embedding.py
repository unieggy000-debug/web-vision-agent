"""Ticket 14 — Embedding + pgvector semantic memory tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.embedding import (
    EMBEDDING_DIMENSION,
    EmbeddingUnavailableError,
    build_case_text,
    embed_text,
)
from tools.memory import (
    normalize_url,
    save_case,
    search_memory,
    update_case_embedding,
)
from tools.supabase_client import get_supabase


def _bruno_case() -> dict:
    return {
        "title": "Bruno Simon Portfolio",
        "url": "https://bruno-simon.com/",
        "screenshots": ["screenshots/bruno.png"],
        "visual": {
            "style": "Playful immersive 3D interactive portfolio",
            "layout": "Full-viewport WebGL scene",
            "typography": "Bold sans-serif overlays",
            "color": "Warm earth tones",
            "spacing": "Open 3D space",
            "imagery": "Car driving through 3D world",
            "visual_effects": "WebGL lighting and shadows",
        },
        "interaction": {
            "scroll": "Keyboard/WASD drive instead of classic scroll",
            "hover": "Objects respond on approach",
            "cursor": "Custom game-like grab controls",
            "transition": "Continuous 3D camera motion",
            "visual_analysis": [],
        },
        "frontend": {
            "framework": {"name": "unknown", "confidence": "low", "evidence": []},
            "libraries": [
                {
                    "name": "Three.js",
                    "confidence": "high",
                    "evidence": ['data-engine="three.js r183 webgpu"'],
                }
            ],
            "frontend_clues": {"scripts": ["three"], "css": [], "dom": [], "media": ["webgl"]},
            "animation_clues": ["requestAnimationFrame game loop", "WebGL canvas"],
        },
        "replication": {
            "prompt": "Build a driveable immersive 3D creative developer portfolio with Three.js",
            "difficulty": "hard",
        },
    }


def test1_embedding() -> None:
    print("=== Test 1: Embedding ===")
    text = "Interactive WebGL portfolio using Three.js"
    vec = embed_text(text)
    assert isinstance(vec, list) and vec, "empty vector"
    assert len(vec) == EMBEDDING_DIMENSION, len(vec)
    print("embedding ok")
    print(f"dimension: {len(vec)}")
    print()


def test2_save_embedding() -> None:
    print("=== Test 2: save / update Bruno embedding ===")
    client = get_supabase()
    case = _bruno_case()
    # save_case will hit duplicate_url for Bruno and refresh embedding.
    r = save_case(case)
    print(json.dumps({k: v for k, v in r.items() if k != "path"}, indent=2, ensure_ascii=False))

    case_id = r.get("existing_case_id") or r.get("case_id")
    if not case_id:
        # Ensure a row exists then backfill.
        rows = (
            client.table("research_cases")
            .select("id,url")
            .limit(50)
            .execute()
            .data
            or []
        )
        target = normalize_url("https://bruno-simon.com/")
        for row in rows:
            if normalize_url(str(row.get("url") or "")) == target:
                case_id = row["id"]
                break
        assert case_id, "Bruno case missing in Supabase"
        emb = update_case_embedding(case_id, case)
        print("backfill:", json.dumps(emb, indent=2))
        assert emb.get("ok"), emb
    else:
        assert r.get("embedding_ok") is True or r.get("saved") is True, r

    rows = (
        client.table("research_cases")
        .select("id,url,embedding")
        .eq("id", case_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    assert rows, "case row missing"
    embedding = rows[0].get("embedding")
    assert embedding not in (None, "", []), f"embedding empty for {case_id}"
    # embedding may come back as string literal from PostgREST
    if isinstance(embedding, str):
        assert embedding.startswith("[") and "," in embedding
        dim = embedding.count(",") + 1
    else:
        dim = len(embedding)
    print(f"supabase embedding present for {case_id}")
    print(f"stored dimension approx: {dim}")
    print("case text preview:")
    print(build_case_text(case)[:240], "...")
    print()


def test3_semantic_zh() -> None:
    print("=== Test 3: semantic search (Chinese query) ===")
    r = search_memory("沉浸式 3D 创意开发者网站")
    print(f"search_mode: {r.get('search_mode')}")
    assert r.get("ok") is True, r
    assert r.get("search_mode") == "semantic", r
    results = r.get("results") or []
    assert results, r
    for i, item in enumerate(results, 1):
        print(f"{i}. {item.get('title')} | {item.get('url')}")
        print(f"   similarity: {item.get('similarity')}")
    # Expect Bruno-ish case among results for this semantic query.
    blob = json.dumps(results, ensure_ascii=False).lower()
    assert "bruno" in blob or "webgl" in blob or "three" in blob or "3d" in blob, results
    print()


def test4_related_queries() -> None:
    print("=== Test 4: related English queries ===")
    a = search_memory("creative 3D interactive portfolio")
    b = search_memory("WebGL portfolio")
    print(f"A search_mode: {a.get('search_mode')} results={len(a.get('results') or [])}")
    print(f"B search_mode: {b.get('search_mode')} results={len(b.get('results') or [])}")
    assert a.get("search_mode") == "semantic", a
    assert b.get("search_mode") == "semantic", b
    assert a.get("results") and b.get("results"), (a, b)
    # Soft check: at least one overlapping id/url family if both find something.
    urls_a = {normalize_url(x.get("url") or "") for x in a["results"]}
    urls_b = {normalize_url(x.get("url") or "") for x in b["results"]}
    print("A urls:", sorted(u for u in urls_a if u))
    print("B urls:", sorted(u for u in urls_b if u))
    print("overlap:", sorted(urls_a & urls_b))
    print()


def test5_embedding_unavailable_fallback() -> None:
    print("=== Test 5: embedding unavailable → keyword_fallback ===")
    with patch(
        "tools.memory.embed_text",
        side_effect=EmbeddingUnavailableError("embedding_unavailable"),
    ):
        r = search_memory("WebGL portfolio")
    print(json.dumps(r, indent=2, ensure_ascii=False)[:800])
    assert r.get("ok") is True, r
    assert r.get("search_mode") == "keyword_fallback", r
    assert r.get("embedding_error") == "embedding_unavailable"
    print("fallback ok")
    print()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass

    test1_embedding()
    test2_save_embedding()
    test3_semantic_zh()
    test4_related_queries()
    test5_embedding_unavailable_fallback()
    print("ALL EMBEDDING / PGVECTOR TESTS PASSED")


if __name__ == "__main__":
    main()
