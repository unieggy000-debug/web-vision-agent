"""Ticket 18/19/20/21 — Evidence-rich report / presentation tests.

HTML is the Style Library product surface.
Markdown keeps Ticket 16 section headings as a compatible archive.
"""

from __future__ import annotations

import json
import struct
import sys
import zlib
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reports.generate_report import (
    classify_style_categories,
    generate_research_report,
    synthesis_to_html,
    synthesis_to_markdown,
    write_report_html,
    write_report_markdown,
)
from reports.style_categories import (
    STYLE_CATEGORIES,
    STYLE_CATEGORY_IDS,
    build_visual_classify_payload,
    normalize_style_assignments,
)
from reports.presentation import (
    build_report_model,
    extract_before_after_pairs,
    exists_rel,
    html_asset_href,
    is_mostly_black,
    md_asset_href,
    pick_hero_screenshot,
    project_style_library,
    resolve_evidence_ids,
    _user_facing_analysis,
)


def _mini_png(path: Path, rgb: tuple[int, int, int] = (30, 40, 50)) -> None:
    """Write a tiny valid 1x1 PNG without Pillow."""
    path.parent.mkdir(parents=True, exist_ok=True)
    r, g, b = rgb
    raw = bytes([0, r, g, b])  # filter 0 + RGB
    compressed = zlib.compress(raw)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def _fixtures() -> dict[str, str]:
    base = ROOT / "screenshots"
    files = {
        "hero_a": "screenshots/ticket18_hero_a.png",
        "hero_b": "screenshots/ticket18_hero_b.png",
        "before": "screenshots/ticket18_hover1_before_x.png",
        "after": "screenshots/ticket18_hover1_after_x.png",
        "black": "screenshots/ticket18_black_empty.png",
        "missing": "screenshots/ticket18_does_not_exist.png",
    }
    _mini_png(ROOT / files["hero_a"], (20, 90, 90))
    _mini_png(ROOT / files["hero_b"], (90, 60, 20))
    _mini_png(ROOT / files["before"], (10, 10, 10))
    _mini_png(ROOT / files["after"], (200, 200, 200))
    _mini_png(ROOT / files["black"], (0, 0, 0))
    return files


def _sample_cases(files: dict[str, str]) -> list[dict]:
    return [
        {
            "id": "case_t18_001",
            "title": "Alpha WebGL Portfolio",
            "url": "https://example.com/alpha?ref=1",
            # Black page shot first — hero picker must skip it when content exists.
            "screenshots": [
                files["black"],
                files["hero_a"],
                files["before"],
                files["after"],
            ],
            "visual": {"style": "Dark cinematic WebGL stage", "layout": "Full viewport"},
            "interaction": {
                "scroll": "Scroll input drives staged reveal.",
                "hover": "Central form scales on hover.",
                "cursor": "pointer",
                "transition": "Scale transition observed.",
                "visual_analysis": [
                    {
                        "interaction": "hover",
                        "effect": "Central shape enlarged after hover.",
                        "before": files["before"],
                        "after": files["after"],
                        "animation_type": "scale",
                        "confidence": "high",
                    }
                ],
            },
            "frontend": {
                "framework": {
                    "name": "Next.js",
                    "confidence": "high",
                    "evidence": ["__NEXT_DATA__ present"],
                },
                "libraries": [
                    {
                        "name": "Three.js",
                        "confidence": "high",
                        "evidence": ["data-engine=three.js"],
                    }
                ],
            },
            "replication": {"prompt": "Full-screen WebGL hero", "difficulty": "hard"},
        },
        {
            "id": "case_t18_002",
            "title": "Beta Editorial Site",
            "url": "https://example.com/beta",
            "screenshots": [files["hero_b"], files["missing"]],
            "visual": {"style": "Editorial minimal", "layout": "Card stack"},
            "interaction": {
                "scroll": "Native document scroll.",
                "hover": "",
                "cursor": "",
                "transition": "",
                "visual_analysis": [],
            },
            "frontend": {
                "framework": {"name": "unknown", "confidence": "low", "evidence": []},
                "libraries": [{"name": "GuessLib", "confidence": "low", "evidence": []}],
            },
            "replication": {"prompt": "Card reveal", "difficulty": "medium"},
        },
        {
            "id": "case_t18_003",
            "title": "Gamma No Media",
            "url": "https://example.com/gamma",
            "screenshots": [],
            "visual": {},
            "interaction": {},
            "frontend": {},
            "replication": {},
        },
    ]


