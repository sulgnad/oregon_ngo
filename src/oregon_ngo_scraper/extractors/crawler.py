"""Crawl an organization's website for pages likely to contain mission text."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..models import FetchedPage
from ..protocols import Browser, HttpClient, RobotsChecker


# Path candidates checked in priority order. Per the project README in the
# starter spreadsheet, prioritise: /about, /about-us, /mission, /our-mission,
# /who-we-are, /what-we-do.
DEFAULT_CANDIDATE_PATHS: tuple[str, ...] = (
    "/",
    "/about",
    "/about-us",
    "/about/mission",
    "/our-mission",
    "/mission",
    "/mission-vision-values",
    "/mission-values",
    "/mission-and-values",
    "/who-we-are",
    "/what-we-do",
    "/values",
    "/our-values",
    "/our-story",
)

NAV_TEXT_RE = re.compile(r"(?i)mission|about|who we are|what we do|values|our story")


class _AllowAllRobots:
    """Default robots checker that allows everything."""

    def is_allowed(self, url: str, user_agent: str) -> bool:  # pragma: no cover - trivial
        return True


class PageCrawler:
    """Walk an org's homepage and a curated set of follow-up paths."""

    def __init__(
        self,
        http: HttpClient,
        *,
        browser: Browser | None = None,
        robots: RobotsChecker | None = None,
        candidate_paths: tuple[str, ...] = DEFAULT_CANDIDATE_PATHS,
        max_pages: int = 6,
        user_agent: str = "OregonNGOResearch/0.1",
    ) -> None:
        self._http = http
        self._browser = browser
        self._robots = robots or _AllowAllRobots()
        self._candidate_paths = candidate_paths
        self._max_pages = max_pages
        self._user_agent = user_agent

    def crawl(self, homepage: str) -> list[FetchedPage]:
        if not homepage:
            return []
        origin = _origin(homepage)
        if not origin:
            return []

        urls = self._build_url_list(origin)
        # Always start with the homepage so we can discover nav links.
        homepage_html = self._fetch(origin)
        pages: list[FetchedPage] = []
        if homepage_html is not None:
            pages.append(homepage_html)
            urls = _merge_urls(urls, self._discover_nav_links(homepage_html))

        seen_urls = {p.url for p in pages}
        for url in urls:
            if url in seen_urls or len(pages) >= self._max_pages:
                continue
            page = self._fetch(url)
            if page is None:
                continue
            seen_urls.add(page.url)
            pages.append(page)
        return pages

    def _fetch(self, url: str) -> FetchedPage | None:
        if not self._robots.is_allowed(url, self._user_agent):
            return None
        try:
            resp = self._http.get(url)
        except Exception:
            return None
        if resp.status_code >= 400 or not resp.text:
            return None
        if _looks_js_rendered(resp.text) and self._browser is not None:
            try:
                rendered = self._browser.render(url)
            except Exception:
                return FetchedPage(url=resp.url or url, html=resp.text, status=resp.status_code)
            return FetchedPage(
                url=resp.url or url,
                html=rendered,
                status=resp.status_code,
                rendered_with_browser=True,
            )
        return FetchedPage(url=resp.url or url, html=resp.text, status=resp.status_code)

    def _build_url_list(self, origin: str) -> list[str]:
        return [urljoin(origin, p) for p in self._candidate_paths]

    def _discover_nav_links(self, page: FetchedPage) -> list[str]:
        soup = BeautifulSoup(page.html, "lxml")
        origin = _origin(page.url)
        urls: list[str] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            text = link.get_text(" ", strip=True)
            if not text or not NAV_TEXT_RE.search(text):
                continue
            absolute = urljoin(page.url, link["href"])
            parsed = urlparse(absolute)
            if not parsed.scheme.startswith("http"):
                continue
            if parsed.netloc != urlparse(origin).netloc:
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            urls.append(absolute)
        return urls


def _origin(url: str) -> str:
    """Return ``scheme://host/`` for ``url`` (note the trailing slash).

    The trailing slash matters: it makes the homepage URL identical to
    ``urljoin(origin, '/')`` so the crawler's seen-set dedupes the homepage
    fetch against the ``/`` candidate path.
    """
    p = urlparse(url)
    if not p.scheme or not p.netloc:
        return ""
    return f"{p.scheme}://{p.netloc}/"


def _looks_js_rendered(html: str) -> bool:
    """Cheap heuristic: very small body or many <script> tags + tiny content."""
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    if len(text) < 200 and "<script" in html.lower():
        return True
    return False


def _merge_urls(base: list[str], extra: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for url in (*base, *extra):
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out
