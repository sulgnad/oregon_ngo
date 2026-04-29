"""DuckDuckGo HTML search engine adapter (no API key required)."""

from __future__ import annotations

from typing import Iterable
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from bs4 import BeautifulSoup

from ..protocols import HttpClient, SearchResult


DDG_HTML_ENDPOINT = "https://html.duckduckgo.com/html/"


class DuckDuckGoSearch:
    """Parses DuckDuckGo HTML search results.

    Takes an injected ``HttpClient`` so tests can swap in a ``FakeHttpClient``
    that returns a captured fixture page.
    """

    name = "duckduckgo"

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def search(self, query: str, *, max_results: int = 10) -> list[SearchResult]:
        url = f"{DDG_HTML_ENDPOINT}?{urlencode({'q': query})}"
        resp = self._http.get(url)
        if resp.status_code >= 400:
            return []
        return list(self._parse(resp.text, max_results=max_results))

    @staticmethod
    def _parse(html: str, *, max_results: int) -> Iterable[SearchResult]:
        soup = BeautifulSoup(html, "lxml")
        results = soup.select("div.result")
        emitted = 0
        for node in results:
            link = node.select_one("a.result__a")
            snippet_node = node.select_one("a.result__snippet, div.result__snippet")
            if link is None:
                continue
            href = link.get("href", "")
            real_url = _unwrap_redirect(href)
            if not real_url:
                continue
            yield SearchResult(
                title=link.get_text(strip=True),
                url=real_url,
                snippet=snippet_node.get_text(" ", strip=True) if snippet_node else "",
            )
            emitted += 1
            if emitted >= max_results:
                return


def _unwrap_redirect(href: str) -> str:
    """DuckDuckGo wraps result URLs in ``/l/?uddg=<encoded>``. Unwrap it."""
    if not href:
        return ""
    parsed = urlparse(href)
    if parsed.path.endswith("/l/") or parsed.path == "/l/":
        params = parse_qs(parsed.query)
        target = params.get("uddg", [""])[0]
        if target:
            return unquote(target)
    if href.startswith("//"):
        return "https:" + href
    return href
