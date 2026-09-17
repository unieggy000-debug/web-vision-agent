"""Library HTML pages. stdlib-only; no frontend framework."""

from __future__ import annotations

import html
import json
from typing import Any

from library.index import category_record, load_index, site_by_id, sites_for_category
from library.replication_prompt import assemble_replication_prompt
from library.search import filter_categories, filter_sites
from library.session import STATUS_RUNNING, STATUS_STOPPING, get_session
from reports.presentation import (
    _framework_code,
    _library_code,
    _pair_facet,
    _user_facing_analysis,
    exists_rel,
    extract_before_after_pairs,
    pick_hero_screenshot,
    site_domain,
)
from reports.style_categories import (
    STYLE_CATEGORIES,
    STYLE_CATEGORY_IDS,
    category_definition,
    category_labels,
)

I18N = {
    "en": {
        "brand": "Web Design Research Library",
        "nav_home": "Home",
        "search": "Search library",
        "search_ph": "Domain, style, visual words…",
        "filter": "Style",
        "filter_all": "All styles",
        "sort": "Sort",
        "sort_recent": "Recently Analyzed",
        "sort_oldest": "Oldest Analyzed",
        "apply": "Apply",
        "input_label": "Research task",
        "input_ph": "Describe a research task: a specific URL, or a visual style to collect (e.g. architecture portfolios, dark cinematic sites)…",
        "input_help": "This starts the Agent. Unrelated tasks are refused.",
        "submit": "Start",
        "cancel": "Cancel",
        "status_idle": "Idle",
        "status_running": "Running",
        "status_stopping": "Stopping — please wait.",
        "status_completed": "Completed",
        "status_failed": "Failed",
        "styles": "Styles",
        "sites": "sites",
        "original": "Original website",
        "no_shot": "No screenshot",
        "empty_library": "No research cards in the library yet.",
        "empty_style": "No sites in this style yet. Use the research task above to collect some.",
        "results": "Matching sites",
        "copy": "Copy",
        "prompt": "Full Replication Prompt",
        "prompt_kicker": "PROMPT",
        "no_hero": "No screenshot available",
        "empty_case_notes": "This card has no written visual notes. Only captured screenshots are shown.",
        "back": "Back to style",
        "not_found": "Not found",
        "before": "Before",
        "after": "After",
        "msg_running": "Research in progress.",
        "msg_stopping": "Stopping — please wait.",
        "msg_completed": "Research completed.",
        "msg_completed_none": "Finished, but no new sites were saved. Try a specific URL, or run again.",
        "msg_completed_partial": "Stopped at an emergency ceiling. Some requested styles may still be missing.",
        "msg_failed": "Research failed.",
        "msg_cancelled": "Stopped. Saved cases were kept.",
    },
    "zh": {
        "brand": "网页设计研究库",
        "nav_home": "首页",
        "search": "搜索已有库",
        "search_ph": "域名、风格、视觉词…",
        "filter": "风格",
        "filter_all": "全部风格",
        "sort": "排序",
        "sort_recent": "最近分析",
        "sort_oldest": "最早分析",
        "apply": "应用",
        "input_label": "调研任务",
        "input_ph": "输入调研任务：指定网站 URL，或指定视觉风格去找站点（例如建筑作品集、暗黑电影感）…",
        "input_help": "提交会启动 Agent。与网站/风格调研无关的任务会被拒绝。",
        "submit": "开始",
        "cancel": "停止",
        "status_idle": "空闲",
        "status_running": "进行中",
        "status_stopping": "正在停止，请稍候。",
        "status_completed": "已完成",
        "status_failed": "失败",
        "styles": "风格",
        "sites": "个网站",
        "original": "原网站",
        "no_shot": "暂无截图",
        "empty_library": "研究库里还没有卡片。",
        "empty_style": "这个风格下还没有网站。用上面的调研任务去收集。",
        "results": "匹配的网站",
        "copy": "复制",
        "prompt": "完整复刻提示词",
        "prompt_kicker": "提示词",
        "no_hero": "暂无截图",
        "empty_case_notes": "这张卡片没有文字分析，只有当时留下的截图。",
        "back": "返回风格",
        "not_found": "未找到",
        "before": "之前",
        "after": "之后",
        "msg_running": "正在调研。",
        "msg_stopping": "正在停止，请稍候。",
        "msg_completed": "调研已完成。",
        "msg_completed_none": "任务结束，但没有保存新网站。可换一个具体 URL 再试。",
        "msg_completed_partial": "因紧急兜底停止。目标里的部分风格可能还没收集到。",
        "msg_failed": "调研失败。",
        "msg_cancelled": "已停止。已保存的卡片仍会保留。",
    },
}


