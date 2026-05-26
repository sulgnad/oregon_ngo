"""Heading-based extraction of mission and values text from HTML.

The extractor performs no I/O \u2014 it operates on HTML strings supplied by the
caller, so unit tests can exercise it directly with fixture pages.
"""

from __future__ import annotations

import json
import re
from typing import Iterable

from bs4 import BeautifulSoup, Tag

from ..models import FetchedPage, MissionResult


MISSION_HEADING_RE = re.compile(r"(?i)^\s*(our\s+)?mission(\s+statement)?\s*$")
# Headings under which orgs publish their values. Covers: "Our Values",
# "Core Values", "Guiding Principles", "What We Stand For", "Our Beliefs",
# "Our Approach", "Our Promise", "Our Pillars", "Vision and Values",
# "What We Believe".
VALUES_HEADING_RE = re.compile(
    r"(?i)^\s*(?:"
    r"(?:our\s+|the\s+)?(?:core\s+|guiding\s+)?(?:values|principles|beliefs|pillars)"
    r"|what\s+we\s+stand\s+for"
    r"|what\s+we\s+believe"
    r"|our\s+commitments?"
    r"|our\s+approach"
    r"|our\s+promise"
    r"|vision\s+and\s+values"
    r"|values\s+and\s+vision"
    r")\s*[:.]?\s*$"
)
MISSION_PHRASE_RE = re.compile(
    r"(?i)(our mission is[^.]+\.|the mission of [^.]+\.)"
)
# Phrases that introduce an inline values listing (often followed by a
# <ul> or a few short sentences).
VALUES_PHRASE_RE = re.compile(
    r"(?i)(?:^|\.\s+)("
    r"we\s+believe\s+(?:in\s+)?[^.]+\."
    r"|we\s+value\s+[^.]+\."
    r"|our\s+values\s+(?:are|include)[^.]+\."
    r"|we\s+are\s+committed\s+to\s+[^.]+\."
    r"|guided\s+by\s+[^.]+\."
    r")"
)


class MissionExtractor:
    """Pull mission and values statements from a list of fetched pages."""

    def extract(self, pages: Iterable[FetchedPage]) -> MissionResult:
        pages = list(pages)
        result = MissionResult()
        for page in pages:
            if result.mission and result.values:
                break
            soup = BeautifulSoup(page.html, "lxml")
            if not result.mission:
                mission = _by_heading(soup, MISSION_HEADING_RE)
                if mission:
                    result.mission = mission
                    result.source_url = page.url
                    result.strategies.append("heading_mission")
                else:
                    phrase = _by_phrase(soup, MISSION_PHRASE_RE)
                    if phrase:
                        result.mission = phrase
                        result.source_url = result.source_url or page.url
                        result.strategies.append("phrase_mission")
                    else:
                        # JSON-LD Organization.description is common on modern
                        # NGO sites (WordPress + Yoast, Squarespace, etc.).
                        jsonld = _by_jsonld_description(soup)
                        if jsonld:
                            result.mission = jsonld
                            result.source_url = result.source_url or page.url
                            result.strategies.append("jsonld_mission")
                        else:
                            meta = _by_og_description(soup)
                            if meta:
                                result.mission = meta
                                result.source_url = result.source_url or page.url
                                result.strategies.append("og_description_mission")
            if not result.values:
                values = _by_heading(soup, VALUES_HEADING_RE)
                if values:
                    result.values = values
                    result.source_url = result.source_url or page.url
                    result.strategies.append("heading_values")
                else:
                    inline = _values_by_phrase(soup)
                    if inline:
                        result.values = inline
                        result.source_url = result.source_url or page.url
                        result.strategies.append("phrase_values")
        return result


def _by_heading(soup: BeautifulSoup, pattern: re.Pattern[str]) -> str | None:
    for level in ("h1", "h2", "h3", "h4", "h5"):
        for heading in soup.find_all(level):
            text = heading.get_text(" ", strip=True)
            if not pattern.match(text):
                continue
            collected = list(_walk_after(heading))
            if not collected:
                continue
            joined = " ".join(t for t in collected if t).strip()
            if len(joined) >= 20:
                return joined
    return None