def _sample_synthesis(cases: list[dict]) -> dict:
    ids = [c["id"] for c in cases]
    return {
        "title": "Ticket 18 Evidence Demo Report",
        "scope": "验证 Screenshot / Before-After / Evidence Mapping",
        "cases_analyzed": [{"id": c["id"], "title": c["title"]} for c in cases],
        "common_patterns": [
            {
                "pattern": "Full-viewport visual stage appears in multiple portfolios.",
                "evidence_case_ids": [ids[0], ids[1], "case_never_exists"],
            }
        ],
        "key_differences": [
            {
                "topic": "Scroll model",
                "comparison": "Alpha uses staged scroll; Beta uses native scroll.",
                "case_ids": [ids[0], ids[1]],
            }
        ],
        "interaction_patterns": [
            {
                "pattern": "Hover-driven scale feedback on focal elements.",
                "evidence_case_ids": [ids[0]],
            }
        ],
        "frontend_patterns": [
            {
                "pattern": "Three.js detected via data-engine evidence.",
                "evidence_case_ids": [ids[0]],
            }
        ],
        "notable_findings": [
            {
                "finding": "Evidence mapping can link findings to concrete cases.",
                "evidence_case_ids": [ids[0], ids[1]],
            }
        ],
        "replication_ideas": [
            {
                "idea": "Recreate hover scale with a transform transition.",
                "source_case_ids": [ids[0]],
                "difficulty": "easy",
            }
        ],
    }


def test_resolver_and_paths(files: dict[str, str], cases: list[dict]) -> None:
    print("=== Resolver / paths ===")
    assert exists_rel(files["hero_a"])
    assert not exists_rel(files["missing"])
    assert is_mostly_black(files["black"]) is True
    assert is_mostly_black(files["hero_a"]) is False
    # Black page shot listed first, but hero must prefer contentful image.
    assert pick_hero_screenshot(cases[0]) == files["hero_a"]
    pairs = extract_before_after_pairs(cases[0])
    assert pairs and pairs[0]["before_exists"] and pairs[0]["after_exists"]
    assert md_asset_href(files["hero_a"]).startswith("../screenshots/")
    assert html_asset_href(files["hero_a"]).startswith("../../screenshots/")
    assert "\\" not in md_asset_href(files["hero_a"])
    lookup = {c["id"]: c for c in cases}
    resolved = resolve_evidence_ids(
        [cases[0]["id"], "case_never_exists", cases[1]["id"]], lookup
    )
    assert resolved == [cases[0]["id"], cases[1]["id"]]
    print("ok")


