"""Frontend inspection — evidence-only Playwright page probes (no tech guessing)."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright

GOTO_TIMEOUT_MS = 20_000
WAIT_MS = 500
MAX_SCRIPT_SAMPLES = 40
MAX_CLUE_ITEMS = 25

# Patterns: name -> list of regexes matched against HTML / script URLs / globals.
LIBRARY_PATTERNS: list[tuple[str, list[re.Pattern[str]]]] = [
    ("GSAP", [re.compile(r"gsap", re.I), re.compile(r"ScrollTrigger", re.I), re.compile(r"TweenMax", re.I)]),
    ("Three.js", [re.compile(r"three(?:\.min)?\.js", re.I), re.compile(r"three/build", re.I), re.compile(r"\bTHREE\b")]),
    ("Lenis", [re.compile(r"lenis", re.I)]),
    ("Framer Motion", [re.compile(r"framer-motion", re.I), re.compile(r"framer\.motion", re.I)]),
    ("Lottie", [re.compile(r"lottie", re.I), re.compile(r"bodymovin", re.I)]),
    ("Swiper", [re.compile(r"swiper", re.I)]),
    ("Barba.js", [re.compile(r"barba(?:\.js|\.umd)?", re.I), re.compile(r"@barba/core", re.I)]),
    ("Anime.js", [re.compile(r"anime(?:\.min)?\.js", re.I), re.compile(r"animejs", re.I)]),
    ("Locomotive Scroll", [re.compile(r"locomotive[-_]?scroll", re.I)]),
    ("React", [re.compile(r"react(?:[-.]dom)?(?:\.production|\.development)?(?:\.min)?\.js", re.I), re.compile(r"__REACT_DEVTOOLS", re.I)]),
    ("Vue", [re.compile(r"vue(?:\.runtime)?(?:\.esm)?(?:\.min)?\.js", re.I), re.compile(r"__VUE__", re.I)]),
    ("Next.js", [re.compile(r"__NEXT_DATA__", re.I), re.compile(r"/_next/", re.I), re.compile(r"next/dist", re.I)]),
    ("Nuxt", [re.compile(r"__NUXT__", re.I), re.compile(r"/_nuxt/", re.I)]),
    ("Svelte", [re.compile(r"svelte", re.I), re.compile(r"__svelte", re.I)]),
    ("Astro", [re.compile(r"astro-island", re.I), re.compile(r"data-astro-", re.I)]),
    ("Webpack", [re.compile(r"webpack", re.I), re.compile(r"__webpack_require__", re.I)]),
    ("Vite", [re.compile(r"/@vite/", re.I), re.compile(r"vite/client", re.I)]),
]

FRAMEWORK_CHECKS: list[tuple[str, str, str]] = [
    # name, kind, pattern_or_key
    ("Next.js", "html", r"__NEXT_DATA__"),
    ("Next.js", "html", r"/_next/"),
    ("Nuxt", "html", r"__NUXT__"),
    ("Nuxt", "html", r"/_nuxt/"),
    ("Astro", "html", r"astro-island"),
    ("Astro", "html", r"data-astro-"),
    ("React", "global", "React"),
    ("React", "global", "__REACT_DEVTOOLS_GLOBAL_HOOK__"),
    ("Vue", "global", "Vue"),
    ("Vue", "global", "__VUE__"),
    ("Svelte", "html", r"__svelte"),
]


def _fail(url: str, error: str) -> dict:
    return {
        "ok": False,
        "url": url or "",
        "framework": None,
        "libraries": [],
        "frontend_clues": None,
        "animation_clues": [],
        "error": error,
    }


def _add_unique(items: list[str], value: str, limit: int = MAX_CLUE_ITEMS) -> None:
    value = (value or "").strip()
    if not value or value in items:
        return
    if len(items) >= limit:
        return
    items.append(value)


def _scriptish_corpus(html: str, script_srcs: list[str]) -> list[str]:
    """Collect only script-related / attribute evidence — not page copy or filter labels."""
    parts: list[str] = list(script_srcs)
    for m in re.finditer(r"<script\b[^>]*>.*?</script>", html or "", re.I | re.S):
        parts.append(m.group(0)[:8_000])
    for m in re.finditer(r"<script\b[^>]+src=['\"]([^'\"]+)['\"]", html or "", re.I):
        parts.append(m.group(1))
    # class / id tokens (real DOM hooks like class="lenis", id="__next")
    for m in re.finditer(r"""\b(?:class|id)=['\"]([^'\"]+)['\"]""", html or "", re.I):
        parts.append(m.group(1))
    for m in re.finditer(r"""\bdata-[\w-]+=['\"]([^'\"]+)['\"]""", html or "", re.I):
        parts.append(m.group(0)[:200])
    return parts


