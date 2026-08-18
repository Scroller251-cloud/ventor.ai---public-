from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

import httpx

from browser_controller import validate_url
from realtime import web_search


def _text(html: str, limit: int = 9000) -> str:
    cleaned = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html, flags=re.I)
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", cleaned)).split())[:limit]


async def _fetch_public_html(client: httpx.AsyncClient, url: str) -> httpx.Response:
    current = validate_url(url)
    for _ in range(4):
        response = await client.get(current, follow_redirects=False)
        if response.is_redirect:
            location = response.headers.get("location")
            if not location:
                return response
            current = validate_url(urljoin(current, location))
            continue
        return response
    raise ValueError("Too many redirects")


async def research(query: str, limit: int = 5) -> dict:
    query = query.strip()
    if not query:
        raise ValueError("query is required")
    limit = max(1, min(int(limit), 8))
    results = await web_search(query, limit)
    sources = []
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "Ventor/3.0"}) as client:
        for item in results:
            url = item.get("url")
            if not url or url.startswith("/"):
                continue
            try:
                response = await _fetch_public_html(client, url)
                response.raise_for_status()
                if "text/html" not in response.headers.get("content-type", ""):
                    continue
                sources.append({"title": item.get("title", ""), "url": str(response.url), "excerpt": _text(response.text)})
            except Exception:
                continue
    return {"query": query, "sources": sources, "source_count": len(sources),
            "note": "Sources are evidence only; Ventor must distinguish evidence from inference."}