def _esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=True)


def asset_href(rel: str | None) -> str:
    raw = str(rel or "").replace("\\", "/").lstrip("/")
    if not raw:
        return ""
    return "/" + raw


def _t(key: str) -> str:
    return I18N["en"].get(key) or key


def _lang_span(en: str, zh: str, tag: str = "span") -> str:
    return (
        f'<{tag} class="js-lang" data-en="{_esc(en)}" data-zh="{_esc(zh)}">'
        f"{_esc(en)}</{tag}>"
    )


def _i18n_span(key: str, tag: str = "span") -> str:
    en = I18N["en"].get(key) or key
    zh = I18N["zh"].get(key) or en
    return (
        f'<{tag} class="js-lang" data-i18n="{_esc(key)}" data-en="{_esc(en)}" '
        f'data-zh="{_esc(zh)}">{_esc(en)}</{tag}>'
    )


def _option(value: str, en: str, zh: str, *, selected: bool = False) -> str:
    sel = " selected" if selected else ""
    return (
        f'<option value="{_esc(value)}" data-en="{_esc(en)}" data-zh="{_esc(zh)}"{sel}>'
        f"{_esc(en)}</option>"
    )


def _shot(rel: str | None, alt: str, *, zoom: bool = False) -> str:
    if not rel or not exists_rel(str(rel)):
        return f'<div class="missing">{_i18n_span("no_shot")}</div>'
    href = asset_href(rel)
    cls = ' class="zoomable"' if zoom else ""
    return (
        f'<img{cls} src="{_esc(href)}" alt="{_esc(alt)}" loading="lazy" '
        f'data-full="{_esc(href)}" />'
    )


def _site_card(site: dict[str, Any]) -> str:
    cid = str(site.get("case_id") or "")
    domain = str(site.get("domain") or "").strip() or "—"
    url = str(site.get("url") or "")
    hero = site.get("hero")
    original = (
        f'<a class="orig" href="{_esc(url)}" target="_blank" rel="noopener">'
        f'{_i18n_span("original")}</a>'
        if url
        else ""
    )
    return f"""
<article class="site-card">
  <a class="thumb" href="/case/{_esc(cid)}">{_shot(hero, domain, zoom=False)}</a>
  <div class="meta">
    <a class="domain" href="/case/{_esc(cid)}">{_esc(domain)}</a>
    {original}
  </div>
</article>"""


def _composer_controls(session: dict[str, Any], *, busy: bool) -> str:
    status = str(session.get("status") or "idle")
    msg_key = str(session.get("message_key") or "")
    if not msg_key:
        msg_key = {
            "running": "msg_running",
            "stopping": "msg_stopping",
            "completed": "msg_completed",
            "failed": "msg_failed",
        }.get(status, "")
    label = _i18n_span(f"status_{status}") if f"status_{status}" in I18N["en"] else _esc(status)
    msg = _i18n_span(msg_key) if msg_key in I18N["en"] else ""
    cancel = ""
    if status == STATUS_RUNNING:
        cancel = (
            '<form class="cancel-form" method="post" action="/research/cancel">'
            f'<button type="submit" class="ghost">{_i18n_span("cancel")}</button></form>'
        )
    start_disabled = " disabled" if busy else ""
    return f"""
<div class="composer-bar">
  <div class="status-inline status-{_esc(status)}">
    <strong>{label}</strong>
    {msg}
  </div>
  <div class="composer-actions">
    {cancel}
    <button type="submit" form="research-form"{start_disabled}>{_i18n_span("submit")}</button>
  </div>
</div>"""


