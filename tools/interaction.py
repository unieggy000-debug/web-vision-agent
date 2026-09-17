"""Interaction tool — low-risk Playwright scroll/hover + Vision before/after compare."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

from tools.page_settle import settle_page
from tools.vision import analyze_interaction

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCREENSHOTS_DIR = PROJECT_ROOT / "screenshots"
GOTO_TIMEOUT_MS = 15_000
SCROLL_POINTS = (0, 500, 1000)
MAX_HOVERS = 3
WAIT_MS = 450

DANGEROUS_RE = re.compile(
    r"(login|log[\s_-]?in|sign[\s_-]?in|sign[\s_-]?up|register|submit|"
    r"delete|remove|buy|purchase|cart|checkout|pay|payment|password|"
    r"logout|unsubscribe|download\s*now)",
    re.I,
)


def _stamp(url: str, label: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:6]
    return f"interaction_{label}_{now}_{digest}.png"


def _save_shot(page, url: str, label: str, flat_paths: list[str]) -> str | None:
    try:
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        name = _stamp(url, label)
        abs_path = SCREENSHOTS_DIR / name
        page.screenshot(path=str(abs_path), full_page=False)
        rel = f"screenshots/{name}"
        flat_paths.append(rel)
        return rel
    except Exception:
        return None


def _page_metrics(page) -> dict:
    return page.evaluate(
        """() => ({
            scrollY: window.scrollY || window.pageYOffset || 0,
            innerHeight: window.innerHeight || 0,
            scrollHeight: document.documentElement.scrollHeight || document.body.scrollHeight || 0,
            clientHeight: document.documentElement.clientHeight || 0,
            fixedOrSticky: Array.from(document.querySelectorAll('body *')).filter(el => {
              const s = window.getComputedStyle(el);
              return s.position === 'fixed' || s.position === 'sticky';
            }).length,
            bodyTextLen: (document.body && document.body.innerText || '').length
        })"""
    )


def _is_safe_candidate(tag: str, href: str, text: str, role: str) -> bool:
    blob = f"{tag} {href} {text} {role}"
    if DANGEROUS_RE.search(blob):
        return False
    if href.startswith("javascript:"):
        return False
    if href.startswith("mailto:") or href.startswith("tel:"):
        return False
    return True


def _pick_hover_targets(page) -> list[dict]:
    raw = page.evaluate(
        """() => {
          const nodes = Array.from(document.querySelectorAll(
            'a[href], button, [role="button"], nav a, header a, .card, [class*="card"]'
          ));
          const out = [];
          for (const el of nodes) {
            const rect = el.getBoundingClientRect();
            if (rect.width < 8 || rect.height < 8) continue;
            if (rect.bottom < 0 || rect.top > window.innerHeight) continue;
            const style = window.getComputedStyle(el);
            if (style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity) === 0) continue;
            const text = (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 80);
            const href = el.getAttribute('href') || '';
            const role = el.getAttribute('role') || '';
            const tag = el.tagName.toLowerCase();
            out.push({
              tag,
              href,
              text,
              role,
              className: (el.className && String(el.className).slice(0, 120)) || '',
              box: {x: rect.x, y: rect.y, w: rect.width, h: rect.height}
            });
            if (out.length >= 20) break;
          }
          return out;
        }"""
    )
    picked = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        if not _is_safe_candidate(
            str(item.get("tag") or ""),
            str(item.get("href") or ""),
            str(item.get("text") or ""),
            str(item.get("role") or ""),
        ):
            continue
        picked.append(item)
        if len(picked) >= MAX_HOVERS:
            break
    return picked


def _locator_for(page, item: dict):
    tag = (item.get("tag") or "a").lower()
    text = (item.get("text") or "").strip()
    href = (item.get("href") or "").strip()
    if tag == "a" and href:
        loc = page.locator(f'a[href="{href}"]').first
        try:
            if loc.count() >= 1:
                return loc
        except Exception:
            pass
    if text:
        loc = page.locator(f"text={text}").first
        try:
            if loc.count() >= 1:
                return loc
        except Exception:
            pass
    box = item.get("box") or {}
    x = float(box.get("x", 0)) + float(box.get("w", 0)) / 2
    y = float(box.get("y", 0)) + float(box.get("h", 0)) / 2
    return ("point", x, y)


def _element_snapshot(page, locator_or_point) -> dict:
    if isinstance(locator_or_point, tuple) and locator_or_point[0] == "point":
        _, x, y = locator_or_point
        return page.evaluate(
            """({x, y}) => {
              const el = document.elementFromPoint(x, y);
              if (!el) return {found: false};
              const r = el.getBoundingClientRect();
              const s = window.getComputedStyle(el);
              return {
                found: true,
                tag: el.tagName.toLowerCase(),
                className: (el.className && String(el.className).slice(0, 120)) || '',
                cursor: s.cursor || '',
                opacity: s.opacity || '',
                transform: s.transform || '',
                backgroundColor: s.backgroundColor || '',
                box: {x: r.x, y: r.y, w: r.width, h: r.height},
                visible: r.width > 0 && r.height > 0 && s.visibility !== 'hidden'
              };
            }""",
            {"x": x, "y": y},
        )
    try:
        box = locator_or_point.bounding_box() or {}
        styles = locator_or_point.evaluate(
            """el => {
              const s = window.getComputedStyle(el);
              return {
                className: (el.className && String(el.className).slice(0, 120)) || '',
                cursor: s.cursor || '',
                opacity: s.opacity || '',
                transform: s.transform || '',
                backgroundColor: s.backgroundColor || '',
                tag: el.tagName.toLowerCase()
              };
            }"""
        )
        return {
            "found": True,
            "tag": styles.get("tag", ""),
            "className": styles.get("className", ""),
            "cursor": styles.get("cursor", ""),
            "opacity": styles.get("opacity", ""),
            "transform": styles.get("transform", ""),
            "backgroundColor": styles.get("backgroundColor", ""),
            "box": {
                "x": box.get("x"),
                "y": box.get("y"),
                "w": box.get("width"),
                "h": box.get("height"),
            },
            "visible": bool(box),
        }
    except Exception as exc:
        return {"found": False, "error": str(exc)}


def _vision_pair(
    before_path: str | None,
    after_path: str | None,
    interaction_type: str,
) -> dict | None:
    if not before_path or not after_path:
        return None
    result = analyze_interaction(before_path, after_path, interaction_type)
    analysis = result.get("analysis") if result.get("ok") else None
    if not analysis:
        return {
            "interaction": interaction_type,
            "changed": False,
            "effect": result.get("error") or "Vision comparison failed",
            "animation_type": "unknown",
            "evidence": "not detected",
            "before": before_path,
            "after": after_path,
            "confidence": "low",
            "elements_changed": "not detected",
        }
    return {
        "interaction": interaction_type,
        "changed": bool(analysis.get("changed")),
        "effect": analysis.get("effect") or "not detected",
        "animation_type": analysis.get("animation_type") or "unknown",
        "evidence": analysis.get("evidence") or "not detected",
        "before": before_path,
        "after": after_path,
        "confidence": analysis.get("confidence") or "low",
        "elements_changed": analysis.get("elements_changed") or "not detected",
    }


def _fail(
    url: str,
    error: str,
    screenshots: list | None = None,
    visual_analysis: list | None = None,
) -> dict:
    return {
        "ok": False,
        "url": url or "",
        "observations": None,
        "visual_analysis": visual_analysis or [],
        "screenshots": screenshots or [],
        "error": error,
    }


def inspect_interaction(url: str) -> dict:
    """
    Low-risk interaction probe with Vision before/after comparison.

    Scroll checkpoints: 0 / 500 / 1000. Hover a few safe elements.
    Never raises. Does not click forms/login/buy flows.
    """
    if not (url or "").strip():
        return _fail(url or "", "Empty URL.")

    url = url.strip()
    playwright = None
    browser = None
    flat_paths: list[str] = []
    screenshot_pairs: list[dict] = []
    visual_analysis: list[dict] = []

    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
        settle_page(page)
        page.wait_for_timeout(WAIT_MS)

        # --- Scroll checkpoints: initial → 500 → 1000 ---
        scroll_notes: list[str] = []
        prev_metrics = None
        prev_shot = None
        for target_y in SCROLL_POINTS:
            page.evaluate(f"window.scrollTo(0, {int(target_y)})")
            page.wait_for_timeout(WAIT_MS)
            metrics = _page_metrics(page)
            shot = _save_shot(page, url, f"scroll_y{int(target_y)}", flat_paths)
            actual_y = float(metrics.get("scrollY", 0))
            scroll_notes.append(
                f"checkpoint y={target_y}: measured scrollY={actual_y:.0f}, "
                f"scrollHeight={metrics.get('scrollHeight')}, "
                f"fixed/sticky={metrics.get('fixedOrSticky')}, shot={shot}."
            )
            if abs(actual_y - float(target_y)) > 20 and float(target_y) > 0:
                scroll_notes.append(
                    f"Page height may be insufficient for y={target_y} "
                    f"(stopped near {actual_y:.0f})."
                )
            if prev_shot and shot:
                screenshot_pairs.append({"before": prev_shot, "after": shot, "kind": "scroll"})
                pair = _vision_pair(prev_shot, shot, "scroll")
                if pair:
                    visual_analysis.append(pair)
            if prev_metrics is not None:
                delta = actual_y - float(prev_metrics.get("scrollY", 0))
                text_delta = int(metrics.get("bodyTextLen", 0)) - int(
                    prev_metrics.get("bodyTextLen", 0)
                )
                scroll_notes.append(
                    f"segment delta scrollY={delta:.0f}, bodyTextLen change={text_delta}."
                )
            prev_metrics = metrics
            prev_shot = shot

        if any(m.get("fixedOrSticky", 0) > 0 for m in [prev_metrics] if m):
            scroll_notes.append("Fixed/sticky chrome detected during scroll sequence.")

        # --- Hover probes near top ---
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(WAIT_MS)

        targets = _pick_hover_targets(page)
        hover_notes: list[str] = []
        cursor_notes: list[str] = []
        transition_notes: list[str] = []

        for idx, item in enumerate(targets, start=1):
            label = item.get("text") or item.get("href") or item.get("tag") or f"el{idx}"
            target = _locator_for(page, item)
            before_el = _element_snapshot(page, target)
            before_hover_shot = _save_shot(page, url, f"hover{idx}_before", flat_paths)

            try:
                if isinstance(target, tuple) and target[0] == "point":
                    page.mouse.move(target[1], target[2])
                else:
                    target.hover(timeout=3_000)
                page.wait_for_timeout(WAIT_MS)
            except Exception as hover_exc:
                hover_notes.append(
                    f"[{label}] hover failed: {type(hover_exc).__name__}: {hover_exc}"
                )
                continue

            after_el = _element_snapshot(page, target)
            after_hover_shot = _save_shot(page, url, f"hover{idx}_after", flat_paths)

            if before_hover_shot and after_hover_shot:
                screenshot_pairs.append(
                    {
                        "before": before_hover_shot,
                        "after": after_hover_shot,
                        "kind": "hover",
                    }
                )
                # Vision-compare only the first successful hover to limit cost/latency.
                if not any(v.get("interaction") == "hover" for v in visual_analysis):
                    pair = _vision_pair(before_hover_shot, after_hover_shot, "hover")
                    if pair:
                        visual_analysis.append(pair)

            cursor_before = (before_el or {}).get("cursor", "")
            cursor_after = (after_el or {}).get("cursor", "")
            cursor_notes.append(
                f"[{label}] cursor '{cursor_before}' → '{cursor_after}'"
            )

            changes = []
            for key in ("className", "opacity", "transform", "backgroundColor"):
                b = (before_el or {}).get(key)
                a = (after_el or {}).get(key)
                if b != a:
                    changes.append(f"{key}: {b!r} → {a!r}")
            box_b = (before_el or {}).get("box") or {}
            box_a = (after_el or {}).get("box") or {}
            if box_b != box_a:
                changes.append(f"box: {box_b} → {box_a}")

            if changes:
                transition_notes.append(f"[{label}] " + "; ".join(changes))
                hover_notes.append(
                    f"[{label}] hover applied; measurable DOM/style change "
                    f"(shots: {before_hover_shot}, {after_hover_shot})."
                )
            else:
                hover_notes.append(
                    f"[{label}] hover applied; no measurable class/style/box change "
                    f"(shots: {before_hover_shot}, {after_hover_shot})."
                )

        if not targets:
            hover_notes.append("No safe visible hover targets found.")
            cursor_notes.append("No cursor samples.")
            transition_notes.append("No transition samples.")

        observations = {
            "scroll": " ".join(scroll_notes) if scroll_notes else "No scroll observations.",
            "hover": " | ".join(hover_notes) if hover_notes else "No hover observations.",
            "cursor": " | ".join(cursor_notes) if cursor_notes else "No cursor observations.",
            "transition": (
                " | ".join(transition_notes)
                if transition_notes
                else "No measurable transitions."
            ),
        }

        return {
            "ok": True,
            "url": url,
            "observations": observations,
            "visual_analysis": visual_analysis,
            "screenshots": screenshot_pairs or [
                {"before": p, "after": None} for p in flat_paths
            ],
            "error": None,
        }
    except Exception as exc:
        return _fail(
            url,
            f"{type(exc).__name__}: {exc}",
            screenshot_pairs,
            visual_analysis,
        )
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
