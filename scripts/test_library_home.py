"""Tickets 32–35 — Home / Style / Case pages and Full Prompt."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from library.index import rebuild_index
from library.pages import render_case_page, render_home, render_style_page
from library.replication_prompt import assemble_replication_prompt
from library.session import reset_session


def _cards() -> list[dict]:
    return [
        {
            "id": "case_a",
            "title": "Alpha WebGL Portfolio",
            "url": "https://romanjeanelie.com/",
            "created_at": "2026-09-17T12:00:00+00:00",
            "screenshots": [],
            "visual": {"style": "Dark cinematic WebGL stage", "typography": "Oversized type"},
            "interaction": {"hover": "Form scales on hover."},
            "frontend": {
                "framework": {"name": "Next.js", "evidence": ["__NEXT_DATA__"]},
                "libraries": [{"name": "GuessLib", "evidence": []}],
            },
            "replication": {"prompt": "Full-screen WebGL hero"},
        },
        {
            "id": "case_b",
            "title": "Editorial Studio Site",
            "url": "https://studiofreight.com/",
            "created_at": "2026-09-16T12:00:00+00:00",
            "screenshots": [],
            "visual": {"style": "Minimal editorial portfolio"},
            "interaction": {},
            "frontend": {},
            "replication": {},
        },
    ]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    reset_session()
    tmp = ROOT / "data" / "_tmp_index_pages.json"
    cards = _cards()
    assignments = {"case_a": "dark_cinematic", "case_b": "editorial"}
    index = rebuild_index(cards, assignments, path=tmp)

    from agent.prompts import SYSTEM_PROMPT

    home = render_home(index, session={"status": "idle", "goal": "", "message": ""})
    assert "ONLY research websites" in SYSTEM_PROMPT
    assert "out-of-scope" in SYSTEM_PROMPT or "unrelated" in SYSTEM_PROMPT
    assert "dark_cinematic" in home or "Dark Cinematic" in home
    assert "Editorial" in home
    assert "Brutalist" in home
    assert "Minimal" in home
    assert "Futuristic" in home
    assert "Playful" in home
    assert "organic" in home or "Organic" in home
    assert "immersive_3d" not in home
    assert "library-head" in home
    assert "composer" in home
    assert 'form="research-form"' in home
    assert "search-form" in home
    assert "Alpha WebGL Portfolio" not in home
    assert "/style/dark_cinematic" in home
    assert "data-i18n-placeholder" in home
    assert 'data-zh="全部风格"' in home or "全部风格" in home
    assert "class=\"zoomable\"" not in home

    style = render_style_page("dark_cinematic", index, sort="recent")
    assert style is not None
    assert "Dark Cinematic" in style
    assert "romanjeanelie.com" in style
    assert "<input type=\"search\"" not in style
    assert 'name="q"' not in style
    assert "Alpha WebGL Portfolio" not in style
    assert "/case/case_a" in style
    empty = render_style_page("brutalist", index)
    assert empty is not None
    assert "Brutalist" in empty
    assert '<input type="search"' not in empty
    assert 'name="q"' not in empty
    oldest = render_style_page("dark_cinematic", index, sort="oldest")
    assert oldest is not None
    assert "sort=oldest" in oldest or "Oldest Analyzed" in oldest

    # Index / card conflict: Index text must not replace card analysis.
    index["sites"][0]["search_text"] = "FAKE_INDEX_ONLY_PHRASE"
    case_html = render_case_page(cards[0], index)
    assert "romanjeanelie.com" in case_html
    assert "Dark cinematic WebGL stage" in case_html
    assert "FAKE_INDEX_ONLY_PHRASE" not in case_html
    assert "Alpha WebGL Portfolio" not in case_html.split("<title>")[0]
    assert "<h1>romanjeanelie.com</h1>" in case_html or ">romanjeanelie.com<" in case_html
    assert "GuessLib" not in case_html
    assert "Next.js" in case_html
    assert "Form scales on hover" in case_html
    assert "Recreate the" not in case_html
    assert "请按" not in case_html
    assert "Full Replication Prompt" in case_html or "完整复刻" in case_html
    prompt = assemble_replication_prompt(cards[0], lang="en")
    assert "Dark cinematic WebGL stage" in prompt
    # Prompt body is HTML-escaped in the page; check key facts survive.
    assert "Oversized type" in case_html
    assert 'class="block prompt-box"' in case_html
    assert "facet-prompt" in case_html

    print("ok")
    if tmp.exists():
        tmp.unlink()
    reset_session()


if __name__ == "__main__":
    main()
