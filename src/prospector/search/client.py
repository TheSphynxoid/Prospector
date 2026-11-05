"""SearXNG's JSON API. Never raises: a failed search is a SearchResult with `error` set."""
import json
from dataclasses import dataclass, field

import httpx

from prospector.http import describe_error

TIMEOUT = 30


@dataclass
class Hit:
    title: str
    url: str
    snippet: str


@dataclass
class SearchResult:
    results: list[Hit] = field(default_factory=list)
    throttled: bool = False
    error: str | None = None


def search_ready(ctx) -> bool:
    return bool(ctx.settings.searxng_url)


def search(ctx, query: str, engines: str | None = "brave", max_results: int = 20) -> SearchResult:
    """One search. `engines=None` uses the instance's default engines. `throttled` means a requested engine
    reported itself unresponsive (CAPTCHA, rate limit, timeout)."""
    base = ctx.settings.searxng_url
    if not base:
        return SearchResult(error="Web search is not set up")
    params = {"q": query, "format": "json"}
    if engines:
        params["engines"] = engines
    try:
        r = ctx.http.get(f"{base.rstrip('/')}/search", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        return SearchResult(error=describe_error(e))
    except (json.JSONDecodeError, ValueError):
        return SearchResult(error="SearXNG did not answer with JSON (is format=json enabled?)")
    if not isinstance(data, dict):
        return SearchResult(error="SearXNG answered with an unexpected shape")
    hits = []
    for item in data.get("results") or []:
        if isinstance(item, dict) and item.get("url"):
            hits.append(Hit(str(item.get("title") or ""), str(item["url"]), str(item.get("content") or "")))
        if len(hits) >= max_results:
            break
    wanted = set(engines.split(",")) if engines else None
    down = {str(e[0]) for e in data.get("unresponsive_engines") or [] if isinstance(e, list | tuple) and e}
    throttled = bool(down & wanted) if wanted else False
    return SearchResult(hits, throttled, None)
