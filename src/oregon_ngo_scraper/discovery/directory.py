"""Discovery for county "community resource" directory pages.

``LinkListDiscovery`` handles the easy case: a page whose members are anchor
tags pointing at their own websites. The county directories approved for the
Jefferson/Tillamook collection mostly aren't like that. They list an
organization as plain text under a category heading, with the address and
phone number run together in the same block::

    Housing / Shelter
      Madras Gospel Misson164 SE D StMadras, OR 97741 541-475-2064
      Neighborimpact Madras 374 SW 5th St., Suite BMadras, OR 97741 541-548-2380

and others use tables with an "Organization and Program Name" column. This
module handles both shapes with one walker: it goes through the document in
order, tracks the most recent heading as the current category, and turns the
list items, table rows and paragraphs underneath it into organizations.

The category heading is the primary topic signal (via :mod:`classify`), with
the entry's own text as a fallback, so a "Domestic Violence" section tags its
members even when their names say nothing about DSV.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .. import classify, geo
from ..models import Organization, OrgType, Topic
from ..protocols import HttpClient
from .base import apex_host

logger = logging.getLogger(__name__)


# Only real headings by default. Tags like <strong> are tempting (some pages
# bold their category labels) but they also wrap org names *inside* entries,
# and since headings are read before the consumed-node check, an org name in
# <strong> would silently become the category for everything after it. Pages
# that genuinely need it can opt in via ``DirectoryConfig.heading_tags``.
DEFAULT_HEADING_TAGS: tuple[str, ...] = ("h1", "h2", "h3", "h4", "h5", "h6")
DEFAULT_ENTRY_TAGS: tuple[str, ...] = ("li", "tr", "p")

# Hosts that are never an organization's own homepage.
_NOISE_HOST_FRAGMENTS: tuple[str, ...] = (
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com",
    "google.com",
    "goo.gl",
    "maps.app.goo.gl",
    "civicplus.com",
    "wikipedia.org",
    "211info.org",
)

# Link/label text that is navigation furniture rather than an org name.
_STOPWORD_NAMES: frozenset[str] = frozenset(
    {
        "home",
        "about",
        "about us",
        "contact",
        "contact us",
        "menu",
        "search",
        "donate",
        "volunteer",
        "more",
        "read more",
        "learn more",
        "click here",
        "website",
        "email",
        "phone",
        "back to top",
        "skip to main content",
        "resources",
        "other resources",
        "links",
        "n/a",
        "multiple",
        "central",
        "north",
        "south",
    }
)

_WS_RE = re.compile(r"\s+")
_PHONE_RE = re.compile(r"\(?\b\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}\b")
# "164 SE D St", "1238 SW Veterans Way", "PO Box 36"
_DIRECTIONAL_ADDRESS_RE = re.compile(r"\d{1,6}\s*[NSEW]{1,2}\b", re.IGNORECASE)
_PO_BOX_RE = re.compile(r"\bP\.?\s?O\.?\s*Box\b", re.IGNORECASE)
_STREET_RE = re.compile(
    r"\b\d{1,6}\s+[A-Za-z][\w'.\-]*\s+"
    r"(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Blvd|Boulevard|Way|Ln|Lane|"
    r"Ct|Court|Hwy|Highway|Pkwy|Pl|Place|Ter|Terrace|Cir|Circle)\b\.?",
    re.IGNORECASE,
)
_TRAILING_JUNK_RE = re.compile(r"[\s,;:\-–—|/\\.]+$")
_LEADING_JUNK_RE = re.compile(r"^[\s,;:\-–—|•*/\\]+")
# Tribal domains use the "-nsn.gov" (Native Sovereign Nation) convention.
_TRIBAL_HOST_RE = re.compile(r"-nsn\.gov$", re.IGNORECASE)
_TRIBAL_NAME_RE = re.compile(
    r"(?<!\w)(?:confederated tribes|tribal council|tribal|\btribe\b)(?!\w)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DirectoryConfig:
    """Declarative description of one resource-directory page.

    Attributes:
        name: Source name recorded in ``discovered_via``.
        url: Page to fetch.
        county: County every organization on this page belongs to.
        default_org_type: Type assigned when host/name heuristics say nothing.
        container_selector: CSS selector narrowing the region to walk.
        heading_tags: Tags treated as category headings.
        entry_tags: Tags treated as candidate organization entries.
        extra_topics: Topics applied to every entry, for single-subject pages
            (e.g. a "Looking for Housing?" page) where headings carry no signal.
        require_topic: Drop entries that match none of the project's topics.
            Turn this off only for pages that are entirely on-topic.
        skip_headings: Substrings identifying sections to ignore wholesale.
        org_type_overrides: ``(needle, OrgType)`` pairs matched against the
            org's name and website. Needed because domain suffixes only get
            you so far — Jefferson County's official site is ``jeffco.net``,
            not a ``.gov`` — so known entities are declared explicitly.
    """

    name: str
    url: str
    county: str
    default_org_type: OrgType = OrgType.NONPROFIT
    container_selector: str | None = None
    heading_tags: tuple[str, ...] = DEFAULT_HEADING_TAGS
    entry_tags: tuple[str, ...] = DEFAULT_ENTRY_TAGS
    extra_topics: frozenset[Topic] = field(default_factory=frozenset)
    require_topic: bool = True
    skip_headings: tuple[str, ...] = ()
    org_type_overrides: tuple[tuple[str, OrgType], ...] = ()


class ResourceDirectoryDiscovery:
    """Yield organizations from a category-structured resource directory."""

    def __init__(self, http: HttpClient, config: DirectoryConfig) -> None:
        self._http = http
        self._config = config
        self.name = config.name

    def discover(self) -> Iterable[Organization]:
        try:
            resp = self._http.get(self._config.url)
        except Exception:  # pragma: no cover - defensive
            logger.exception("directory fetch failed: %s", self._config.url)
            return []
        if resp.status_code >= 400 or not resp.text:
            logger.warning(
                "directory %s returned %s", self._config.url, resp.status_code
            )
            return []
        return list(self.parse(resp.text))

    def parse(self, html: str) -> Iterable[Organization]:
        """Parse directory HTML into organizations (pure; no I/O)."""
        cfg = self._config
        soup = BeautifulSoup(html, "lxml")
        container = None
        if cfg.container_selector:
            container = soup.select_one(cfg.container_selector)
        scope = container or soup

        wanted_tags = list(dict.fromkeys(cfg.heading_tags + cfg.entry_tags))
        heading_tags = set(cfg.heading_tags)
        page_host = apex_host(cfg.url)

        current_heading: str | None = None
        consumed: set[int] = set()
        seen_names: set[str] = set()

        for node in scope.find_all(wanted_tags):
            text = node.get_text(" ", strip=True)
            if not text:
                continue

            if node.name in heading_tags:
                # Long "headings" are almost always emphasised body copy that
                # a source opted into via heading_tags; ignore them so they
                # don't clobber the real category.
                if len(text) <= 80:
                    current_heading = text
                continue

            if self._skipped(current_heading):
                continue
            if any(id(parent) in consumed for parent in node.parents):
                continue

            org = self._entry_to_org(node, current_heading, page_host)
            if org is None:
                continue
            key = org.name.strip().lower()
            if key in seen_names:
                consumed.add(id(node))
                continue
            seen_names.add(key)
            consumed.add(id(node))
            yield org

    # --- internals ---------------------------------------------------------

    def _skipped(self, heading: str | None) -> bool:
        if not heading or not self._config.skip_headings:
            return False
        lowered = heading.lower()
        return any(skip.lower() in lowered for skip in self._config.skip_headings)

    def _entry_to_org(
        self, node, heading: str | None, page_host: str
    ) -> Organization | None:
        cfg = self._config
        full_text = node.get_text(" ", strip=True)
        name_source = self._name_source(node)
        if name_source is None:
            return None
        name = clean_org_name(name_source)
        if not is_plausible_org_name(name):
            return None

        website = self._pick_website(node, page_host)
        topics = classify.topics_for_text(heading, name, full_text) | set(
            cfg.extra_topics
        )
        if cfg.require_topic and not topics:
            return None

        return Organization(
            name=name,
            website=website,
            city=geo.find_city(full_text, cfg.county),
            county=cfg.county,
            state="OR",
            topics=topics,
            org_type=resolve_org_type(
                name,
                website,
                default=cfg.default_org_type,
                overrides=cfg.org_type_overrides,
            ),
            notes=(
                f'Listed under "{heading}" on {cfg.name}.' if heading else None
            ),
            discovered_via=[cfg.name],
            source_urls=[cfg.url],
        )

    def _name_source(self, node) -> str | None:
        """Return the text most likely to contain the organization name."""
        if node.name == "tr":
            cells = node.find_all(["td", "th"])
            if not cells:
                return None
            # A row of only <th> is a header row.
            if all(cell.name == "th" for cell in cells):
                return None
            return cells[0].get_text(" ", strip=True)
        # Prefer a link's own text: it's the name without the address run-on.
        link = self._first_content_link(node)
        if link is not None:
            link_text = link.get_text(" ", strip=True)
            if is_plausible_org_name(clean_org_name(link_text)):
                return link_text
        return node.get_text(" ", strip=True)

    def _first_content_link(self, node):
        for anchor in node.find_all("a", href=True):
            if _is_content_href(anchor["href"]):
                return anchor
        return None

    def _pick_website(self, node, page_host: str) -> str | None:
        for anchor in node.find_all("a", href=True):
            href = anchor["href"].strip()
            if not _is_content_href(href):
                continue
            absolute = urljoin(self._config.url, href)
            parsed = urlparse(absolute)
            if not parsed.scheme.startswith("http"):
                continue
            host = apex_host(absolute)
            if not host or host == page_host:
                continue
            if any(noise in host for noise in _NOISE_HOST_FRAGMENTS):
                continue
            return f"{parsed.scheme}://{parsed.netloc}"
        return None


# --- helpers ----------------------------------------------------------------


def _is_content_href(href: str) -> bool:
    lowered = href.strip().lower()
    if not lowered or lowered.startswith(("#", "mailto:", "tel:", "javascript:")):
        return False
    return True


def clean_org_name(text: str) -> str:
    """Trim an entry's text down to just the organization name.

    Directory entries glue the name to an address and phone number, sometimes
    without a separator (``"Madras Gospel Misson164 SE D St"``). We cut at the
    earliest address- or phone-looking token.
    """
    if not text:
        return ""
    cleaned = _WS_RE.sub(" ", text).strip()
    cut = len(cleaned)
    for pattern in (_PHONE_RE, _DIRECTIONAL_ADDRESS_RE, _PO_BOX_RE, _STREET_RE):
        match = pattern.search(cleaned)
        if match and match.start() < cut:
            cut = match.start()
    cleaned = cleaned[:cut]
    cleaned = _LEADING_JUNK_RE.sub("", cleaned)
    cleaned = _TRAILING_JUNK_RE.sub("", cleaned)
    return _WS_RE.sub(" ", cleaned).strip()


def is_plausible_org_name(name: str) -> bool:
    """Reject nav furniture, fragments and address leftovers."""
    if not name:
        return False
    if len(name) < 3 or len(name) > 120:
        return False
    if name.lower() in _STOPWORD_NAMES:
        return False
    if name.lower().startswith(("http://", "https://", "www.")):
        return False
    # Needs real words, not just digits/punctuation.
    letters = sum(1 for ch in name if ch.isalpha())
    return letters >= 3


def resolve_org_type(
    name: str,
    website: str | None,
    *,
    default: OrgType = OrgType.NONPROFIT,
    overrides: tuple[tuple[str, OrgType], ...] = (),
) -> OrgType:
    """Apply per-source overrides, then fall back to :func:`infer_org_type`."""
    haystack = f"{name or ''} {website or ''}".lower()
    for needle, org_type in overrides:
        if needle and needle.lower() in haystack:
            return org_type
    return infer_org_type(name, website, default)


def infer_org_type(
    name: str, website: str | None, default: OrgType = OrgType.NONPROFIT
) -> OrgType:
    """Classify an entity as tribal / government / nonprofit.

    Host-based rules come first because they're unambiguous; the name-based
    tribal check is a fallback for entries with no website. Deliberately does
    **not** treat the word "county" in a name as government evidence \u2014
    "Tillamook County Habitat for Humanity" is a 501(c)(3).
    """
    host = apex_host(website) if website else ""
    if host:
        if _TRIBAL_HOST_RE.search(host):
            return OrgType.TRIBAL_GOVERNMENT
        if host.endswith(".gov") or host.endswith(".state.or.us"):
            return OrgType.GOVERNMENT
    if _TRIBAL_NAME_RE.search(name or ""):
        return OrgType.TRIBAL_GOVERNMENT
    return default