def _match_libraries(html: str, script_srcs: list[str], globals_hit: dict) -> list[dict]:
    found: dict[str, dict] = {}
    haystacks = _scriptish_corpus(html, script_srcs)

    for name, patterns in LIBRARY_PATTERNS:
        evidence: list[str] = []
        for pattern in patterns:
            for hay in haystacks:
                m = pattern.search(hay or "")
                if not m:
                    continue
                snippet = (hay or "").strip()
                if snippet.startswith("http") or snippet.startswith("/") or ".js" in snippet:
                    evidence.append(snippet[:300])
                else:
                    start = max(0, m.start() - 20)
                    end = min(len(snippet), m.end() + 40)
                    evidence.append(snippet[start:end].replace("\n", " ")[:300])
                break
            if evidence:
                break
        if evidence:
            uniq: list[str] = []
            for e in evidence:
                if e not in uniq:
                    uniq.append(e)
            found[name] = {
                "name": name,
                "confidence": "high",
                "evidence": uniq[:5],
            }

    # Globals are strong evidence even without script URL match.
    global_lib_map = {
        "gsap": "GSAP",
        "GreenSockGlobals": "GSAP",
        "THREE": "Three.js",
        "Lenis": "Lenis",
        "anime": "Anime.js",
        "LocomotiveScroll": "Locomotive Scroll",
        "barba": "Barba.js",
        "Swiper": "Swiper",
    }
    for gkey, lname in global_lib_map.items():
        if globals_hit.get(gkey):
            entry = found.get(lname) or {
                "name": lname,
                "confidence": "high",
                "evidence": [],
            }
            tip = f"window.{gkey} is present"
            if tip not in entry["evidence"]:
                entry["evidence"] = [tip] + list(entry.get("evidence") or [])
            entry["confidence"] = "high"
            found[lname] = entry

    return list(found.values())


def _detect_framework(html: str, globals_hit: dict, script_srcs: list[str]) -> dict:
    evidence: list[str] = []
    name = "unknown"
    confidence = "low"

    if globals_hit.get("__NEXT_DATA__") or "__NEXT_DATA__" in html or any(
        "/_next/" in s for s in script_srcs
    ):
        ev = []
        if globals_hit.get("__NEXT_DATA__"):
            ev.append("window.__NEXT_DATA__ is present")
        if "__NEXT_DATA__" in html:
            ev.append("Detected __NEXT_DATA__ in page HTML")
        for s in script_srcs:
            if "/_next/" in s:
                ev.append(s)
                break
        return {"name": "Next.js", "confidence": "high", "evidence": ev[:5]}

    if globals_hit.get("__NUXT__") or "__NUXT__" in html or any("/_nuxt/" in s for s in script_srcs):
        ev = []
        if globals_hit.get("__NUXT__"):
            ev.append("window.__NUXT__ is present")
        if "__NUXT__" in html:
            ev.append("Detected __NUXT__ in page HTML")
        for s in script_srcs:
            if "/_nuxt/" in s:
                ev.append(s)
                break
        return {"name": "Nuxt", "confidence": "high", "evidence": ev[:5]}

    if "astro-island" in html or "data-astro-" in html:
        return {
            "name": "Astro",
            "confidence": "high",
            "evidence": ["Detected Astro island / data-astro-* markers in HTML"],
        }

    if globals_hit.get("__REACT_DEVTOOLS_GLOBAL_HOOK__") or globals_hit.get("React"):
        evidence = []
        if globals_hit.get("React"):
            evidence.append("window.React is present")
        if globals_hit.get("__REACT_DEVTOOLS_GLOBAL_HOOK__"):
            evidence.append("window.__REACT_DEVTOOLS_GLOBAL_HOOK__ is present")
        for s in script_srcs:
            if re.search(r"react", s, re.I):
                evidence.append(s)
                break
        return {
            "name": "React",
            "confidence": "medium" if evidence else "low",
            "evidence": evidence[:5],
        }

    if globals_hit.get("Vue") or globals_hit.get("__VUE__"):
        evidence = []
        if globals_hit.get("Vue"):
            evidence.append("window.Vue is present")
        if globals_hit.get("__VUE__"):
            evidence.append("window.__VUE__ is present")
        return {"name": "Vue", "confidence": "medium", "evidence": evidence}

    if "__svelte" in html.lower():
        return {"name": "Svelte", "confidence": "medium", "evidence": ["__svelte marker in HTML"]}

    if 'id="__next"' in html or "id='__next'" in html:
        return {"name": "Next.js", "confidence": "medium", "evidence": ['HTML marker: id="__next"']}

    return {"name": name, "confidence": confidence, "evidence": evidence}