def _chrome(
    title: str,
    body: str,
    *,
    title_zh: str | None = None,
    session: dict[str, Any] | None = None,
) -> str:
    sess = session if session is not None else get_session()
    status = str(sess.get("status") or "idle")
    zh_title = title_zh if title_zh is not None else title
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title class="js-lang" data-en="{_esc(title)}" data-zh="{_esc(zh_title)}">{_esc(title)}</title>
  <style>{_CSS}</style>
</head>
<body data-status="{_esc(status)}">
  <header class="top">
    <a class="brand" href="/">{_i18n_span("brand")}</a>
    <nav>
      <a href="/">{_i18n_span("nav_home")}</a>
      <div class="lang-switch" role="group">
        <button type="button" data-lang-btn="en">EN</button>
        <button type="button" data-lang-btn="zh">中文</button>
      </div>
    </nav>
  </header>
  <main>{body}</main>
  <div id="lightbox" aria-hidden="true"><img id="lightbox-img" alt="" />
    <button type="button" id="lightbox-close">×</button></div>
  <script>{_JS}</script>
</body>
</html>"""


def render_home(
    index: dict[str, Any] | None = None,
    *,
    q: str = "",
    style: str = "",
    sort: str = "recent",
    session: dict[str, Any] | None = None,
) -> str:
    data = index if index is not None else load_index()
    sess = session if session is not None else get_session()
    status = str(sess.get("status") or "idle")
    busy = status in {STATUS_RUNNING, STATUS_STOPPING}
    cats = filter_categories(data, q=q, style=style)
    matches = filter_sites(data, q=q, style=style, sort=sort) if q else []

    style_opts = [_option("", "All styles", "全部风格", selected=not style)]
    for key, en, zh in STYLE_CATEGORIES:
        style_opts.append(_option(key, en, zh, selected=style == key))
    input_disabled = " disabled" if busy else ""
    goal_value = str(sess.get("goal") or "") if busy else ""

    search_form = f"""
<form class="search-form" method="get" action="/" role="search">
  <input type="search" name="q" value="{_esc(q)}" placeholder="{_esc(_t('search_ph'))}"
         data-i18n-placeholder="search_ph" aria-label="Search" />
  <select name="style" aria-label="Style" onchange="this.form.submit()">{''.join(style_opts)}</select>
  <select name="sort" aria-label="Sort" onchange="this.form.submit()">
    {_option("recent", "Recently Analyzed", "最近分析", selected=sort != "oldest")}
    {_option("oldest", "Oldest Analyzed", "最早分析", selected=sort == "oldest")}
  </select>
</form>"""

    research_form = f"""
<section class="composer">
  <form id="research-form" class="research-form" method="post" action="/research">
    <textarea name="goal" rows="4" placeholder="{_esc(_t('input_ph'))}"
              data-i18n-placeholder="input_ph"{input_disabled}>{_esc(goal_value)}</textarea>
  </form>
  {_composer_controls(sess, busy=busy)}
  <p class="hint">{_i18n_span("input_help")}</p>
</section>"""

    cat_html = []
    for cat in cats:
        cid = str(cat.get("id") or "")
        count = int(cat.get("count") or 0)
        href = f"/style/{_esc(cid)}"
        if sort == "oldest":
            href += "?sort=oldest"
        cover = _shot(cat.get("cover"), str(cat.get("label_en") or cid), zoom=False)
        empty_cls = " empty" if count == 0 else ""
        cat_html.append(
            f"""
<a class="style-card{empty_cls}" href="{href}">
  {cover}
  <h2>{_lang_span(str(cat.get('label_en') or ''), str(cat.get('label_zh') or ''))}</h2>
  <p>{count} {_i18n_span("sites")}</p>
</a>"""
        )
    if not cat_html:
        cat_html.append(f'<p class="empty">{_i18n_span("empty_library")}</p>')

    results = ""
    if q:
        cards = "".join(_site_card(s) for s in matches)
        results = f"<section><h2>{_i18n_span('results')}</h2><div class='grid'>{cards}</div></section>"

    body = f"""
{research_form}
<section class="library-section">
  <div class="library-head">
    <h1>{_i18n_span("styles")}</h1>
    {search_form}
  </div>
  <div class="grid styles">{''.join(cat_html)}</div>
