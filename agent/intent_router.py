"""Pure request routing for the bounded website-research orchestrator.

No model calls, browser work, database calls, or file writes in this module.
A model may suggest an intent/search query, but may NOT invent target URLs.
"""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

MAX_SITES = 5
MAX_GOAL_CHARS = 4000
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
RESEARCH_HINTS = (
    "研究", "调研", "分析网站", "分析网页", "视觉", "案例", "参考网站",
    "寻找网站", "找网站", "网页设计", "交互", "web design",
    "research", "analyze", "analyse", "inspiration", "reference site",
)
GENERATION_HINTS = (
    "生成应用", "生成模板", "制作应用", "开发应用", "应用生成",
    "搭建应用", "生成app", "build an app", "generate an app",
    "create an app", "generate a template",
)
COUNT_RE = re.compile(r"([1-5])\s*(?:个|家|条|款|sites?\b|websites?\b)", re.I)
GENERATION_RE = re.compile(r"(?:生成|制作|开发|搭建|创建).{0,12}(?:应用|模板|app)", re.I)


def normalize_url(value: str) -> str | None:
    """Allow http(s) public website URLs only; avoid private/local browser targets."""
    raw = (value or "").strip().rstrip(".,;:!?，。；：！？)]）}>'\"")
    if not raw:
        return None
    try:
        parsed = urlsplit(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username or parsed.password:
            return None
        host = parsed.hostname.lower().rstrip(".")
        if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
            return None
        try:
            address = ipaddress.ip_address(host)
            if not address.is_global:
                return None
        except ValueError:
            pass
        # Preserve URL paths; only remove an insignificant root slash and fragment.
        path = parsed.path.rstrip("/") if parsed.path == "/" else parsed.path
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))
    except ValueError:
        return None


def extract_urls(goal: str) -> list[str]:
    found, seen = [], set()
    for match in URL_RE.findall(goal or ""):
        url = normalize_url(match)
        if url is not None and url not in seen:
            found.append(url)
            seen.add(url)
    return found


def plan_request(goal: str, model_output: dict | None = None) -> dict:
    """Turn a natural-language query into an explicit, safe routing decision.

    Only URLs physically present in the original request can be direct targets.
    For discovery, candidate URLs must come from a real search result later.
    """
    if not isinstance(goal, str) or not goal.strip() or len(goal) > MAX_GOAL_CHARS:
        raise ValueError("goal must be non-empty and no longer than 4000 characters")
    goal = goal.strip()
    lowered = goal.lower()
    urls = extract_urls(goal)
    model_output = model_output if isinstance(model_output, dict) else {}
    wants_generation = (
        any(marker in lowered for marker in GENERATION_HINTS)
        or bool(GENERATION_RE.search(lowered))
        or model_output.get("wants_app_generation") is True
    )
    research = bool(urls) or any(marker in lowered for marker in RESEARCH_HINTS)
    model_intent = model_output.get("intent")
    if not research and model_intent in {"website_research", "website_discovery"}:
        research = True
    if urls:
        intent, status = "website_research", "ready"
    elif research:
        intent, status = "website_discovery", "needs_discovery"
    elif wants_generation:
        intent, status = "app_generation", "unsupported"
    else:
        intent, status = "out_of_scope", "unsupported"

    count = len(urls) if urls else 3
    count_match = COUNT_RE.search(goal)
    if not urls and count_match:
        count = int(count_match.group(1))
    if not urls and type(model_output.get("requested_sites")) is int:
        count = model_output["requested_sites"]
    count = max(1, min(MAX_SITES, count))
    query = model_output.get("search_query")
    query = query.strip()[:250] if isinstance(query, str) and query.strip() else goal[:250]

    return {
        "schema_version": 1,
        "original_goal": goal,
        "intent": intent,
        "status": status,
        "target_urls": urls[:MAX_SITES],
        "requested_sites": count,
        "search_query": query if status == "needs_discovery" else None,
        "wants_app_generation": wants_generation,
        "app_generation_supported": False,
        "truncated_targets": len(urls) > MAX_SITES,
    }


def task_manifest(plan: dict, discovery_results: list[dict] | None = None) -> list[dict]:
    """Make site-scoped tasks that can be run by the existing agent.batch runner."""
    if plan.get("status") not in {"ready", "needs_discovery"}:
        return []
    if plan["status"] == "needs_discovery" and discovery_results is None:
        return []
    candidates = (
        [{"url": value} for value in plan["target_urls"]]
        if plan["status"] == "ready"
        else discovery_results or []
    )
    urls, seen, hosts = [], set(), set()
    max_sites = min(MAX_SITES, int(plan.get("requested_sites") or 1))
    for item in candidates:
        if not isinstance(item, dict):
            continue
        url = normalize_url(str(item.get("url") or ""))
        if not url or url in seen:
            continue
        host = urlsplit(url).hostname
        # Discovery should return independent sites, not five pages from one domain.
        if plan["status"] == "needs_discovery" and host in hosts:
            continue
        urls.append(url)
        seen.add(url)
        hosts.add(host)
        if len(urls) >= max_sites:
            break
    tasks = []
    for i, url in enumerate(urls, 1):
        tasks.append({
            "task_id": f"site_{i:03d}",
            "target_url": url,
            "goal": (
                f"对 {url} 进行网页视觉研究。根据真实网页证据调查布局、颜色、"
                "字体、视觉效果及前端线索；不要把关键词提及当作框架使用证据；"
                "截图不完整时明确说明限制。保存一条有证据的研究案例。"
                "只进行网站研究与案例沉淀，不执行应用生成。"
            ),
        })
    return tasks


def summarize_batch(plan: dict, batch: dict) -> dict:
    """Aggregate operational results without fabricating a business-quality pass."""
    results = batch.get("results") if isinstance(batch, dict) else {}
    results = results if isinstance(results, dict) else {}
    return {
        "intent": plan.get("intent"),
        "batch_id": batch.get("batch_id") if isinstance(batch, dict) else None,
        "task_count": len(results),
        "technical_finished": sum(
            1 for result in results.values()
            if isinstance(result, dict) and result.get("status") == "finished"
        ),
        "saved_case_count": sum(
            len(result.get("saved_case_ids") or [])
            for result in results.values() if isinstance(result, dict)
        ),
        "failed_tasks": [
            key for key, result in results.items()
            if not isinstance(result, dict) or result.get("status") != "finished"
        ],
        "business_pass": None,
        "quality_review_required": True,
        "generation_handoff_required": bool(plan.get("wants_app_generation")),
        "generation_implemented": False,
    }