def inspect_frontend(url: str) -> dict:
    """
    Page-level frontend inspection with evidence-only reporting.

    Never raises to the Agent Loop. Does not download whole sites or guess tech from visuals.
    """
    if not (url or "").strip():
        return _fail(url or "", "Empty URL.")

    url = url.strip()
    playwright = None
    browser = None

    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
        page.wait_for_timeout(WAIT_MS)

        final_url = page.url
        html = page.content() or ""
        # Cap HTML corpus size for regex scanning.
        html_scan = html[:500_000]

        probe = page.evaluate(
            """() => {
              const scripts = Array.from(document.scripts || []).map(s => ({
                src: s.src || '',
                type: s.type || '',
                inlineLen: s.src ? 0 : (s.textContent || '').length
              }));
              const links = Array.from(document.querySelectorAll('link[href]')).map(l => ({
                rel: l.rel || '',
                href: l.href || ''
              }));
              const meta = Array.from(document.querySelectorAll('meta')).map(m => ({
                name: m.getAttribute('name') || m.getAttribute('property') || '',
                content: (m.getAttribute('content') || '').slice(0, 120)
              })).filter(m => m.name);
              const globals = {
                React: typeof window.React !== 'undefined',
                Vue: typeof window.Vue !== 'undefined',
                __VUE__: typeof window.__VUE__ !== 'undefined',
                __REACT_DEVTOOLS_GLOBAL_HOOK__: typeof window.__REACT_DEVTOOLS_GLOBAL_HOOK__ !== 'undefined',
                gsap: typeof window.gsap !== 'undefined',
                GreenSockGlobals: typeof window.GreenSockGlobals !== 'undefined',
                THREE: typeof window.THREE !== 'undefined',
                Lenis: typeof window.Lenis !== 'undefined',
                anime: typeof window.anime !== 'undefined',
                LocomotiveScroll: typeof window.LocomotiveScroll !== 'undefined',
                barba: typeof window.barba !== 'undefined',
                Swiper: typeof window.Swiper !== 'undefined',
                __NEXT_DATA__: typeof window.__NEXT_DATA__ !== 'undefined',
                __NUXT__: typeof window.__NUXT__ !== 'undefined'
              };
              const media = {
                canvas: document.querySelectorAll('canvas').length,
                video: document.querySelectorAll('video').length,
                svg: document.querySelectorAll('svg').length,
                iframe: document.querySelectorAll('iframe').length,
                webglContexts: (() => {
                  let n = 0;
                  document.querySelectorAll('canvas').forEach(c => {
                    try {
                      if (c.getContext('webgl') || c.getContext('webgl2') || c.getContext('experimental-webgl')) n += 1;
                    } catch (e) {}
                  });
                  return n;
                })()
              };
              const sample = Array.from(document.querySelectorAll('body *')).slice(0, 800);
              let transition = 0, animation = 0, transform = 0, opacityAnimated = 0;
              let filter = 0, backdrop = 0, fixed = 0, sticky = 0;
              for (const el of sample) {
                const s = getComputedStyle(el);
                if (s.transition && s.transition !== 'all 0s ease 0s' && s.transition !== 'none') transition += 1;
                if (s.animation && s.animation !== 'none' && s.animationName !== 'none') animation += 1;
                if (s.transform && s.transform !== 'none') transform += 1;
                if (s.filter && s.filter !== 'none') filter += 1;
                if (s.backdropFilter && s.backdropFilter !== 'none') backdrop += 1;
                if (s.position === 'fixed') fixed += 1;
                if (s.position === 'sticky') sticky += 1;
                if (s.opacity !== '1' && s.opacity !== '') opacityAnimated += 1;
              }
              return { scripts, links, meta, globals, media, cssCounts: {
                transition, animation, transform, filter, backdropFilter: backdrop, fixed, sticky,
                nonOpaque: opacityAnimated, sampled: sample.length
              }};
            }"""
        )

        script_srcs: list[str] = []
        scripts_clue: list[str] = []
        for item in (probe.get("scripts") or [])[:MAX_SCRIPT_SAMPLES]:
            src = (item.get("src") or "").strip()
            if src:
                script_srcs.append(src)
                _add_unique(scripts_clue, src)
            elif int(item.get("inlineLen") or 0) > 0:
                _add_unique(scripts_clue, f"inline script (~{item.get('inlineLen')} chars)")

        # Absolute-ize relative script URLs for evidence clarity.
        abs_scripts = []
        for s in script_srcs:
            abs_scripts.append(urljoin(final_url, s))

        globals_hit = {k: bool(v) for k, v in (probe.get("globals") or {}).items() if v}

        libraries = _match_libraries(html_scan, abs_scripts, globals_hit)
        framework = _detect_framework(html_scan, globals_hit, abs_scripts)

        css_clues: list[str] = []
        counts = probe.get("cssCounts") or {}
        for key, label in [
            ("transition", "elements with CSS transition"),
            ("animation", "elements with CSS animation"),
            ("transform", "elements with CSS transform"),
            ("filter", "elements with CSS filter"),
            ("backdropFilter", "elements with backdrop-filter"),
            ("fixed", "position:fixed elements"),
            ("sticky", "position:sticky elements"),
            ("nonOpaque", "elements with opacity != 1"),
        ]:
            n = int(counts.get(key) or 0)
            if n > 0:
                css_clues.append(f"{label}: {n} (sampled {counts.get('sampled', 0)} nodes)")

        dom_clues: list[str] = []
        for link in (probe.get("links") or [])[:20]:
            href = link.get("href") or ""
            rel = link.get("rel") or ""
            if href:
                _add_unique(dom_clues, f"link[{rel}]: {href}")
        for meta in (probe.get("meta") or [])[:15]:
            _add_unique(dom_clues, f"meta[{meta.get('name')}]: {meta.get('content')}")

        # data-* / generator hints from HTML (evidence snippets only).
        for pat, label in [
            (r'data-reactroot', "data-reactroot attribute"),
            (r'data-reactid', "data-reactid attribute"),
            (r'id="__next"', "div#__next"),
            (r'id="__nuxt"', "div#__nuxt"),
            (r'ng-version=', "Angular ng-version attribute"),
        ]:
            if re.search(pat, html_scan, re.I):
                _add_unique(dom_clues, f"HTML marker: {label}")

        media_clues: list[str] = []
        media = probe.get("media") or {}
        for key in ("canvas", "video", "svg", "iframe", "webglContexts"):
            n = int(media.get(key) or 0)
            if n > 0:
                media_clues.append(f"{key}: {n}")

        animation_clues: list[str] = []
        if int(counts.get("transition") or 0) > 0:
            animation_clues.append("CSS transitions present on sampled DOM nodes")
        if int(counts.get("animation") or 0) > 0:
            animation_clues.append("CSS animations present on sampled DOM nodes")
        if int(counts.get("transform") or 0) > 0:
            animation_clues.append("CSS transforms present on sampled DOM nodes")
        if int(media.get("webglContexts") or 0) > 0:
            animation_clues.append("Canvas WebGL context(s) obtained successfully")
        if int(media.get("canvas") or 0) > 0 and int(media.get("webglContexts") or 0) == 0:
            animation_clues.append("canvas elements present; WebGL context not confirmed")
        for lib in libraries:
            if lib["name"] in {
                "GSAP",
                "Three.js",
                "Lenis",
                "Lottie",
                "Anime.js",
                "Locomotive Scroll",
                "Barba.js",
                "Framer Motion",
                "Swiper",
            }:
                animation_clues.append(
                    f"{lib['name']} evidence: {'; '.join(lib.get('evidence') or [])}"
                )

        frontend_clues = {
            "css": css_clues,
            "dom": dom_clues,
            "media": media_clues,
            "scripts": scripts_clue,
        }

        return {
            "ok": True,
            "url": final_url or url,
            "framework": framework,
            "libraries": libraries,
            "frontend_clues": frontend_clues,
            "animation_clues": animation_clues,
            "error": None,
        }
    except Exception as exc:
        return _fail(url, f"{type(exc).__name__}: {exc}")
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
