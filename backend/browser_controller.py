from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class BrowserPolicyError(ValueError):
    pass


def validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise BrowserPolicyError("Only http(s) URLs are allowed")
    if parsed.username or parsed.password:
        raise BrowserPolicyError("Credential-bearing URLs are not allowed")
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise BrowserPolicyError("Local hostnames are blocked")
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        for addr in {x[4][0] for x in infos}:
            ip = ipaddress.ip_address(addr)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
                raise BrowserPolicyError("Private or non-public network targets are blocked")
    except socket.gaierror as exc:
        raise BrowserPolicyError("Host could not be resolved") from exc
    return url


def _clean_text(text: str, limit: int = 12000) -> str:
    return " ".join(text.split())[:limit]


async def open_page(url: str, *, timeout_ms: int = 15000) -> dict:
    validate_url(url)
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is not installed; install the browser runtime before using this capability") from exc
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context(ignore_https_errors=False)
            async def guard_route(route):
                try:
                    validate_url(route.request.url)
                    await route.continue_()
                except BrowserPolicyError:
                    await route.abort("blockedbyclient")
            await context.route("**/*", guard_route)
            page = await context.new_page()
            response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            validate_url(page.url)
            return {"url": page.url, "status": response.status if response else None, "title": await page.title(), "text": _clean_text(await page.locator("body").inner_text()), "links": await page.locator("a[href]").evaluate_all("els => els.slice(0, 30).map(a => ({text:(a.innerText||'').trim(), href:a.href}))")}
        finally:
            await browser.close()