</section>
{results}"""
    return _chrome("Web Design Research Library", body, title_zh="网页设计研究库", session=sess)


def render_style_page(
    category_id: str,
    index: dict[str, Any] | None = None,
    *,
    sort: str = "recent",
    session: dict[str, Any] | None = None,
) -> str | None:
    data = index if index is not None else load_index()
    if str(category_id or "") not in STYLE_CATEGORY_IDS:
        return None
    cat = category_record(data, category_id) or {}
    sites = sites_for_category(data, category_id, sort=sort)
    en, zh = category_labels(category_id)
    den, dzh = category_definition(category_id)
    recent_cls = "active" if sort != "oldest" else ""
    oldest_cls = "active" if sort == "oldest" else ""
    if sites:
        cards = "".join(_site_card(s) for s in sites)
    else:
        cards = f'<p class="empty">{_i18n_span("empty_style")}</p>'
    _ = cat
    body = f"""
<p><a href="/">{_i18n_span("nav_home")}</a></p>
<header class="style-head">
  {_lang_span(en, zh, "h1")}
  {_lang_span(den, dzh, "p")}
</header>
<p class="sort-links">
  {_i18n_span("sort")}:
  <a class="{recent_cls}" href="/style/{_esc(category_id)}?sort=recent">{_i18n_span("sort_recent")}</a>
  <a class="{oldest_cls}" href="/style/{_esc(category_id)}?sort=oldest">{_i18n_span("sort_oldest")}</a>
</p>
<div class="grid">{cards}</div>"""
    return _chrome(f"{en} / {zh}", body, session=session)


def _ba_block(pairs: list[dict[str, Any]], facet: str) -> str:
    blocks: list[str] = []
    for pair in pairs:
        if not isinstance(pair, dict) or not pair.get("content_ok"):
            continue
        if _pair_facet(pair) != facet:
            continue
        before = str(pair.get("before") or "")
        after = str(pair.get("after") or "")
        blocks.append(
            f"""
<div class="ba">
  <figure>{_shot(before, "Before", zoom=True)}<figcaption>{_i18n_span("before")}</figcaption></figure>
  <figure>{_shot(after, "After", zoom=True)}<figcaption>{_i18n_span("after")}</figcaption></figure>
