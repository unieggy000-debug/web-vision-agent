"""Screenshot tool — capture a full-page PNG with Playwright."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

from tools.page_settle import settle_page

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCREENSHOTS_DIR = PROJECT_ROOT / "screenshots"
GOTO_TIMEOUT_MS = 15_000


def _unique_filename(url: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    return f"screenshot_{stamp}_{digest}.png"


def screenshot(url: str) -> dict:
    """
    Open a URL and save a full-page screenshot under screenshots/.

    Never raises to the Agent Loop: failures become ok=False + error.
    """
    if not (url or "").strip():
        return {
            "ok": False,
            "url": url or "",
            "title": "",
            "screenshot_path": None,
            "error": "Empty URL.",
        }

    url = url.strip()
    playwright = None
    browser = None

    try:
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        filename = _unique_filename(url)
        abs_path = SCREENSHOTS_DIR / filename
        rel_path = f"screenshots/{filename}"

        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
        settle_page(page)

        title = page.title() or ""
        page.screenshot(path=str(abs_path), full_page=True)

        if not abs_path.is_file() or abs_path.stat().st_size <= 0:
            return {
                "ok": False,
                "url": url,
                "title": title,
                "screenshot_path": None,
                "error": "Screenshot file was not written.",
            }

        return {
            "ok": True,
            "url": url,
            "title": title,
            "screenshot_path": rel_path,
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "url": url,
            "title": "",
            "screenshot_path": None,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