def test_markdown_and_html(cases: list[dict], synthesis: dict) -> dict:
    print("=== Markdown + HTML render ===")
    model = build_report_model(
        synthesis,
        cases,
        goal=synthesis["scope"],
        run_id="run_t18",
        style_assignments={
            cases[0]["id"]: "dark_cinematic",
            cases[1]["id"]: "editorial",
            cases[2]["id"]: "other",
        },
    )
    md = synthesis_to_markdown(synthesis, cases, goal=synthesis["scope"], run_id="run_t18")
    html = synthesis_to_html(
        synthesis,
        cases,
        goal=synthesis["scope"],
        run_id="run_t18",
        style_assignments={
            cases[0]["id"]: "dark_cinematic",
            cases[1]["id"]: "editorial",
            cases[2]["id"]: "other",
        },
    )

    for heading in (
        "## Research Scope",
        "## Cases Analyzed",
        "## Common Patterns",
        "## Key Differences",
        "## Interaction Patterns",
        "## Frontend Patterns",
        "## Notable Findings",
        "## Replication Ideas",
        "## Case Studies",
        "## Source Cases",
    ):
        assert heading in md, heading

    # Ticket 21: Markdown remains Ticket 16 headings; Style Library is HTML-only.
    assert "## Style Library" not in md
    assert 'id="style"' not in md
    assert "data-facet=" not in md

    assert "Synthesis:" in md
    assert "Observation" in md or "Before / After" in md
    assert "../screenshots/ticket18_hero_a.png" in md
    assert "ticket18_black_empty.png" not in md.split("Case Studies")[0]  # hero area prefers non-black
    assert "case_never_exists" not in md
    assert "No screenshot available" in md  # gamma case

    assert "<!DOCTYPE html>" in html
    assert 'id="style"' in html
    assert "Web design style reference library" in html or 'data-i18n="nav_style"' in html
    assert "Original website" in html
    assert "Prompt" in html
    assert "Recreate the" in html
    assert "请按" in html
    assert "Look and feel" in html
    assert "整体感觉" in html
    assert "Hover" in html
    assert "悬停" in html
    assert "js-lang" in html
    assert "Before / After" in html
    assert "category-grid" in html
    assert "cat-dark_cinematic" in html
    assert "example.com" in html
    assert "Alpha WebGL Portfolio" not in html
    assert "site-strip" not in html
    assert 'class="detail-card' in html
    assert "prompt-fold" in html
    assert "copy-prompt" in html
    assert 'details class="detail-card' in html
    assert "../../screenshots/ticket18_hero_a.png" in html
    assert "ticket18_black_empty.png" not in html
    assert 'data-lang-btn="zh"' in html
    assert "data-i18n=" in html
    assert "lang-switch" in html
    assert "case_never_exists" not in html
    assert "GuessLib" not in html
    assert "data-engine=three.js" in html
    assert "No screenshot available" in html or "no_hero" in html or "Gamma" in html
    assert "#ddd8ce" in html  # non-black media placeholder
    assert "整站气质" not in html
    assert "What happens on hover" not in html
    assert "请复刻" not in html
    assert "Recreate this" not in html
    for old in (
        'id="findings"',
        'id="visual"',
        'id="interaction"',
        'id="frontend"',
        'id="compare"',
        'id="ideas"',
        "Key findings",
        "Visual patterns",
        "Interaction patterns",
        "Frontend patterns",
        "Cross-case comparison",
        "Replication ideas",
    ):
        assert old not in html, old

    md_path = write_report_markdown(md, title=synthesis["title"])
    html_path = write_report_html(html, title=synthesis["title"])
    assert md_path.exists()
    assert html_path.exists()
    assert "reports" in str(md_path).replace("\\", "/")
    assert "html" in str(html_path).replace("\\", "/")
    print("md:", md_path)
    print("html:", html_path)
    return {
        "md": str(md_path.relative_to(ROOT)).replace("\\", "/"),
        "html": str(html_path.relative_to(ROOT)).replace("\\", "/"),
        "cases_count": model["cases_count"],
        "hero_case0": model["cases"][0].get("hero"),
    }


def _details_by_facet(site: dict) -> dict:
    return {d["facet"]: d for d in site.get("details") or []}


