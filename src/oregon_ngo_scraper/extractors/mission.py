"""Heading-based extraction of mission and values text from HTML.

The extractor performs no I/O \u2014 it operates on HTML strings supplied by the
caller, so unit tests can exercise it directly with fixture pages.
"""

from __future__ import annotations

import re
from typing import Iterable

from bs4 import BeautifulSoup, Tag

from ..models import FetchedPage, MissionResult


MISSION_HEADING_RE = re.compile(r"(?i)^\s*(our\s+)?mission(\s+statement)?\s*$")
# Values come under many headings: "Our Values", "Core Values", "Our Core
# Values", "What We Stand For", "Guiding Principles", "Our Beliefs".
VALUES_HEADING_RE = re.compile(
    r"(?i)^\s*(?:"
    r"(?:our\s+|the\s+)?(?:core\s+|guiding\s+)?(?:values|principles|beliefs)"
    r"|what\s+we\s+stand\s+for"
    r"|our\s+commitments?"
    r")\s*[:.]?\s*$"
)
MISSION_PHRASE_RE = re.compile(
    r"(?i)(our mission is[^.]+\.|the mission of [^.]+\.)"
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
                    phrase = _by_phrase(soup)
                    if phrase:
                        result.mission = phrase
                        result.source_url = result.source_url or page.url
                        result.strategies.append("phrase_mission")
            if not result.values:
                values = _by_heading(soup, VALUES_HEADING_RE)
                if values:
                    result.values = values
                    result.source_url = result.source_url or page.url
                    result.strategies.append("heading_values")
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


def _by_phrase(soup: BeautifulSoup) -> str | None:
    text = soup.get_text(" ", strip=True)
    match = MISSION_PHRASE_RE.search(text)
    if not match:
        return None
    return match.group(1).strip()
