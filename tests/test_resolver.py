from __future__ import annotations

from oregon_ngo_scraper.protocols import SearchResult
from oregon_ngo_scraper.resolver import HomepageResolver


def test_picks_org_homepage_over_social_or_aggregator(fake_search) -> None:
    fake_search.by_query["Bradley Angle"] = [
        SearchResult(
            title="Bradley Angle - Facebook",
            url="https://www.facebook.com/bradleyangle",
            snippet="",
        ),
        SearchResult(
            title="Bradley Angle - ProPublica",
            url="https://projects.propublica.org/nonprofits/organizations/930388110",
            snippet="",
        ),
        SearchResult(
            title="Bradley Angle",
            url="https://bradleyangle.org",
            snippet="Anti-violence organization in Portland, Oregon.",
        ),
    ]
    resolver = HomepageResolver(fake_search)

    url = resolver.resolve("Bradley Angle")
    assert url == "https://bradleyangle.org"


def test_returns_none_when_no_candidates(fake_search) -> None:
    fake_search.by_query["Empty"] = [
        SearchResult(title="Some Page", url="https://wikipedia.org/x"),
    ]
    resolver = HomepageResolver(fake_search)
    assert resolver.resolve("Empty") is None


def test_returns_none_for_empty_name(fake_search) -> None:
    resolver = HomepageResolver(fake_search)
    assert resolver.resolve("") is None
    assert fake_search.calls == []
