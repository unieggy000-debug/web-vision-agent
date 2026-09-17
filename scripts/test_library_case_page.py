"""Ticket 34/35 — Case Page reads the Research Card; one Full Prompt."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from library.index import rebuild_index
from library.pages import render_case_page
from library.replication_prompt import assemble_replication_prompt


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    card = {
        "id": "case_a",
        "title": "Alpha WebGL Portfolio",
        "url": "https://romanjeanelie.com/path",
        "created_at": "2026-09-17T00:00:00+00:00",
        "screenshots": [],
        "visual": {"style": "CARD_ONLY_STYLE_SENTENCE", "color": "Black and red"},
        "interaction": {"hover": "Scales on hover."},
        "frontend": {"libraries": [{"name": "GuessLib", "evidence": []}]},
        "replication": {},
    }
    tmp = ROOT / "data" / "_tmp_index_case.json"
    index = rebuild_index([card], {"case_a": "dark_cinematic"}, path=tmp)
    index["sites"][0]["search_text"] = "INDEX_MUST_NOT_APPEAR"
    html = render_case_page(card, index)
    assert "CARD_ONLY_STYLE_SENTENCE" in html
    assert "INDEX_MUST_NOT_APPEAR" not in html
    assert "romanjeanelie.com" in html
    assert "<h1>romanjeanelie.com</h1>" in html
    assert "GuessLib" not in html
    assert "Recreate the" not in html
    assert "请按" not in html
    assert "只复刻能看见的效果，不要编造库或 CSS" not in html
    assert "CARD_ONLY_STYLE_SENTENCE" in html
    assert "Scales on hover" in html
    assert 'class="js-lang"' in html
    assert "facet-prompt" in html
    assert html.count("prompt-code") >= 4
    empty = render_case_page(
        {
            "id": "case_empty",
            "title": "Empty",
            "url": "https://empty.example/",
            "created_at": "2026-09-17T00:00:00+00:00",
            "screenshots": [],
            "visual": {},
            "interaction": {},
            "frontend": {},
            "replication": {},
        },
        index,
    )
    assert "empty_case_notes" in empty or "no written visual notes" in empty
    assert "请按" not in empty
    prompt = assemble_replication_prompt(card, lang="en")
    assert "CARD_ONLY_STYLE_SENTENCE" in prompt
    assert "prompt-code" in html
    assert 'class="code prompt-code"' in html or "prompt-code" in html
    assert "prompt-kicker" in html
    print("ok")
    if tmp.exists():
        tmp.unlink()


if __name__ == "__main__":
    main()
