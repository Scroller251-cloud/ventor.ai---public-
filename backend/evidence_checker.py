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
    urls = re.findall(r'https?://[^\s)\]>]+', text or '')
    valid = [u for u in urls if urlparse(u).scheme in {'http', 'https'} and bool(urlparse(u).netloc)]
    return EvidenceCheck(urls, len(urls), len(valid), ['URL syntax check only; this does not establish factual truth.'])
