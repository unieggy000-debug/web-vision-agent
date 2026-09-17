"""Shared Playwright page settle helpers (WebGL / late paint)."""

from __future__ import annotations

SETTLE_MS = 2_500
NETWORK_IDLE_TIMEOUT_MS = 5_000


def settle_page(page, *, settle_ms: int = SETTLE_MS) -> None:
    """
    Give SPA / WebGL a short window to paint before screenshots.
    Never raises.
    """
    try:
        page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
    except Exception:
        pass
    try:
        page.wait_for_timeout(max(0, int(settle_ms)))
    except Exception:
        pass
    try:
        # Two animation frames — canvas often paints on rAF.
        page.evaluate(
            """() => new Promise((resolve) => {
              requestAnimationFrame(() => requestAnimationFrame(() => resolve(true)));
            })"""
        )
    except Exception:
        pass
