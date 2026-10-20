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

import hashlib
import logging
import re
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from ..aggregators import is_noise_host
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

# Pages that carry a street address / phone. Only crawled when the caller asks
# for contact details (``include_contact_pages``); the statewide mission run
# has no use for them and shouldn't pay the extra requests.
CONTACT_CANDIDATE_PATHS: tuple[str, ...] = (
    "/contact",
    "/contact-us",
    "/contactus",
    "/locations",
    "/location",
    "/find-us",
    "/visit",
    "/hours-and-location",
)

CONTACT_NAV_TEXT_RE = re.compile(r"(?i)contact|location|find us|visit us|directions")

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

def _is_aggregator(host: str) -> bool:
    """True for directory/profile hosts that are not the org's own site.

    Shared with the resolver via :mod:`..aggregators` so a host only has to
    be blocked once.
    """
    return is_noise_host(host)


def _same_apex(a: str, b: str) -> bool:
    """True when two URLs/hosts share the same apex domain."""
    return bool(apex_host(a)) and apex_host(a) == apex_host(b)


@dataclass(frozen=True)
class _PathScope:
    """The part of a site that belongs to one pinned page.

    A department page on a shared domain (``county.gov/health/health.html``)
    is not a homepage: the site root and the sibling departments describe the
    whole jurisdiction. Scoping keeps the crawl inside the section the page
    lives in while still letting it follow that section's own navigation.

    The scope is the pinned page itself plus its *directory subtree*:

    * a path ending in a file (``/health/health.html``) scopes to its parent
      directory (``/health/``);
    * an extensionless or trailing-slash path (``/publichealth``,
      ``/clinics/baker-city/``) is treated as a section and scopes to itself
      and everything beneath it.

    A page at the very top of a site (``/clinic.html``) has no directory of
    its own, so its scope is that single page rather than the whole site.
    """

    apex: str
    exact: str  # the pinned page's own path, no trailing slash
    prefix: str | None  # directory subtree with trailing slash; None = page only
    base: str  # absolute URL of the directory, used to resolve relative paths

    @classmethod
    def from_url(cls, url: str) -> "_PathScope":
        parsed = urlparse(url)
        exact = (parsed.path or "/").rstrip("/") or "/"
        last_segment = exact.rsplit("/", 1)[-1]
        directory = exact.rsplit("/", 1)[0] if "." in last_segment else exact
        directory = directory.rstrip("/")
        prefix = f"{directory}/" if directory else None
        base = f"{parsed.scheme}://{parsed.netloc}{directory}/"
        return cls(apex_host(url), exact, prefix, base)

    def contains(self, url: str) -> bool:
        if not _same_apex(url, self.apex):
            return False
        path = urlparse(url).path or "/"
        if (path.rstrip("/") or "/") == self.exact:
            return True
        return self.prefix is not None and path.startswith(self.prefix)


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
        include_contact_pages: bool = False,
        contact_page_budget: int = 3,
    ) -> None:
        self._http = http
        self._browser = browser
        self._robots = robots or _AllowAllRobots()
        self._candidate_paths = candidate_paths
        self._max_pages = max_pages
        self._user_agent = user_agent
        self._include_contact_pages = include_contact_pages
        # Contact pages get their own allowance on top of ``max_pages`` so
        # they are strictly additive: enabling them can never displace a
        # mission page that the statewide run would have fetched.
        self._contact_page_budget = contact_page_budget if include_contact_pages else 0

    def crawl(
        self, homepage: str, *, scope_to_path: bool = False
    ) -> list[FetchedPage]:
        """Crawl ``homepage`` for mission (and optionally contact) pages.

        By default the argument is reduced to its site origin and the whole
        site is walked, which is right for an organization's own domain.
        With ``scope_to_path`` the URL is treated as a pinned page and the
        crawl stays inside that page's section; see :class:`_PathScope`.
        """
        if not homepage:
            return []
        if _is_aggregator(urlparse(homepage).netloc):
            logger.info("refusing to crawl aggregator host: %s", homepage)
            return []
        if scope_to_path:
            return self._crawl_scoped(homepage)
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

        if self._include_contact_pages:
            pages.extend(
                self._crawl_contact_pages(
                    homepage_page, canonical_origin, seen_urls
                )
            )
        return pages

    def _crawl_scoped(self, url: str) -> list[FetchedPage]:
        """Crawl only the section of a site that a pinned page belongs to.

        The pinned page is fetched first, so its own text is always read.
        Mission-ish pages are then found through that page's navigation and
        the sitemap, but only when they sit inside the pinned page's scope.
        The static guess list (``/about``, ``/mission``, ...) is skipped:
        resolved against a department directory those guesses almost never
        exist and would only burn requests.
        """
        first = self._fetch(url)
        if first is None:
            return []
        # A same-site redirect (``/health`` -> ``/health/index.html``) moves
        # the scope with it. A redirect to another site is ignored: the
        # pinned URL is what we were asked to read.
        final = first.url or url
        scope = _PathScope.from_url(final if _same_apex(final, url) else url)
        origin = _origin(final) or _origin(url)

        pages: list[FetchedPage] = [first]
        seen_urls = {first.url}
        seen_text = {_fingerprint(first)}
        nav_urls = self._discover_nav_links(first, origin, scope=scope)
        sitemap_urls = self._discover_sitemap_urls(origin, scope=scope)
        for candidate in _merge_urls(nav_urls, sitemap_urls):
            if candidate in seen_urls or len(pages) >= self._max_pages:
                continue
            page = self._fetch(candidate)
            if page is None:
                continue
            seen_urls.add(page.url)
            if _is_repeat(page, seen_text):
                continue
            pages.append(page)

        if self._include_contact_pages:
            pages.extend(
                self._crawl_contact_pages(
                    first, origin, seen_urls, scope=scope, seen_text=seen_text
                )
            )
        return pages

    def _crawl_contact_pages(
        self,
        homepage_page: FetchedPage,
        origin: str,
        seen_urls: set[str],
        *,
        scope: _PathScope | None = None,
        seen_text: set[str] | None = None,
    ) -> list[FetchedPage]:
        """Fetch up to ``contact_page_budget`` contact-ish pages.

        Nav links matching contact wording are tried before the static path
        list, since a site that labels the page ``/get-in-touch`` will only
        ever be reachable through its own navigation.

        With a ``scope`` both sources are confined to it: a department's
        ``Contact Us`` link is followed, but the county-wide ``/contact`` is
        not, since that page lists some other office.

        Pages whose text matches one already collected are discarded without
        spending budget. Many CMSes answer an unknown path under a section
        with a 200 and the section's own page (a soft 404), so guessed paths
        like ``/contact-us`` would otherwise return copies of the page we
        already have and crowd out a real contact page.
        """
        if seen_text is None:
            seen_text = set()
        nav_urls = self._discover_nav_links(
            homepage_page, origin, text_pattern=CONTACT_NAV_TEXT_RE, scope=scope
        )
        if scope is None:
            static_urls = [urljoin(origin, p) for p in CONTACT_CANDIDATE_PATHS]
        elif scope.prefix is not None:
            static_urls = [
                urljoin(scope.base, p.lstrip("/")) for p in CONTACT_CANDIDATE_PATHS
            ]
        else:
            static_urls = []
        found: list[FetchedPage] = []
        for url in _merge_urls(nav_urls, static_urls):
            if len(found) >= self._contact_page_budget:
                break
            if url in seen_urls:
                continue
            page = self._fetch(url)
            if page is None:
                continue
            seen_urls.add(page.url)
            if _is_repeat(page, seen_text):
                continue
            found.append(page)
        return found

    def _fetch(self, url: str) -> FetchedPage | None:
        # A fragment names a spot on a page the server never sees, so
        # ``/page#tab-1`` and ``/page#tab-2`` are the same document.
        url = urldefrag(url)[0]
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

    def _discover_nav_links(
        self,
        page: FetchedPage,
        origin: str,
        *,
        text_pattern: re.Pattern[str] = NAV_TEXT_RE,
        scope: _PathScope | None = None,
    ) -> list[str]:
        """Find ``<a>`` links on ``page`` whose text matches ``text_pattern``.

        Same-origin is judged by apex host, so ``www.acme.org`` links from a
        page served by ``acme.org`` (or vice versa) still count. When a
        ``scope`` is given, links outside it are dropped.
        """
        soup = BeautifulSoup(page.html, "lxml")
        urls: list[str] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            text = link.get_text(" ", strip=True)
            if not text or not text_pattern.search(text):
                continue
            absolute = urldefrag(urljoin(page.url, link["href"]))[0]
            parsed = urlparse(absolute)
            if not parsed.scheme.startswith("http"):
                continue
            if not _same_apex(absolute, origin):
                continue
            if scope is not None and not scope.contains(absolute):
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            urls.append(absolute)
        return urls

    def _discover_sitemap_urls(
        self, origin: str, *, scope: _PathScope | None = None
    ) -> list[str]:
        """Pull URLs from ``/sitemap.xml`` (and any referenced sub-sitemaps)
        that look like they contain mission/about/values content.

        Returns at most ``max_pages`` URLs, ranked so explicit mission/values
        paths come before generic about/who/story paths. A ``scope`` is
        applied *before* the cut-off, so out-of-scope URLs cannot crowd
        in-scope ones out of the budget.
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
                if scope is not None and not scope.contains(url):
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


#: Pages with less text than this are never treated as duplicates of one
#: another: two near-empty shells say nothing about each other.
_MIN_FINGERPRINT_CHARS = 80


def _fingerprint(page: FetchedPage) -> str:
    """Hash of a page's visible text, for spotting soft-404 copies."""
    text = BeautifulSoup(page.html, "lxml").get_text(" ", strip=True)
    text = " ".join(text.split()).lower()
    if len(text) < _MIN_FINGERPRINT_CHARS:
        # Unique per page so short pages never collide.
        return f"short:{page.url}"
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _is_repeat(page: FetchedPage, seen_text: set[str]) -> bool:
    """True if ``page`` repeats text already collected; records it otherwise."""
    fingerprint = _fingerprint(page)
    if fingerprint in seen_text:
        return True
    seen_text.add(fingerprint)
    return False


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