def test_style_library_projection(
    files: dict[str, str],
    cases: list[dict],
    synthesis: dict,
) -> None:
    print("=== Ticket 19 Style Library projection ===")
    extra = {
        "id": "case_t19_black_ba",
        "title": "Black Before After",
        "url": "https://example.com/black-ba",
        "screenshots": [files["black"]],
        "visual": {"style": "Empty capture"},
        "interaction": {
            "hover": "",
            "visual_analysis": [
                {
                    "interaction": "hover",
                    "effect": "none",
                    "before": files["black"],
                    "after": files["black"],
                    "animation_type": "none",
                },
                {
                    "interaction": "scroll",
                    "effect": "missing",
                    "before": files["missing"],
                    "after": files["missing"],
                    "animation_type": "none",
                },
            ],
        },
        "frontend": {
            "libraries": [{"name": "GuessLib", "confidence": "low", "evidence": []}],
        },
        "replication": {},
    }
    projected_cases = list(cases) + [extra]
    assignments = {
        "case_t18_001": "dark_cinematic",
        "case_t18_002": "editorial",
        "case_t18_003": "other",
        "case_t19_black_ba": "other",
    }
    model = build_report_model(
        synthesis,
        projected_cases,
        goal=synthesis["scope"],
        run_id="run_t19",
        style_assignments=assignments,
    )
    lib = model.get("style_library")
    assert isinstance(lib, dict), lib
    assert lib.get("label") == synthesis["title"]
    assert len(lib.get("sites") or []) == len(projected_cases)

    direct = project_style_library(
        projected_cases,
        style_label=synthesis["title"],
        assignments=assignments,
    )
    assert direct["label"] == lib["label"]
    assert len(direct["sites"]) == len(lib["sites"])

    by_id = {s["id"]: s for s in lib["sites"]}
    alpha = by_id["case_t18_001"]
    beta = by_id["case_t18_002"]
    gamma = by_id["case_t18_003"]
    black_site = by_id["case_t19_black_ba"]

    alpha_facets = set(_details_by_facet(alpha))
    assert "typography" not in alpha_facets
    assert "overview" in alpha_facets
    assert "layout" in alpha_facets
    assert "hover_cursor" in alpha_facets
    assert "scroll" in alpha_facets
    assert "animation" in alpha_facets

    for detail in alpha["details"]:
        if detail.get("analysis"):
            assert str(detail.get("prompt") or "").strip(), detail
            assert str(detail.get("prompt_zh") or "").strip(), detail
            assert "请按" in str(detail.get("prompt_zh"))
            assert "example.com" in str(detail.get("prompt"))
            assert "Alpha WebGL Portfolio" not in str(detail.get("prompt"))
            assert "Alpha WebGL Portfolio" not in str(detail.get("prompt_zh"))
        if detail.get("facet") == "overview":
            assert detail.get("label_zh") == "整体感觉"
            assert detail.get("label_en") == "Look and feel"
            assert "Typography" not in (detail.get("label_en") or "")

    code_blob = json.dumps(
        [d.get("code") for d in alpha["details"] if d.get("code")],
        ensure_ascii=False,
    )
    assert "Three.js" in code_blob
    assert "data-engine=three.js" in code_blob
    assert "GuessLib" not in code_blob

    beta_facets = set(_details_by_facet(beta))
    assert "typography" not in beta_facets
    assert "overview" in beta_facets
    for detail in beta["details"]:
        assert detail.get("code") is None, detail
        if detail.get("analysis"):
            assert str(detail.get("prompt") or "").strip()
    assert "GuessLib" not in json.dumps(beta.get("details"), ensure_ascii=False)

    hover = _details_by_facet(alpha)["hover_cursor"]
    assert hover.get("pairs")
    assert all(p.get("content_ok") for p in hover["pairs"])
    assert files["before"] in [p.get("before") for p in hover["pairs"]]

    for site in lib["sites"]:
        for detail in site.get("details") or []:
            for pair in detail.get("pairs") or []:
                assert pair.get("content_ok") is True
                assert pair.get("before") != files["black"] or pair.get("after") != files["black"]
                assert files["missing"] not in (pair.get("before"), pair.get("after"))

    black_facets = set(_details_by_facet(black_site))
    assert "hover_cursor" not in black_facets
    assert "scroll" not in black_facets
    assert "typography" not in set(_details_by_facet(gamma))

    cats = lib.get("categories") or []
    assert cats, cats
    assert all("site_ids" not in cat for cat in cats)
    by_cat = {c["id"]: c for c in cats}
    assert "dark_cinematic" in by_cat
    assert "editorial" in by_cat
    assert "brutalist" not in by_cat
    assert [s["id"] for s in by_cat["dark_cinematic"]["sites"]] == ["case_t18_001"]
    assert alpha.get("domain") == "example.com"
    assert alpha.get("category_id") == "dark_cinematic"
    seen_ids = [s["id"] for c in cats for s in c.get("sites") or []]
    assert seen_ids.count("case_t18_001") == 1
    print("ok")


def test_missing_assets_do_not_crash(cases: list[dict], synthesis: dict) -> None:
    print("=== Missing assets graceful ===")
    broken = json.loads(json.dumps(cases))
    broken[0]["screenshots"] = ["screenshots/absolutely_missing.png"]
    broken[0]["interaction"]["visual_analysis"] = [
        {
            "interaction": "scroll",
            "before": "screenshots/missing_before.png",
            "after": "screenshots/missing_after.png",
            "effect": "n/a",
        }
    ]
    md = synthesis_to_markdown(synthesis, broken)
    html = synthesis_to_html(synthesis, broken)
    assert "Research Scope" in md
    assert "<!DOCTYPE html>" in html
    print("ok")


def test_user_facing_analysis() -> None:
    print("=== Ticket 22 readable analysis ===")
    messy = (
        "Fixed full-viewport stage (scrollHeight 900, 6 fixed/sticky elements) "
        "with centered 'WELCOME' intro. "
        "No native document scroll: measured scrollY stayed 0 across y=0/500/1000 "
        "checkpoints with scrollHeight 900 — the page is a fixed full-viewport stage "
        "where scroll input drives a scripted sequence (GSAP) rather than document scrolling. "
        "bodyTextLen unchanged across checkpoints. "
        "CSS transitions present on sampled DOM nodes. "
        "Dark cinematic portfolio (score 7.21/10)."
    )
    cleaned = _user_facing_analysis(messy)
    assert "scrollHeight" not in cleaned
    assert "scrollY" not in cleaned
    assert "bodyTextLen" not in cleaned
    assert "sampled DOM" not in cleaned
    assert "score" not in cleaned.lower()
    assert "WELCOME" in cleaned
    assert "GSAP" in cleaned
    assert "Dark cinematic portfolio" in cleaned
    print("ok")


