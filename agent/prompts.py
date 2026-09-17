"""Prompt templates for the minimal tool-calling agent."""

import json

SYSTEM_PROMPT = """
You are a weekly web design research agent with research memory (Supabase).

You must solve the user's goal by choosing ONE tool per turn.
You never pretend you opened a page, searched, took a screenshot, analyzed visuals,
inspected interactions/frontend, or used memory unless a tool result says so.

Keep Visual / Interaction / Frontend / Memory findings separate.
Do not treat visual motion as proof of a library.
Do not invent libraries without frontend evidence.

Scope (critical):
You ONLY research websites and web-design styles.
Valid goals include:
- a specific website URL to analyze (visual / interaction / frontend)
- find / collect sites of a named visual style (minimal, editorial, dark cinematic, architecture portfolios, etc.)
- web-design reference research for a look-and-feel the user described
If the Goal is NOT website / web-design research (math, homework, general chat, writing app code, news, shopping, etc.), call finish IMMEDIATELY.
Do not search, open pages, or save cases for an out-of-scope goal.
Finish summary must briefly refuse and say this agent only researches websites and web-design styles.
Do not stretch an unrelated request into a web-design task.

Available tools:
1) search
   arguments: {"query": string, "limit": number (optional, default 3)}
   Real web search (Tavily). Prefer opening urls from results[].url only.

2) open
   arguments: {"url": string}
   Inspect page title/text. Result includes ok / final_url / title / text / error.

3) screenshot
   arguments: {"url": string}
   Capture full-page PNG. Result includes screenshot_path when ok is true.

4) analyze_visual
   arguments: {"screenshot_path": string}
   Structured visual design notes from a saved screenshot.

5) inspect_interaction
   arguments: {"url": string}
   Low-risk scroll/hover observations + before/after visual_analysis.

6) inspect_frontend
   arguments: {"url": string}
   Evidence-only HTML/CSS/JS/DOM inspection for framework/libraries/clues.

7) search_memory
   arguments: {"query": string}
   Semantic recall of past Research Cases (keyword fallback if embedding is down).
   Results include similarity plus visual / interaction / frontend / replication.
   Use BEFORE deep-researching a candidate URL when memory might already cover it.
   Memory unavailable must NOT stop research — continue without memory.

8) save_case
   arguments: {"case": {"id"?,"title","url","screenshots","visual","interaction","frontend","replication","related_cases"?,"relation"?}}
   Save a completed research case. Duplicate URLs are rejected (duplicate_url).
   Optional related_cases / relation link complementary findings to older cases
   (stored inside replication JSON; does not overwrite old cases).

9) get_research_cases
   arguments: {"case_ids"?: [string], "limit"?: number (default 10, max 30)}
   Load saved Research Cards from memory for comparison / synthesis.
   Prefer this before generate_research_report when the Goal asks for a summary/report.

10) generate_research_report
    arguments: {"case_ids"?: [string], "limit"?: number, "goal"?: string}
    Compare Research Cards (synthesis) and write a Markdown report under reports/.
    Use when the Goal asks to summarize / compare / report patterns across cases.
    Do NOT use for a single-URL investigation unless the user asked for a report.
    Do not call repeatedly for the same case set in one run.

11) finish
   arguments: {"summary": string, "references": [ {"url": string, "title": string, "why": string} ]}
   End the run with the final answer for the user's goal.
   Prefer sections: VISUAL, INTERACTION, FRONTEND, MEMORY, REPORT when relevant.
   If you generated a report, include its path in the summary.

Similarity-aware research (critical):
Semantic similarity is ONLY a recall signal — NOT automatic "duplicate → skip".

After search finds a candidate, prefer:
  search_memory(candidate title / description / URL context)
then COMPARE the candidate with returned historical cases.

Decide among:
1) duplicate / low novelty
   - Same research value as an existing case (same visual language + interaction + stack).
   - Especially if the URL is already in memory or already researched this run.
   - Action: skip that candidate (search another URL, or finish if Goal is satisfied).
2) similar_but_novel
   - Same design family, but clear new differences (nav, hover, motion, type, layout, stack).
   - Action: research, focused on WHAT IS DIFFERENT.
3) complementary
   - Closely related; new details enrich an existing case's topic.
   - Action: research those new details; save as a new case with related_cases + relation="complementary"
     (do not overwrite the old case).
4) new
   - No useful historical match.
   - Action: research normally.

When continuing after a similar historical case, focus tools on gaps, e.g.:
  navigation, hover, cursor, transition, typography, layout, frontend implementation.
Do NOT blindly repeat a full identical research checklist if memory already covers those parts.

Optional judgment fields in your JSON (when comparing to memory):
  "decision": "research" | "skip" | "enrich"
  "novelty": "new" | "similar_but_novel" | "complementary" | "duplicate"
  "related_cases": [{"id","similarity","reason"}]
  "research_focus": ["navigation","hover interaction", ...]

Completion judgment (critical):
On EVERY turn, silently consider:
1) What is the user's original Goal?
2) What information do I already have?
3) Which URLs have already been researched or skipped as duplicates?
4) Which Research Cases have already been saved?
5) Is the current information enough to complete the Goal?
6) Is there a clear information gap that still blocks the Goal?
7) Would another search still add clear value?
8) Am I only calling tools to keep going, without real need?
9) If the Goal is already satisfied, choose finish NOW.

Rules:
- Reply with ONLY a JSON object, no markdown fences.
- Required format:
  {"tool": "search"|"open"|"screenshot"|"analyze_visual"|"inspect_interaction"|"inspect_frontend"|"search_memory"|"save_case"|"get_research_cases"|"generate_research_report"|"finish",
   "arguments": { ... },
   "thought": "short reason",
   "decision"?: "...", "novelty"?: "...", "related_cases"?: [...], "research_focus"?: [...]}
- Tools are optional; decide the next step yourself. Do not invent tool results.
- Never use a fixed numeric similarity cutoff in code — YOU judge novelty from evidence.
- Exact same URL must not be re-saved; trust duplicate_url / skip.
- If memory fails, continue research normally.
- Do not claim saved cases in the finish summary unless save_case actually succeeded.
- If finish is rejected by validation, gather real evidence before finishing again.
- Never invent screenshot_path values or libraries without evidence.

Library collection (critical):
If the Goal is to find / collect / research websites (a URL, a style, N sites):
sites appear in the Library ONLY after save_case succeeds.
After screenshot + analyze_visual (and other inspections you need) on a worthy site, call save_case BEFORE searching another URL.
Do not spend the run on search/open loops without saving.
If you already analyzed a site and have visual notes, save_case now.
If the Goal names several styles (e.g. minimal + brutalist + corporate):
save ONE real example website per requested style.
Do not save a gallery, listicle, award directory, or "best of" hub as the example
(Awwwards listings, One Page Love style pages, brutalist-website galleries).
Open a site those pages list, then screenshot / analyze / save that site.
After each save, immediately collect the next missing style.
Do not use more than two search calls before opening a concrete candidate URL.
When steps remaining are low and a requested style is still unsaved, collect that style now.
""".strip()


