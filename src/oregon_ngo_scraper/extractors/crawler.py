"""Crawl an organization's website for pages likely to contain mission text.

The crawler is built around three discovery strategies, applied in priority
order for each org:

1. **Homepage scan** — fetch ``/``, find its *final* URL after redirects, and
   pull the page's ``<a>`` links matching mission-ish text. This single page
   produced ~45% of all successful mission extractions in the current data,
   so it's checked first.
2. **Sitemap discovery** — fetch ``/sitemap.xml`` (and ``/sitemap_index.xml``)
   and scan every URL inside for path tokens like ``about``, ``mission``,
   ``values``, ``story``, ``who``, ``approach``, ``principles``. This catches
   idiosyncratic paths like ``/about-rose``, ``/whoweare`` or
   ``/about-us/our-mission-and-values/`` that the static path list won't.
3. **Static candidate paths** — a hand-curated list of high-probability URLs
   (``/about``, ``/mission``, etc.) as the final fallback.

Netloc comparisons use the apex host (``apex.org`` == ``www.apex.org``) so a
homepage that redirects between www and non-www doesn't make us drop in-domain
nav links.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..discovery.base import apex_host
from ..models import FetchedPage
from ..protocols import Browser, HttpClient, RobotsChecker

logger = logging.getLogger(__name__)


# Path candidates checked in priority order. Per the project README in the
# starter spreadsheet, prioritise: /about, /about-us, /mission, /our-mission,
# /who-we-are, /what-we-do.
DEFAULT_CANDIDATE_PATHS: tuple[str, ...] = (
    "/",
    "/about",
    "/about-us",
    "/about/mission",
    "/about/values",
    "/about/our-values",
    "/our-mission",
    "/mission",
    "/mission-vision-values",
    "/mission-values",
    "/mission-and-values",
    "/who-we-are",
    "/what-we-do",
    "/what-we-believe",
    "/values",
    "/our-values",
    "/core-values",
    "/our-approach",
    "/principles",
    "/our-promise",
    "/our-story",
)

NAV_TEXT_RE = re.compile(r"(?i)mission|about|who we are|what we do|values|our story")

# Path-token regex used to score sitemap URLs. Words that strongly suggest a
# page contains mission/values content. "impact"/"overview"/"organization"
# are intentionally excluded — they appear in blog/report URLs too often to
# be useful signal.
SITEMAP_KEYWORD_RE = re.compile(
    r"(?i)(?:^|/|-|_)(?:"
    r"about|mission|values|principles|beliefs?|approach|promise|pillars?"
    r"|story|history|who-?we-?are|who_we_are|whoweare|what-?we-?do"
    r"|what-?we-?believe|charter"
    r")(?:$|/|-|_|\.)"
)

# Hosts we never want to count as part of an org's own site.
_AGGREGATOR_HOSTS = (
    "propublica.org",
    "guidestar.org",
    "candid.org",
    "charitynavigator.org",
    "plaincharity.com",
    "searchcharities.org",
    "nonprofitscan.com",
    "nonprofitlocator.org",
    "nonprofitlist.org",
    "intellispect.co",
    "f990.org",
    "taxexemptworld.com",
    "healthshareoregon.org",
    "idealist.org",
)


def _is_aggregator(host: str) -> bool:
    h = (host or "").lower()
    return any(noise in h for noise in _AGGREGATOR_HOSTS)


def _same_apex(a: str, b: str) -> bool:
    """True when two URLs/hosts share the same apex domain."""
    return bool(apex_host(a)) and apex_host(a) == apex_host(b)


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
        if _is_aggregator(urlparse(homepage).netloc):
            logger.info("refusing to crawl aggregator host: %s", homepage)
            return []
        seed_origin = _origin(homepage)
        if not seed_origin:
            return []

        pages: list[FetchedPage] = []
        # 1. Fetch the homepage; use the *final* URL as canonical origin
        # so nav links on www-redirecting sites still pass same-apex checks.
        homepage_page = self._fetch(seed_origin)
        if homepage_page is None:
            # Couldn't reach apex; try the www. variant.
            www_url = _add_www(seed_origin)
            if www_url and www_url != seed_origin:
                homepage_page = self._fetch(www_url)
        if homepage_page is None:
            return []
        pages.append(homepage_page)
        canonical_origin = _origin(homepage_page.url) or seed_origin

        # 2. Discover candidate URLs in priority order:
        #    - links on the homepage matching mission/about/values text
        #    - sitemap.xml entries matching keyword tokens in the path
        #    - static curated candidate paths
        nav_urls = self._discover_nav_links(homepage_page, canonical_origin)
        sitemap_urls = self._discover_sitemap_urls(canonical_origin)
        static_urls = self._build_url_list(canonical_origin)
        urls = _merge_urls(nav_urls, sitemap_urls, static_urls)

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

    def _discover_nav_links(self, page: FetchedPage, origin: str) -> list[str]:
        """Find ``<a>`` links on ``page`` whose text matches mission-ish words.

        Same-origin is judged by apex host, so ``www.acme.org`` links from a
        page served by ``acme.org`` (or vice versa) still count.
        """
        soup = BeautifulSoup(page.html, "lxml")
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
            if not _same_apex(absolute, origin):
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            urls.append(absolute)
        return urls

    def _discover_sitemap_urls(self, origin: str) -> list[str]:
        """Pull URLs from ``/sitemap.xml`` (and any referenced sub-sitemaps)
        that look like they contain mission/about/values content.

        Returns at most ``max_pages`` URLs, ranked so explicit mission/values
        paths come before generic about/who/story paths.
        """
        candidates: list[str] = []
        for entry in ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml"):
            try:
                resp = self._http.get(urljoin(origin, entry))
            except Exception:
                continue
            if resp.status_code >= 400 or not resp.text:
                continue
            for url in _iter_sitemap_urls(resp.text):
                if not _same_apex(url, origin):
                    continue
                if SITEMAP_KEYWORD_RE.search(urlparse(url).path):
                    candidates.append(url)
            if candidates:
                break
        # Rank: prefer URLs whose path contains the strongest keywords first.
        def _rank(url: str) -> int:
            p = urlparse(url).path.lower()
            for i, kw in enumerate((
                "mission-and-values",
                "mission-values",
                "our-mission",
                "mission",
                "values",
                "principles",
                "approach",
                "about",
                "who",
                "story",
            )):
                if kw in p:
                    return i
            return 99
        candidates.sort(key=_rank)
        # De-dup while preserving rank.
        out: list[str] = []
        seen: set[str] = set()
        for u in candidates:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out[: self._max_pages]


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


def _add_www(url: str) -> str:
    """Return ``url`` with a ``www.`` prefix on the host (or unchanged)."""
    p = urlparse(url)
    if not p.netloc or p.netloc.startswith("www."):
        return url
    return f"{p.scheme}://www.{p.netloc}{p.path or '/'}"


_SITEMAP_LOC_RE = re.compile(r"<loc>([^<]+)</loc>", re.IGNORECASE)


def _iter_sitemap_urls(xml: str) -> list[str]:
    """Pull every ``<loc>...</loc>`` URL out of a sitemap XML string.

    Sitemap-index files (which list other sitemaps) are handled by the
    caller: every <loc> from any sitemap is returned, and the caller filters
    those that look like content URLs (vs sub-sitemap URLs ending in .xml).
    """
    return [u.strip() for u in _SITEMAP_LOC_RE.findall(xml) if not u.strip().endswith(".xml")]


def _merge_urls(*lists: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for lst in lists:
        for url in lst:
            if url not in seen:
                seen.add(url)
                out.append(url)
    return out
