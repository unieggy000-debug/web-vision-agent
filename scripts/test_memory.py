"""Ticket 12 — Supabase Research Memory tests."""

from __future__ import annotations

import json
from unittest.mock import patch

from tools.memory import save_case, search_memory
from tools.supabase_client import get_supabase, reset_supabase_client


def _bruno_case(url: str = "https://bruno-simon.com/") -> dict:
    return {
        "title": "Bruno Simon Portfolio",
        "url": url,
        "screenshots": ["screenshots/bruno.png"],
        "visual": {
            "style": "Playful 3D interactive portfolio",
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
            "cursor": "Custom game-like controls",
            "transition": "Continuous 3D camera motion",
            "visual_analysis": [],
        },
        "frontend": {
            "framework": {"name": "unknown", "confidence": "low", "evidence": []},
            "libraries": [
                {
                    "name": "Three.js",
                    "confidence": "high",
                    "evidence": ["data-engine=three.js"],
                }
            ],
            "frontend_clues": {
                "scripts": ["three"],
                "css": [],
                "dom": [],
                "media": [],
            },
            "animation_clues": ["requestAnimationFrame game loop"],
        },
        "replication": {
            "prompt": "Build a driveable 3D portfolio with Three.js",
            "difficulty": "hard",
        },
    }


def _count_by_url(url: str) -> int:
    client = get_supabase()
    # Count via fetch + normalize comparison for robustness.
    from tools.memory import normalize_url

    target = normalize_url(url)
    rows = (
        client.table("research_cases")
        .select("id,url")
        .limit(500)
        .execute()
        .data
        or []
    )
    return sum(1 for r in rows if normalize_url(str(r.get("url") or "")) == target)


def main() -> None:
    reset_supabase_client()
    client = get_supabase()
    print("=== Supabase client ready ===")

    # Clean prior Bruno rows from previous test runs (by normalized URL family).
    existing = (
        client.table("research_cases").select("id,url").limit(500).execute().data or []
    )
    from tools.memory import normalize_url

    target = normalize_url("https://bruno-simon.com/")
    for row in existing:
        if normalize_url(str(row.get("url") or "")) == target:
            client.table("research_cases").delete().eq("id", row["id"]).execute()
            print("cleaned prior case:", row.get("id"))

    print()
    print("=== Test 1: save_case → Supabase ===")
    r1 = save_case(_bruno_case())
    print(json.dumps(r1, indent=2, ensure_ascii=False))
    assert r1.get("ok") and r1.get("saved"), r1
    assert r1.get("storage") == "supabase", r1
    rows = (
        client.table("research_cases")
        .select("*")
        .eq("id", r1["case_id"])
        .limit(1)
        .execute()
        .data
        or []
    )
    assert len(rows) == 1, rows
    print("supabase row id:", rows[0].get("id"))
    print("supabase row url:", rows[0].get("url"))

    print()
    print("=== Test 2: search_memory ===")
    r2 = search_memory("WebGL interactive portfolio")
    print(json.dumps(r2, indent=2, ensure_ascii=False))
    assert r2.get("ok") and len(r2.get("results", [])) >= 1, r2
    assert any(
        "bruno" in (x.get("url") or "").lower()
        or "bruno" in (x.get("title") or "").lower()
        for x in r2["results"]
    ), r2

    print()
    print("=== Test 3: duplicate URL ===")
    r3 = save_case(_bruno_case(url="https://Bruno-Simon.com"))
    print(json.dumps(r3, indent=2, ensure_ascii=False))
    assert r3.get("ok") is True and r3.get("saved") is False
    assert r3.get("reason") == "duplicate_url", r3
    assert _count_by_url("https://bruno-simon.com/") == 1

    print()
    print("=== Test 4: empty query ===")
    r4 = search_memory("")
    print(json.dumps(r4, indent=2))
    assert r4.get("ok") is False
    assert r4.get("results") == []

    print()
    print("=== Test 5: Supabase unavailable ===")
    with patch("tools.memory.get_supabase", side_effect=RuntimeError("Supabase down")):
        r5 = save_case(_bruno_case(url="https://example.com/unavailable-test"))
        print("save_case:", json.dumps(r5, indent=2))
        assert r5.get("ok") is False
        assert r5.get("error")
        r6 = search_memory("WebGL")
        print("search_memory:", json.dumps(r6, indent=2))
        assert r6.get("ok") is False
        assert r6.get("error")

    print()
    print("ALL SUPABASE MEMORY TESTS PASSED")


if __name__ == "__main__":
    main()
