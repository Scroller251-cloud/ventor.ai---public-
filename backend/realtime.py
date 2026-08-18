from __future__ import annotations

import datetime as dt
import re
from html import unescape

import httpx


def now_info() -> dict[str, str]:
    now = dt.datetime.now().astimezone()
    return {"iso": now.isoformat(), "date": now.date().isoformat(), "weekday": now.strftime("%A"),
            "time": now.strftime("%H:%M:%S"), "timezone": str(now.tzinfo), "utc": dt.datetime.now(dt.timezone.utc).isoformat()}


def needs_realtime(text: str) -> bool:
    return bool(re.search(r"\b(today|now|current|latest|real[- ]?time|this week|this month|weather|news|price|stock|time in|date)\b", text, re.I))


async def web_search(query: str, limit: int = 5) -> list[dict]:
    limit = max(1, min(int(limit), 10))
    try:
        async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "Ventor/1.0"}) as client:
            response = await client.get("https://html.duckduckgo.com/html/", params={"q": query})
            response.raise_for_status()
        hits = []
        for match in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', response.text, re.S):
            hits.append({"title": unescape(re.sub(r"<.*?>", "", match.group(2))), "url": match.group(1)})
            if len(hits) >= limit:
                break
        return hits
    except Exception as exc:
        return [{"error": type(exc).__name__}]