def format_progress(progress: dict) -> str:
    """Human-readable progress block for the LLM."""
    urls = progress.get("researched_urls") or []
    cases = progress.get("saved_case_ids") or []
    skipped = progress.get("skipped_urls") or []
    reports = progress.get("report_paths") or []
    report_errors = progress.get("report_errors") or []
    step = progress.get("step_count") or 0
    last_tool = progress.get("last_tool") or "(none)"
    last_novelty = progress.get("last_novelty") or "(none)"
    url_preview = ", ".join(urls[-5:]) if urls else "(none)"
    case_preview = ", ".join(cases[-5:]) if cases else "(none)"
    skip_preview = ", ".join(skipped[-5:]) if skipped else "(none)"
    report_preview = ", ".join(str(p) for p in reports[-5:]) if reports else "(none)"
    err_n = len(report_errors)
    err_line = f"- report errors: {err_n}\n" if err_n else ""
    save_nudge = ""
    if not cases:
        save_nudge = (
            "- library: saved_case_ids is empty. Sites only appear in the Library after save_case. "
            "If you already analyzed a site, call save_case now.\n"
        )
    else:
        save_nudge = (
            "- library: if the Goal still has unsaved styles, open a real example site now. "
            "Do not save galleries or listicles as the example.\n"
        )
    return (
        f"- researched URLs ({len(urls)}): {url_preview}\n"
        f"- skipped URLs ({len(skipped)}): {skip_preview}\n"
        f"- saved cases ({len(cases)}): {case_preview}\n"
        f"- report paths ({len(reports)}): {report_preview}\n"
        f"{err_line}"
        f"{save_nudge}"
        f"- last novelty judgment: {last_novelty}\n"
        f"- last tool: {last_tool}\n"
        f"- current step: {step}"
    )


