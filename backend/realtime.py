from __future__ import annotations

import datetime as dt
import re
from html import unescape

import httpx

_CLIENT: httpx.AsyncClient | None = None


def now_info():
    now = dt.datetime.now().astimezone()
    return {"iso": now.isoformat(), "date": now.date().isoformat(), "weekday": now.strftime("%A"), "time": now.strftime("%H:%M:%S"), "timezone": str(now.tzinfo), "utc": dt.datetime.now(dt.timezone.utc).isoformat()}


def needs_realtime(text):
    return bool(re.search(r"\b(today|now|current|latest|real[- ]?time|this week|this month|weather|news|price|stock|time in|date)\b", text, re.I))


async def _client():
    global _CLIENT
    if _CLIENT is None or _CLIENT.is_closed:
        _CLIENT = httpx.AsyncClient(timeout=8, headers={"User-Agent": "Ventor/3.0"}, limits=httpx.Limits(max_connections=16, max_keepalive_connections=4))
    return _CLIENT


async def web_search(query, limit=5):
    limit = max(1, min(int(limit), 8))
    try:
        client = await _client()
        response = await client.get("https://html.duckduckgo.com/html/", params={"q": str(query)[:1000]})
        response.raise_for_status()
        hits = []
        for match in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', response.text, re.S):
            hits.append({"title": unescape(re.sub("<.*?>", "", match.group(2))), "url": match.group(1)})
            if len(hits) >= limit:
                break
        return hits
    except Exception as exc:
        return [{"error": type(exc).__name__}]
