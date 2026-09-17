"""Browser tool — open a real page with Playwright."""

from __future__ import annotations

from playwright.sync_api import sync_playwright

TEXT_LIMIT = 2000
GOTO_TIMEOUT_MS = 15_000


def open_page(url: str) -> dict:
    """
    Open a URL with headless Chromium and return a structured result.

    Never raises to the caller: failures become ok=False + error text
    so the Agent Loop can decide the next step.
    """
    if not (url or "").strip():
        return {
            "url": url or "",
            "final_url": "",
            "title": "",
            "ok": False,
            "text": "",
            "error": "Empty URL.",
        }

    url = url.strip()
    playwright = None
    browser = None

    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)

        title = page.title() or ""
        final_url = page.url or ""
        try:
            raw_text = page.locator("body").inner_text(timeout=5_000)
        except Exception:
            raw_text = ""
        # Normalize odd whitespace (e.g. NBSP) so Windows consoles can print results.
        text = (raw_text or "").replace("\xa0", " ").strip()
        if len(text) > TEXT_LIMIT:
            text = text[:TEXT_LIMIT] + "..."

        return {
            "url": url,
            "final_url": final_url,
            "title": title,
            "ok": True,
            "text": text,
            "error": None,
        }
    except Exception as exc:
        return {
            "url": url,
            "final_url": "",
            "title": "",
            "ok": False,
            "text": "",
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