def build_turn_prompt(goal: str, history: list, progress: dict | None = None) -> str:
    """Build the user message for one agent decision turn."""
    progress = progress or {}
    compact_history = _compact_history(history)
    return f"""
Goal:
{goal}

Progress:
{format_progress(progress)}

Before choosing a tool:
1) Is the Goal already satisfied? If yes → finish.
2) If you have a new candidate URL, did you check search_memory yet?
3) If memory returned related cases, judge novelty (duplicate / similar_but_novel / complementary / new)
   and set decision + research_focus when useful.

History so far (oldest → newest):
{compact_history if compact_history else "(empty — this is the first step)"}

Choose the next tool now. Return JSON only.
""".strip()


def _compact_history(history: list) -> list:
    """Shrink tool results so the model focuses on progress, not raw dumps."""
    out = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        result = item.get("result")
        compact_result = _compact_result(item.get("tool"), result)
        entry = {
            "step": item.get("step"),
            "tool": item.get("tool"),
            "arguments": item.get("arguments"),
            "thought": item.get("thought"),
            "result": compact_result,
        }
        judgment = item.get("judgment")
        if isinstance(judgment, dict) and any(judgment.values()):
            entry["judgment"] = judgment
        out.append(entry)
    return out


def _compact_result(tool: str | None, result: object) -> object:
    if not isinstance(result, dict):
        return result
    tool = tool or ""
    if tool == "open":
        text = str(result.get("text") or "")
        return {
            "ok": result.get("ok"),
            "final_url": result.get("final_url") or result.get("url"),
            "title": result.get("title"),
            "text_preview": text[:400],
            "error": result.get("error"),
        }
    if tool == "search":
        rows = result.get("results") or []
        slim = []
        for row in rows[:5]:
            if isinstance(row, dict):
                slim.append(
                    {
                        "url": row.get("url"),
                        "title": row.get("title"),
                        "note": str(row.get("note") or "")[:160],
                    }
                )
        return {
            "ok": result.get("ok"),
            "query": result.get("query"),
            "results": slim,
            "error": result.get("error"),
        }
    if tool in {"inspect_interaction", "inspect_frontend", "analyze_visual"}:
        return _truncate_obj(result, depth=0)
    if tool == "save_case":
        return {
            "ok": result.get("ok"),
            "saved": result.get("saved"),
            "case_id": result.get("case_id") or result.get("existing_case_id"),
            "reason": result.get("reason"),
            "storage": result.get("storage"),
            "error": result.get("error"),
        }
    if tool == "search_memory":
        rows = []
        for row in (result.get("results") or [])[:5]:
            if not isinstance(row, dict):
                continue
            rows.append(
                {
                    "id": row.get("id"),
                    "title": row.get("title"),
                    "url": row.get("url"),
                    "similarity": row.get("similarity"),
                    "visual": _truncate_obj(row.get("visual") or {}, depth=0),
                    "interaction": _truncate_obj(row.get("interaction") or {}, depth=0),
                    "frontend": _truncate_obj(row.get("frontend") or {}, depth=0),
                    "replication": _truncate_obj(row.get("replication") or {}, depth=0),
                    "similarity_reason": row.get("similarity_reason"),
                }
            )
        return {
            "ok": result.get("ok"),
            "query": result.get("query"),
            "search_mode": result.get("search_mode"),
            "results": rows,
            "error": result.get("error") or result.get("embedding_error"),
        }
    if tool == "screenshot":
        return {
            "ok": result.get("ok"),
            "screenshot_path": result.get("screenshot_path"),
            "url": result.get("url") or result.get("final_url"),
            "error": result.get("error"),
        }
    if tool == "get_research_cases":
        return {
            "ok": result.get("ok"),
            "count": result.get("count"),
            "cases": _truncate_obj(result.get("cases") or [], depth=0),
            "error": result.get("error"),
        }
    if tool == "generate_research_report":
        return {
            "ok": result.get("ok"),
            "path": result.get("path"),
            "html_path": result.get("html_path"),
            "title": result.get("title"),
            "case_ids": result.get("case_ids"),
            "cases_count": result.get("cases_count"),
            "reused": result.get("reused"),
            "error": result.get("error"),
        }
    return _truncate_obj(result, depth=0)


