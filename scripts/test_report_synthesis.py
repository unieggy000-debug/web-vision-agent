"""Ticket 16/21 — Research Report / Synthesis tests.

Markdown keeps Ticket 16 headings as a compatible archive.
HTML Style Library coverage lives in test_evidence_report.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reports.generate_report import (
    generate_research_report,
    synthesize_cases,
    synthesis_to_markdown,
    write_report_markdown,
)
from tools.memory import get_research_cases


def test1_retrieve() -> list[dict]:
    print("=== Test 1: get_research_cases ===")
    r = get_research_cases(limit=5)
    print(json.dumps({k: r.get(k) for k in ("ok", "count", "error")}, indent=2))
    assert r.get("ok") is True, r
    assert r.get("count", 0) > 0, r
    cases = r.get("cases") or []
    first = cases[0]
    for key in ("id", "title", "url", "visual", "interaction", "frontend", "replication"):
        assert key in first, first
    return cases


def test2_synthesis(cases: list[dict]) -> dict:
    print("=== Test 2: Synthesis ===")
    sample = cases[:3]
    syn = synthesize_cases(
        sample,
        goal="总结这些 WebGL / portfolio 案例的视觉、交互与前端模式",
    )
    print("synthesis ok:", syn.get("ok"), "error:", syn.get("error"))
    assert syn.get("ok") is True, syn
    data = syn["synthesis"]
    for key in (
        "title",
        "cases_analyzed",
        "common_patterns",
        "key_differences",
        "interaction_patterns",
        "frontend_patterns",
        "notable_findings",
        "replication_ideas",
    ):
        assert key in data, data.keys()

    known = {c.get("id") for c in sample}
    for bucket_name in (
        "common_patterns",
        "interaction_patterns",
        "frontend_patterns",
        "notable_findings",
    ):
        for item in data.get(bucket_name) or []:
            if not isinstance(item, dict):
                continue
            for cid in item.get("evidence_case_ids") or []:
                assert cid in known, (bucket_name, cid, known)
    print("title:", data.get("title"))
    print("common_patterns:", len(data.get("common_patterns") or []))
    print("key_differences:", len(data.get("key_differences") or []))
    return data


def test3_report(cases: list[dict], synthesis: dict) -> Path:
    print("=== Test 3: Report Generation ===")
    md = synthesis_to_markdown(synthesis, cases[:3])
    path = write_report_markdown(md, title=str(synthesis.get("title") or "test"))
    text = path.read_text(encoding="utf-8")
    for heading in (
        "# ",
        "## Research Scope",
        "## Cases Analyzed",
        "## Common Patterns",
        "## Key Differences",
        "## Interaction Patterns",
        "## Frontend Patterns",
        "## Notable Findings",
        "## Replication Ideas",
        "## Source Cases",
    ):
        assert heading in text, heading
    print("wrote", path)
    # Ticket 21: Markdown stays a Ticket 16 archive, not an HTML Style Library.
    assert 'id="style"' not in text
    assert "data-facet=" not in text
    assert "## Style Library" not in text
    return path


def test4_empty_memory() -> None:
    print("=== Test 4: Empty Memory ===")
    with patch(
        "tools.memory.get_supabase"
    ) as mock_client:
        # Force empty result path without network by patching table chain.
        class Empty:
            def table(self, *_a, **_k):
                return self

            def select(self, *_a, **_k):
                return self

            def in_(self, *_a, **_k):
                return self

            def order(self, *_a, **_k):
                return self

            def limit(self, *_a, **_k):
                return self

            def execute(self):
                class R:
                    data = []

                return R()

        mock_client.return_value = Empty()
        r = get_research_cases(limit=5)
    print(r)
    assert r.get("ok") is False
    assert r.get("error") == "no_cases"


def test5_supabase_failure() -> None:
    print("=== Test 5: Supabase Failure ===")
    with patch("tools.memory.get_supabase", side_effect=RuntimeError("Supabase down")):
        r = get_research_cases(limit=5)
    print({k: r.get(k) for k in ("ok", "count", "error")})
    assert r.get("ok") is False
    assert r.get("cases") == []


def test6_long_context_truncation(cases: list[dict]) -> None:
    print("=== Test 6: Long Context Truncation ===")
    long_case = dict(cases[0])
    long_case["visual"] = {
        "style": ("VERY_LONG_STYLE_TEXT_" * 200),
        "layout": ("LAYOUT_" * 200),
    }
    # Truncation happens in get_research_cases/_public_case_view path.
    from tools.memory import _public_case_view, CASE_FIELD_CHAR_LIMIT

    truncated = _public_case_view(long_case, truncate=True)
    style = str((truncated.get("visual") or {}).get("style") or "")
    assert len(style) <= CASE_FIELD_CHAR_LIMIT + 5, len(style)
    # Original object not mutated by view helper for nested replace — we passed a copy.
    original_style = str((long_case.get("visual") or {}).get("style") or "")
    assert len(original_style) > CASE_FIELD_CHAR_LIMIT
    print("truncated style length:", len(style), "original:", len(original_style))


def test_generate_tool(cases: list[dict]) -> dict:
    print("=== Tool: generate_research_report ===")
    ids = [c.get("id") for c in cases[:3]]
    r = generate_research_report(
        case_ids=ids,
        limit=3,
        goal="总结已有 WebGL portfolio 的视觉、交互和前端实现模式",
    )
    print({k: r.get(k) for k in ("ok", "path", "cases_count", "error", "reused")})
    assert r.get("ok") is True, r
    assert r.get("path")
    assert r.get("html_path"), r
    # Second call with same ids should reuse cache.
    r2 = generate_research_report(case_ids=ids, limit=3, goal="same")
    assert r2.get("reused") is True, r2
    return r


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass

    cases = test1_retrieve()
    synthesis = test2_synthesis(cases)
    test3_report(cases, synthesis)
    test4_empty_memory()
    test5_supabase_failure()
    test6_long_context_truncation(cases)
    report = test_generate_tool(cases)

    out = ROOT / "data" / "ticket16_test_results.json"
    out.write_text(
        json.dumps(
            {
                "retrieve_count": len(cases),
                "synthesis_title": synthesis.get("title"),
                "report_path": report.get("path"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("\nALL REPORT SYNTHESIS TESTS PASSED")
    print("Wrote", out)


if __name__ == "__main__":
    main()