def _classify_cases() -> list[dict]:
    return [
        {
            "id": "case_a",
            "title": "Roman Jean-Elie — Next.js + R3F + GSAP WebGL portfolio",
            "url": "https://www.romanjeanelie.com/?ref=secret",
            "visual": {
                "style": "Dark cinematic full-viewport WebGL stage",
                "layout": "Fixed hero stage",
                "typography": "Oversized uppercase type",
                "color": "Black and red",
                "spacing": "Generous negative space",
                "imagery": "WebGL silhouette scene",
                "visual_effects": "Red glow",
            },
            "frontend": {
                "framework": {"name": "Next.js", "evidence": ["__NEXT_DATA__"]},
                "libraries": [{"name": "Three.js", "evidence": ["data-engine"]}],
            },
            "replication": {"prompt": "Recreate the WebGL hero"},
        },
        {
            "id": "case_b",
            "title": "Editorial Studio Site",
            "url": "https://example.com/editorial",
            "visual": {
                "style": "Minimal editorial portfolio",
                "layout": "Single column cards",
            },
            "frontend": {"framework": {"name": "Hugo"}},
            "replication": {},
        },
        {
            "id": "case_c",
            "title": "No Visual Case",
            "url": "https://example.com/empty",
            "visual": {},
            "frontend": {"libraries": [{"name": "GuessLib"}]},
        },
    ]


def _fake_chat_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = content
    return response


def test_style_category_taxonomy() -> None:
    print("=== Ticket 23 closed taxonomy ===")
    ids = [item[0] for item in STYLE_CATEGORIES]
    assert ids == [
        "minimal",
        "editorial",
        "brutalist",
        "corporate",
        "luxury",
        "futuristic",
        "playful",
        "experimental",
        "organic",
        "dark_cinematic",
        "other",
    ]
    assert len(STYLE_CATEGORY_IDS) == 11
    assert STYLE_CATEGORY_IDS == set(ids)
    assert "immersive_3d" not in STYLE_CATEGORY_IDS
    print("ok")


def test_visual_classify_payload_and_normalize() -> None:
    print("=== Ticket 23 payload + clamp ===")
    cases = _classify_cases()
    payload = build_visual_classify_payload(cases)
    blob = json.dumps(payload)
    assert "title" not in blob
    assert "url" not in blob
    assert "frontend" not in blob
    assert "replication" not in blob
    assert "Next.js" not in blob
    assert "romanjeanelie" not in blob
    assert "GuessLib" not in blob
    assert [row["id"] for row in payload] == ["case_a", "case_b", "case_c"]
    for row in payload:
        assert set(row.keys()) == {"id", "visual"}
        assert set(row["visual"]).issubset(
            {
                "style",
                "layout",
                "typography",
                "color",
                "spacing",
                "imagery",
                "visual_effects",
            }
        )
    assert payload[2]["visual"] == {}

    ids = ["case_a", "case_b", "case_c"]
    legal = normalize_style_assignments(
        {
            "assignments": [
                {"id": "case_a", "category": "dark_cinematic"},
                {"id": "case_b", "category": "editorial"},
            ]
        },
        ids,
    )
    assert legal == {
        "case_a": "dark_cinematic",
        "case_b": "editorial",
        "case_c": "other",
    }

    invalid = normalize_style_assignments(
        {"assignments": [{"id": "case_a", "category": "cyberpunk-glass"}]},
        ids,
    )
    assert invalid["case_a"] == "other"

    multi = normalize_style_assignments(
        {
            "assignments": [
                {"id": "case_a", "category": "minimal"},
                {"id": "case_a", "category": "editorial"},
            ]
        },
        ids,
    )
    assert multi["case_a"] == "other"

    empty = normalize_style_assignments({}, ids)
    assert empty == {"case_a": "other", "case_b": "other", "case_c": "other"}
    print("ok")


