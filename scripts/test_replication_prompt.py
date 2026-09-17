"""Ticket 30 — Full Replication Prompt assembler (no LLM)."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from library.replication_prompt import assemble_replication_prompt


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    card = {
        "id": "case_a",
        "title": "Alpha WebGL Portfolio",
        "url": "https://example.com/alpha",
        "visual": {
            "style": "Dark cinematic WebGL stage",
            "layout": "Full viewport",
            "typography": "Oversized type",
            "color": "Black and red",
        },
        "interaction": {
            "hover": "Central form scales on hover.",
            "scroll": "Scroll input drives staged reveal.",
            "transition": "Scale transition observed.",
            "visual_analysis": [
                {
                    "interaction": "hover",
                    "effect": "Shape enlarged after hover.",
                    "before": "screenshots/missing_before.png",
                    "after": "screenshots/missing_after.png",
                }
            ],
        },
        "frontend": {
            "framework": {
                "name": "Next.js",
                "evidence": ["__NEXT_DATA__ present"],
            },
            "libraries": [
                {"name": "Three.js", "evidence": ["data-engine=three.js"]},
                {"name": "GuessLib", "confidence": "low", "evidence": []},
            ],
        },
        "replication": {"prompt": "Full-screen WebGL hero"},
    }
    en = assemble_replication_prompt(card, lang="en")
    zh = assemble_replication_prompt(card, lang="zh")
    assert "example.com" in en
    assert "Dark cinematic WebGL stage" in en
    assert "Full-screen WebGL hero" in en
    assert "Recreate the Hover" not in en
    assert "Recreate the" not in en
    assert "GuessLib" not in en
    assert "Next.js" in en
    assert "Three.js" in en
    assert "If a library is not listed here" in en
    assert "## Typography" in en
    assert "Oversized type" in en
    empty = assemble_replication_prompt(
        {"id": "x", "url": "https://example.com/x", "visual": {}, "interaction": {}, "frontend": {}},
        lang="en",
    )
    assert "## Typography" not in empty
    assert "example.com" in zh
    source = inspect.getsource(assemble_replication_prompt)
    assert "chat.completions" not in source
    assert "OpenAI" not in source
    print("ok")


if __name__ == "__main__":
    main()