def _walk_after(heading: Tag) -> Iterable[str]:
    """Yield text from sibling nodes after ``heading`` until the next heading."""
    headings = {"h1", "h2", "h3", "h4", "h5", "h6"}
    for sibling in heading.find_all_next():
        if not isinstance(sibling, Tag):
            continue
        if sibling.name in headings:
            return
        if sibling.name in {"p", "li", "blockquote"}:
            text = sibling.get_text(" ", strip=True)
            if text:
                yield text
        elif sibling.name == "ul":
            for li in sibling.find_all("li"):
                text = li.get_text(" ", strip=True)
                if text:
                    yield text
        # Stop after a reasonable number of paragraphs to avoid greedy capture.


def _by_phrase(soup: BeautifulSoup, pattern: re.Pattern[str]) -> str | None:
    text = soup.get_text(" ", strip=True)
    match = pattern.search(text)
    if not match:
        return None
    return match.group(1).strip()


def _by_jsonld_description(soup: BeautifulSoup) -> str | None:
    """Look for a Schema.org ``Organization`` (or ``NGO``/``LocalBusiness``)
    JSON-LD block on the page and return its ``description`` or ``slogan``.
    Yoast SEO, Squarespace and many WordPress themes populate this block
    automatically with the site's tagline / about copy.
    """
    for script in soup.find_all('script', type='application/ld+json'):
        raw = (script.string or script.get_text() or '').strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            continue
        for node in _walk_jsonld(payload):
            if not isinstance(node, dict):
                continue
            node_type = node.get('@type')
            type_list = [node_type] if isinstance(node_type, str) else (node_type or [])
            if not any(t in {'Organization', 'NGO', 'LocalBusiness', 'NonprofitOrganization',
                              'CharitableOrganization'} for t in type_list):
                continue
            for key in ('description', 'slogan', 'mission'):
                value = node.get(key)
                if isinstance(value, str) and 40 <= len(value) <= 1500:
                    return value.strip()
    return None


def _walk_jsonld(node: object) -> Iterable[object]:
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk_jsonld(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_jsonld(v)


def _by_og_description(soup: BeautifulSoup) -> str | None:
    """Last-resort: pull the OG/meta description as a mission summary.

    Most NGO sites populate ``<meta property="og:description">`` with their
    elevator pitch ("X is a Portland-based nonprofit that..."). Worth
    capturing when neither a heading nor a phrase match fired.
    """
    for selector in (
        ('meta', {'property': 'og:description'}),
        ('meta', {'name': 'description'}),
        ('meta', {'name': 'twitter:description'}),
    ):
        tag = soup.find(*selector)
        if tag is None:
            continue
        content = (tag.get('content') or '').strip()
        if 40 <= len(content) <= 600:
            return content
    return None


def _values_by_phrase(soup: BeautifulSoup) -> str | None:
    """Capture an inline values statement intro'd by phrases like "we believe
    in", "we are committed to", "guided by", "we value".

    Strategy: find the phrase, then look for a sibling ``<ul>`` immediately
    after to grab a list of values; otherwise return the phrase sentence.
    """
    # First pass: scan paragraph nodes so we can grab the following <ul>
    for tag in soup.find_all(['p', 'div']):
        text = tag.get_text(' ', strip=True)
        match = VALUES_PHRASE_RE.search(text)
        if not match:
            continue
        sentence = match.group(1).strip()
        # Look ahead for a list of bullets near this paragraph.
        sibling_ul = tag.find_next_sibling('ul')
        if sibling_ul is not None:
            items = [li.get_text(' ', strip=True) for li in sibling_ul.find_all('li')]
            items = [it for it in items if it]
            if 2 <= len(items) <= 12:
                bullet_text = ' • '.join(items)
                return f"{sentence} {bullet_text}".strip()
        if len(sentence) >= 40:
            return sentence
    # Fallback: any text-based phrase match
    return _by_phrase(soup, VALUES_PHRASE_RE)