def test_classify_style_categories_mocked() -> None:
    print("=== Ticket 23 mocked classify LLM ===")
    cases = _classify_cases()
    captured: dict = {}

    def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return _fake_chat_response(
            json.dumps(
                {
                    "assignments": [
                        {"id": "case_a", "category": "dark_cinematic"},
                        {"id": "case_b", "category": "editorial"},
                        {"id": "case_c", "category": "other"},
                    ]
                }
            )
        )

    with patch("reports.generate_report._llm_client") as mock_client:
        mock_client.return_value.chat.completions.create.side_effect = fake_create
        result = classify_style_categories(cases)

    assert result.get("ok") is True, result
    assert result["assignments"]["case_a"] == "dark_cinematic"
    assert result["assignments"]["case_b"] == "editorial"
    assert result["assignments"]["case_c"] == "other"
    user_msg = captured["messages"][1]["content"]
    assert "title" not in user_msg
    assert "https://" not in user_msg
    assert "frontend" not in user_msg
    assert "GuessLib" not in user_msg
    assert "Next.js" not in user_msg

    with patch("reports.generate_report._llm_client") as mock_client:
        mock_client.return_value.chat.completions.create.return_value = _fake_chat_response(
            "{}"
        )
        empty = classify_style_categories(cases)
    assert empty["assignments"] == {
        "case_a": "other",
        "case_b": "other",
        "case_c": "other",
    }

    with patch("reports.generate_report._llm_client") as mock_client:
        mock_client.side_effect = RuntimeError("no key")
        failed = classify_style_categories(cases)
    assert failed.get("ok") is False
    assert failed["assignments"]["case_a"] == "other"

    none = classify_style_categories([])
    assert none.get("ok") is False
    assert none.get("assignments") == {}
    print("ok")


def test_generate_report_classification_wiring(
    files: dict[str, str],
    cases: list[dict],
    synthesis: dict,
) -> None:
    print("=== Ticket 26 generate_research_report classify wiring ===")
    fetched = {"ok": True, "cases": cases, "count": len(cases), "error": None}
    syn_ok = {"ok": True, "error": None, "synthesis": synthesis}
    ids = [c["id"] for c in cases]
    assignments = {
        cases[0]["id"]: "dark_cinematic",
        cases[1]["id"]: "editorial",
        cases[2]["id"]: "other",
    }

    with patch("reports.generate_report.get_research_cases", return_value=fetched), patch(
        "reports.generate_report.synthesize_cases", return_value=syn_ok
    ), patch("reports.generate_report.classify_style_categories") as mock_cls:
        mock_cls.return_value = {
            "ok": True,
            "error": None,
            "assignments": assignments,
            "payload": [],
        }
        result = generate_research_report(case_ids=ids, limit=3, force=True, run_id="t26")

    assert result.get("ok") is True, result
    assert result.get("html_path")
    html = (ROOT / str(result["html_path"])).read_text(encoding="utf-8")
    assert "cat-dark_cinematic" in html
    assert "category-grid" in html
    assert "example.com" in html
    assert "Alpha WebGL Portfolio" not in html
    assert "GuessLib" not in html
    mock_cls.assert_called_once()

    with patch("reports.generate_report.get_research_cases", return_value=fetched), patch(
        "reports.generate_report.synthesize_cases", return_value=syn_ok
    ), patch("reports.generate_report.classify_style_categories") as mock_cls:
        mock_cls.return_value = {
            "ok": False,
            "error": "classifier_down",
            "assignments": {},
            "payload": [],
        }
        failed = generate_research_report(
            case_ids=ids, limit=3, force=True, goal="retry-other", run_id="t26b"
        )
    assert failed.get("ok") is True, failed
    html_fail = (ROOT / str(failed["html_path"])).read_text(encoding="utf-8")
    assert "cat-other" in html_fail
    assert failed.get("path")
    print("ok")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass

    files = _fixtures()
    cases = _sample_cases(files)
    synthesis = _sample_synthesis(cases)
    test_resolver_and_paths(files, cases)
    test_user_facing_analysis()
    test_style_category_taxonomy()
    test_visual_classify_payload_and_normalize()
    test_classify_style_categories_mocked()
    test_style_library_projection(files, cases, synthesis)
    paths = test_markdown_and_html(cases, synthesis)
    test_generate_report_classification_wiring(files, cases, synthesis)
    test_missing_assets_do_not_crash(cases, synthesis)

    out = ROOT / "data" / "ticket18_test_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"status": "passed", **paths}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nALL TICKET 18 TESTS PASSED")
    print("Wrote", out)


if __name__ == "__main__":
    main()
