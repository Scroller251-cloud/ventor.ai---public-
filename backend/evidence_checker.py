from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlparse


@dataclass
class EvidenceCheck:
    urls: list[str]
    checked: int
    valid_syntax: int
    notes: list[str]


async def check_urls(text: str) -> EvidenceCheck:
    urls = re.findall(r"https?://[^\s)\]>]+", text or "")
    valid = [
        url
        for url in urls
        if urlparse(url).scheme in {"http", "https"} and bool(urlparse(url).netloc)
    ]
    return EvidenceCheck(
        urls=urls,
        checked=len(urls),
        valid_syntax=len(valid),
        notes=[
            "URL syntax check only; this does not establish factual truth."
        ],
    )