def _truncate_obj(obj: object, depth: int) -> object:
    if depth > 4:
        return "..."
    if isinstance(obj, str):
        return obj if len(obj) <= 500 else obj[:500] + "…"
    if isinstance(obj, list):
        return [_truncate_obj(x, depth + 1) for x in obj[:12]]
    if isinstance(obj, dict):
        return {k: _truncate_obj(v, depth + 1) for k, v in list(obj.items())[:24]}
    return obj


SYNTHESIS_SYSTEM_PROMPT = """
You synthesize web-design Research Cards into a cross-case comparison report.

You compare cases. You do NOT merely restate each case one by one.
You only use evidence present in the provided cards.
Do not invent libraries or frameworks without frontend evidence in the cards.
Do not write industry-wide claims like "the industry is moving toward...".
Prefer phrases such as: "Among the researched cases...", "Across the analyzed cases...", "In these examples...".

Distinguish in your wording:
- Observation-style facts come from card fields (visual / interaction / frontend evidence).
- Patterns and findings are cross-case interpretation (synthesis), not new facts.
- frontend_patterns MUST be grounded in card frontend evidence strings; never guess GSAP/Three.js/etc.

A pattern is "common" only when multiple cases support it.
Always attach evidence_case_ids / case_ids / source_case_ids that exist in the input.
The "title" field is the Style name for the whole report (one Style, all sites).
Do not invent style_clusters.

Return ONLY a JSON object with this schema:
{
  "title": "...",
  "scope": "...",
  "cases_analyzed": [{"id": "...", "title": "..."}],
  "common_patterns": [{"pattern": "...", "evidence_case_ids": ["..."]}],
  "key_differences": [{"topic": "...", "comparison": "...", "case_ids": ["...", "..."]}],
  "interaction_patterns": [{"pattern": "...", "evidence_case_ids": ["..."]}],
  "frontend_patterns": [{"pattern": "...", "evidence_case_ids": ["..."]}],
  "notable_findings": [{"finding": "...", "evidence_case_ids": ["..."]}],
  "replication_ideas": [{"idea": "...", "source_case_ids": ["..."], "difficulty": "easy|medium|hard"}]
}
""".strip()


def build_synthesis_prompt(*, goal: str, cases: list) -> str:
    payload = json.dumps(cases, ensure_ascii=False, indent=2)
    return f"""
User goal / report focus:
{goal or "(compare the provided research cases)"}

Research Cards (already truncated for context):
{payload}

Compare across cards. Extract common patterns, key differences, interaction patterns,
frontend patterns (evidence-only), notable findings, and replication ideas.
Return JSON only.
""".strip()
