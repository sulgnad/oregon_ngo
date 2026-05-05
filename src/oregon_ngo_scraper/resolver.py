"""Resolve a homepage URL for an organization that has only a name.

Takes an injected :class:`SearchEngine` (DuckDuckGo HTML in production, fake in
tests) and selects the most plausible homepage from the search results,
filtering out social media, aggregator and self-reference noise.
"""

from __future__ import annotations

from urllib.parse import urlparse

import tldextract
from rapidfuzz import fuzz

from .protocols import SearchEngine, SearchResult


# Hosts that are never the org's own homepage even if they appear at the top
# of the result page.
NOISE_HOST_FRAGMENTS = (
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com",
    "yelp.com",
    "guidestar.org",
    "candid.org",
    "charitynavigator.org",
    "propublica.org",
    "ocadsv.org",
    "wikipedia.org",
    "google.com",
)


class HomepageResolver:
    """Pick the best homepage URL for an org name."""

    def __init__(self, search: SearchEngine, *, query_suffix: str = "Oregon nonprofit") -> None:
        self._search = search
        self._suffix = query_suffix

    def resolve(self, name: str, *, city: str | None = None) -> str | None:
        """Return the best-guess homepage URL for ``name``.

        ``city`` is optional context that gets folded into the search query
        (e.g. "\"Bienestar Inc\" Hillsboro Oregon nonprofit"); supplying it
        makes name collisions far less likely.
        """
        if not name:
            return None
        query = f'"{name}" {city} {self._suffix}' if city else f'"{name}" {self._suffix}'
        results = self._search.search(query, max_results=10)
        ranked = sorted(
            (r for r in results if _is_candidate(r)),
            key=lambda r: _score(r, name),
            reverse=True,
        )
        if not ranked:
            return None
        best = ranked[0]
        if _score(best, name) <= 0:
            return None
        return _to_origin(best.url)


def _is_candidate(result: SearchResult) -> bool:
    host = urlparse(result.url).netloc.lower()
    if not host:
        return False
    return not any(noise in host for noise in NOISE_HOST_FRAGMENTS)


def _score(result: SearchResult, name: str) -> int:
    title_score = fuzz.token_set_ratio(name.lower(), result.title.lower())
    snippet_score = fuzz.partial_ratio(name.lower(), (result.snippet or "").lower())
    host = urlparse(result.url).netloc.lower()
    name_tokens = {t for t in name.lower().split() if len(t) > 2}
    host_bonus = 20 if any(tok in host for tok in name_tokens) else 0
    tld = tldextract.extract(result.url).suffix
    tld_bonus = 10 if tld == "org" else 0
    return int(0.7 * title_score + 0.3 * snippet_score) + host_bonus + tld_bonus


def _to_origin(url: str) -> str:
    p = urlparse(url)
    if not p.scheme or not p.netloc:
        return url
    return f"{p.scheme}://{p.netloc}"