</div>"""
        )
    return "".join(blocks)


def _join_notes(*parts: Any) -> str:
    bits: list[str] = []
    for part in parts:
        text = _user_facing_analysis(str(part or ""))
        if text and text not in bits:
            bits.append(text)
    return " ".join(bits)


def _pair_obs(pairs: list[dict[str, Any]], facet: str) -> str:
    notes: list[str] = []
    for pair in pairs:
        if not isinstance(pair, dict) or not pair.get("content_ok"):
            continue
        if _pair_facet(pair) != facet:
            continue
        obs = _user_facing_analysis(str(pair.get("observation") or ""))
        if obs and obs not in notes:
            notes.append(obs)
    return " ".join(notes)


def _section(title_en: str, title_zh: str, body: str) -> str:
    if not (body or "").strip():
        return ""
    return (
        f"<section class='block'><h2>{_lang_span(title_en, title_zh)}</h2>{body}</section>"
    )


def _prompt_pre(en: str, zh: str) -> str:
    text_en = str(en or "").strip()
    text_zh = str(zh or "").strip() or text_en
    if not text_en:
        return ""
    return (
        '<pre class="code prompt-code"><code class="js-lang" '
        f'data-en="{_esc(text_en)}" data-zh="{_esc(text_zh)}">{_esc(text_en)}</code></pre>'
    )


def _facet_prompt(analysis: Any) -> str:
    cleaned = _user_facing_analysis(str(analysis or ""))
    if not cleaned:
        return ""
    boxed = _prompt_pre(cleaned, cleaned)
    if not boxed:
        return ""
    return (
        '<div class="prompt-box facet-prompt">'
        '<div class="prompt-toolbar">'
        f'<span class="prompt-kicker">{_i18n_span("prompt_kicker")}</span>'
        f'<button type="button" class="copy-prompt">{_i18n_span("copy")}</button>'
        "</div>"
        f"{boxed}</div>"
    )


def render_case_page(
    card: dict[str, Any],
    index: dict[str, Any] | None = None,
    *,
    session: dict[str, Any] | None = None,
) -> str:
    data = index if index is not None else load_index()
    url = str(card.get("url") or "")
    domain = site_domain(url) or "—"
    cid = str(card.get("id") or "")
    visual = card.get("visual") if isinstance(card.get("visual"), dict) else {}
    interaction = card.get("interaction") if isinstance(card.get("interaction"), dict) else {}
    frontend = card.get("frontend") if isinstance(card.get("frontend"), dict) else {}
    hero = pick_hero_screenshot(card)
    pairs = extract_before_after_pairs(card)
    index_row = site_by_id(data, cid)
    cat_id = str((index_row or {}).get("category_id") or "")
    back = ""
    if cat_id:
        en, zh = category_labels(cat_id)
        back = (
            f'<p><a href="/style/{_esc(cat_id)}">{_i18n_span("back")} — '
            f"{_lang_span(en, zh)}</a></p>"
        )

    hero_html = (
        f'<figure class="hero">{_shot(hero, domain, zoom=True)}</figure>'
        if hero
        else f'<p class="missing">{_i18n_span("no_hero")}</p>'
    )
    orig = (
        f'<p><a href="{_esc(url)}" target="_blank" rel="noopener">{_i18n_span("original")}</a></p>'
        if url
        else ""
    )

    fw = _framework_code(frontend)
    libs = _library_code(frontend)
    code_bits: list[str] = []
    for payload in (fw, libs):
        if isinstance(payload, dict):
            code_bits.extend(str(s) for s in (payload.get("snippets") or []) if s)
    code_html = ""
    if code_bits:
        code_html = "<pre class='code'><code>" + _esc("\n".join(code_bits)) + "</code></pre>"

    prompt_en = assemble_replication_prompt(card, lang="en")
    prompt_zh = assemble_replication_prompt(card, lang="zh")

    blocks = "".join(
        [
            _section(
                "Overall visual",
                "整体视觉",
                _facet_prompt(visual.get("style")),
            ),
            _section(
                "Typography",
                "字体",
                _facet_prompt(visual.get("typography")),
            ),
            _section(
                "Layout",
                "布局",
                _facet_prompt(_join_notes(visual.get("layout"), visual.get("spacing"))),
            ),
            _section(
                "Color",
                "配色",
                _facet_prompt(visual.get("color")),
            ),
            _section(
                "Imagery",
                "画面",
                _facet_prompt(_join_notes(visual.get("imagery"), visual.get("visual_effects"))),
            ),
            _section(
                "Animation",
                "动效",
                _facet_prompt(
                    _join_notes(interaction.get("transition"), _pair_obs(pairs, "animation"))
                )
                + _ba_block(pairs, "animation"),
            ),
            _section(
                "Scroll",
                "滚动",
                _facet_prompt(
                    _join_notes(interaction.get("scroll"), _pair_obs(pairs, "scroll"))
                )
                + _ba_block(pairs, "scroll"),
            ),
            _section(
                "Hover / Cursor",
                "悬停 / 光标",
                _facet_prompt(
                    _join_notes(
                        interaction.get("hover"),
                        interaction.get("cursor"),
                        _pair_obs(pairs, "hover_cursor"),
                    )
                )
                + _ba_block(pairs, "hover_cursor"),
            ),
            _section(
                "Interaction",
                "其他互动",
                _ba_block(pairs, "interaction"),
            ),
            _section("Frontend Evidence", "前端证据", code_html),
        ]
    )
    empty_notes = ""
    if "## " not in prompt_en:
        empty_notes = f"<p class='empty'>{_i18n_span('empty_case_notes')}</p>"

    prompt_html = f"""
<section class="block prompt-box">
  <div class="prompt-toolbar">
    <span class="prompt-kicker">{_i18n_span("prompt_kicker")}</span>
    <h2>{_i18n_span("prompt")}</h2>
    <button type="button" class="copy-prompt">{_i18n_span("copy")}</button>
  </div>
  <pre class="code prompt-code"><code class="js-lang" data-en="{_esc(prompt_en)}" data-zh="{_esc(prompt_zh)}">{_esc(prompt_en)}</code></pre>
</section>"""

    body = f"""
{back}
<h1>{_esc(domain)}</h1>
{orig}
{hero_html}
{empty_notes}
{blocks}
{prompt_html}"""
    return _chrome(domain, body, session=session)


def render_not_found(message: str = "Not found") -> str:
    body = f"<h1>{_i18n_span('not_found')}</h1><p>{_esc(message)}</p><p><a href='/'>{_i18n_span('nav_home')}</a></p>"
    return _chrome("Not found", body)


_CSS = """
:root { --ink:#1c1915; --muted:#6b645b; --bg:#f4efe6; --card:#fffdf8; --line:#ddd4c6; --accent:#c45c26; }
* { box-sizing:border-box; }
body { margin:0; font:16px/1.5 Georgia, "Songti SC", serif; background:var(--bg); color:var(--ink); }
a { color:var(--ink); }
.top { display:flex; justify-content:space-between; align-items:center; padding:16px 24px; border-bottom:1px solid var(--line); }
.brand { font-weight:700; text-decoration:none; }
nav { display:flex; gap:16px; align-items:center; }
main { max-width:1100px; margin:0 auto; padding:24px; }
.composer { margin:0 0 28px; }
.research-form { margin:0; }
.research-form textarea {
  width:100%; min-height:132px; resize:vertical; font:inherit; font-size:1.05rem;
  padding:16px 18px; border:1px solid var(--line); border-radius:16px; background:var(--card);
  box-shadow:0 1px 0 rgba(28,25,21,.04);
}
.composer-bar { display:flex; justify-content:space-between; align-items:center; gap:12px; margin-top:10px; flex-wrap:wrap; }
.status-inline { font-size:0.9rem; color:var(--muted); }
.status-inline strong { color:var(--ink); margin-right:8px; }
.status-running strong { color:#b8860b; }
.status-stopping strong { color:var(--accent); }
.status-completed strong { color:#2f6b3a; }
.status-failed strong { color:#a33; }
.composer-actions { display:flex; gap:8px; align-items:center; }
.library-head { display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap; margin:0 0 14px; }
.library-head h1 { margin:0; font-size:1.35rem; }
.search-form { display:flex; align-items:center; gap:8px; margin:0; background:transparent; border:0; padding:0; }
.search-form input[type="search"], .search-form select {
  font:inherit; font-size:0.82rem; padding:5px 8px; border:1px solid var(--line);
  border-radius:8px; background:#fff; min-width:0;
}
.search-form input[type="search"] { width:180px; }
.cancel-form { margin:0; padding:0; background:transparent; border:0; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:16px; }
.style-card, .site-card { background:var(--card); border:1px solid var(--line); border-radius:12px; overflow:hidden; text-decoration:none; display:block; color:inherit; }
.style-card.empty { opacity:0.72; }
.style-card img, .site-card img, .hero img, .ba img { width:100%; height:140px; object-fit:cover; display:block; background:#ddd8ce; }
.hero img { height:360px; }
.style-card, .site-card { padding:0 0 12px; }
.style-card h2, .site-card .domain { margin:10px 12px 0; font-size:1.05rem; }
.style-card p, .site-card .meta { margin:4px 12px 0; color:var(--muted); }
.site-card .meta { display:flex; justify-content:space-between; gap:8px; }
.orig { font-size:0.85rem; }
input, select, textarea, button { font:inherit; padding:8px 10px; border:1px solid var(--line); border-radius:8px; }
button { background:var(--accent); color:#fff; border:0; cursor:pointer; padding:8px 16px; }
button.ghost { background:transparent; color:var(--ink); border:1px solid var(--line); }
button:disabled { opacity:0.5; cursor:not-allowed; }
.hint { color:var(--muted); margin:8px 0 0; font-size:0.85rem; }
.sort-links a { margin-right:12px; }
.sort-links a.active { font-weight:700; }
.block { margin:24px 0; }
.ba { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:8px 0; }
.prompt-box { border:1px solid var(--line); border-radius:12px; overflow:hidden; background:#ece6db; }
.prompt-toolbar { display:flex; align-items:center; gap:10px; padding:10px 14px; background:#e4ddd0; color:var(--ink); }
.prompt-kicker { font:700 0.72rem/1 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; letter-spacing:0.12em; color:#8a5a28; }
.prompt-toolbar h2 { flex:1; margin:0; font-size:0.95rem; color:var(--ink); }
.prompt-toolbar .copy-prompt { background:#c45c26; }
.prompt-code { margin:0; border-radius:0; border:0; font:0.9rem/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.prompt, .code { white-space:pre-wrap; background:#ece6db; color:var(--ink); padding:16px; border-radius:10px; overflow:auto; }
.facet-prompt { margin:0 0 12px; }
.missing { background:#ddd8ce; min-height:140px; display:flex; align-items:center; justify-content:center; color:var(--muted); }
.empty { color:var(--muted); }
.lang-switch button { background:transparent; color:var(--ink); }
.lang-switch button.active { background:var(--ink); color:#fff; }
#lightbox { display:none; position:fixed; inset:0; background:rgba(0,0,0,.75); align-items:center; justify-content:center; }
#lightbox[aria-hidden="false"] { display:flex; }
#lightbox img { max-width:90vw; max-height:90vh; }
#lightbox-close { position:absolute; top:16px; right:16px; }
@media (max-width:720px) {
  .search-form { width:100%; }
  .search-form input[type="search"] { flex:1; width:auto; }
}
"""

_JS = """
(function () {
  const I18N = """ + json.dumps(I18N, ensure_ascii=False) + """;
  const applyLang = (lang) => {
    const dict = I18N[lang] || I18N.en;
    document.body.setAttribute("data-lang", lang);
    document.documentElement.setAttribute("lang", lang === "zh" ? "zh-CN" : "en");
    document.querySelectorAll(".js-lang").forEach((el) => {
      const text = lang === "zh" ? el.getAttribute("data-zh") : el.getAttribute("data-en");
      if (text != null) el.textContent = text;
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      const key = el.getAttribute("data-i18n-placeholder");
      if (key && dict[key] != null) el.setAttribute("placeholder", dict[key]);
    });
    document.querySelectorAll("option[data-en]").forEach((el) => {
      const text = lang === "zh" ? el.getAttribute("data-zh") : el.getAttribute("data-en");
      if (text != null) el.textContent = text;
    });
    document.querySelectorAll("[data-lang-btn]").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-lang-btn") === lang);
    });
    try { localStorage.setItem("wwr_library_lang", lang); } catch (_) {}
  };
  document.querySelectorAll("[data-lang-btn]").forEach((btn) => {
    btn.addEventListener("click", () => applyLang(btn.getAttribute("data-lang-btn")));
  });
  let initial = "en";
  try {
    const saved = localStorage.getItem("wwr_library_lang");
    if (saved === "zh" || saved === "en") initial = saved;
  } catch (_) {}
  applyLang(initial);

  const researchForm = document.getElementById("research-form");
  if (researchForm) {
    const area = researchForm.querySelector("textarea");
    if (area) {
      area.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
          e.preventDefault();
          researchForm.requestSubmit();
        }
      });
    }
  }

  document.querySelectorAll(".copy-prompt").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const box = btn.closest(".prompt-box");
      const block = box ? box.querySelector(".prompt-code") : null;
      const text = block ? (block.textContent || "") : "";
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
        btn.textContent = "OK";
        setTimeout(() => applyLang(document.body.getAttribute("data-lang") || "en"), 900);
      } catch (_) {}
    });
  });

  const lb = document.getElementById("lightbox");
  const img = document.getElementById("lightbox-img");
  if (lb && img) {
    const close = () => { lb.setAttribute("aria-hidden", "true"); };
    const closeBtn = document.getElementById("lightbox-close");
    if (closeBtn) closeBtn.addEventListener("click", close);
    lb.addEventListener("click", (e) => { if (e.target === lb) close(); });
    document.querySelectorAll(".zoomable").forEach((el) => {
      if (el.closest("a[href]")) return;
      el.addEventListener("click", (e) => {
        e.preventDefault();
        img.src = el.getAttribute("data-full") || el.getAttribute("src") || "";
        lb.setAttribute("aria-hidden", "false");
      });
    });
  }

  const status = document.body.getAttribute("data-status");
  if (status === "running" || status === "stopping") {
    setInterval(async () => {
      try {
        const res = await fetch("/api/status");
        const data = await res.json();
        if (data && data.status && data.status !== status) location.reload();
      } catch (_) {}
    }, 3000);
  }
})();
"""
