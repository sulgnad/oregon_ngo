from __future__ import annotations

import json

from oregon_ngo_scraper.enrichers.propublica_website import (
    DETAIL_ENDPOINT_TEMPLATE,
    ProPublicaDetailFetcher,
    ProPublicaWebsiteEnricher,
    _extract_url_from_payload,
    _looks_like_homepage,
)
from oregon_ngo_scraper.models import Organization, Topic
from oregon_ngo_scraper.protocols import HttpResponse, SearchResult
from oregon_ngo_scraper.resolver import HomepageResolver


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_looks_like_homepage_filters_aggregators_and_socials() -> None:
    assert _looks_like_homepage("https://bradleyangle.org") is True
    assert _looks_like_homepage("www.bradleyangle.org") is True
    assert _looks_like_homepage("bradleyangle.org") is True
    assert _looks_like_homepage("https://facebook.com/bradleyangle") is False
    assert _looks_like_homepage("https://propublica.org/x") is False
    assert _looks_like_homepage("") is False
    assert _looks_like_homepage("not a url") is False


def test_extract_url_prefers_known_keys() -> None:
    payload = {
        "name": "X",
        "website": "https://example.org",
        "data_source": "ProPublica https://projects.propublica.org/...",
    }
    assert _extract_url_from_payload(payload) == "https://example.org"


def test_extract_url_falls_back_to_walk_when_no_known_keys() -> None:
    payload = {
        "summary": "Visit us at https://example.org for more info",
        "data_source": "https://propublica.org/x",  # noise, skipped
    }
    assert _extract_url_from_payload(payload) == "https://example.org"


def test_extract_url_returns_none_when_only_noise() -> None:
    payload = {"data_source": "https://propublica.org/x"}
    assert _extract_url_from_payload(payload) is None


# ---------------------------------------------------------------------------
# Detail fetcher
# ---------------------------------------------------------------------------


def test_detail_fetcher_returns_parsed_payload(fake_http) -> None:
    ein = "930860753"
    url = DETAIL_ENDPOINT_TEMPLATE.format(ein=ein)
    fake_http.responses[url] = HttpResponse(
        status_code=200,
        text=json.dumps({"organization": {"ein": int(ein), "city": "Hillsboro"}}),
        url=url,
    )
    fetcher = ProPublicaDetailFetcher(fake_http)
    payload = fetcher.fetch(ein)
    assert payload is not None
    assert payload["organization"]["city"] == "Hillsboro"


def test_detail_fetcher_returns_none_on_404(fake_http) -> None:
    ein = "999999999"
    url = DETAIL_ENDPOINT_TEMPLATE.format(ein=ein)
    fake_http.responses[url] = HttpResponse(status_code=404, text="", url=url)
    fetcher = ProPublicaDetailFetcher(fake_http)
    assert fetcher.fetch(ein) is None


def test_detail_fetcher_returns_none_on_invalid_json(fake_http) -> None:
    ein = "1"
    url = DETAIL_ENDPOINT_TEMPLATE.format(ein=ein)
    fake_http.responses[url] = HttpResponse(status_code=200, text="not json", url=url)
    fetcher = ProPublicaDetailFetcher(fake_http)
    assert fetcher.fetch(ein) is None


# ---------------------------------------------------------------------------
# Enricher
# ---------------------------------------------------------------------------


class _StubFetcher:
    def __init__(self, payloads: dict[str, dict | None]) -> None:
        self.payloads = payloads
        self.calls: list[str] = []

    def fetch(self, ein: str) -> dict | None:
        self.calls.append(ein)
        return self.payloads.get(ein)


def test_enricher_skips_orgs_without_an_ein() -> None:
    fetcher = _StubFetcher({})
    enricher = ProPublicaWebsiteEnricher(fetcher, resolver=None)

    enricher.enrich([Organization(name="No EIN")])
    assert fetcher.calls == []  # nothing to look up


def test_enricher_still_fetches_detail_for_orgs_that_have_a_website() -> None:
    """The IRS address is worth fetching even when the URL is already known.

    Only the *website lookup* is skipped for these orgs.
    """
    fetcher = _StubFetcher({
        "123": {
            "organization": {
                "address": "164 SE D St",
                "city": "Madras",
                "state": "OR",
                "zipcode": "97741",
                "website": "https://should-not-be-used.org",
            }
        },
    })
    enricher = ProPublicaWebsiteEnricher(fetcher, resolver=None)

    org = Organization(name="Already has site", ein="123", website="https://x.org")
    enricher.enrich([org])

    assert fetcher.calls == ["123"]
    assert org.address == "164 SE D St, Madras, OR 97741"
    assert org.website == "https://x.org"  # existing URL is not overwritten


def test_enricher_formats_the_irs_address() -> None:
    fetcher = _StubFetcher({
        "555": {
            "organization": {
                "address": "2010 Fourth St",
                "city": "Tillamook",
                "state": "OR",
                "zipcode": "97141",
            }
        },
    })
    enricher = ProPublicaWebsiteEnricher(fetcher, resolver=None)
    org = Organization(name="Tides", ein="555")
    enricher.enrich([org])
    assert org.address == "2010 Fourth St, Tillamook, OR 97141"


def test_enricher_ignores_a_detail_address_with_no_street() -> None:
    """A bare city is already captured by ``org.city``."""
    fetcher = _StubFetcher({"666": {"organization": {"city": "Madras"}}})
    enricher = ProPublicaWebsiteEnricher(fetcher, resolver=None)
    org = Organization(name="X", ein="666")
    enricher.enrich([org])
    assert org.address is None


def test_enricher_does_not_overwrite_a_seeded_address() -> None:
    fetcher = _StubFetcher({
        "777": {
            "organization": {
                "address": "IRS PO Box 1",
                "city": "Madras",
                "state": "OR",
                "zipcode": "97741",
            }
        },
    })
    enricher = ProPublicaWebsiteEnricher(fetcher, resolver=None)
    org = Organization(name="X", ein="777", address="Hand verified, Madras, OR 97741")
    enricher.enrich([org])
    assert org.address == "Hand verified, Madras, OR 97741"


def test_enricher_uses_url_in_detail_payload_directly() -> None:
    fetcher = _StubFetcher({
        "111": {"organization": {"city": "Portland", "website": "https://acme.org"}},
    })
    enricher = ProPublicaWebsiteEnricher(fetcher, resolver=None)

    orgs = [Organization(name="Acme", ein="111", topics={Topic.HOUSING})]
    enricher.enrich(orgs)

    assert orgs[0].website == "https://acme.org"
    assert "propublica_detail" in orgs[0].discovered_via


def test_enricher_falls_back_to_resolver_with_city_context(
    fake_search,
) -> None:
    # Detail has no website, but does have a city we can use for search.
    fetcher = _StubFetcher({
        "222": {"organization": {"city": "Hillsboro"}},
    })
    # Resolver constructs `"Bienestar Inc" Hillsboro Oregon nonprofit`; match
    # on a substring that survives the quoting.
    fake_search.by_query["Hillsboro"] = [
        SearchResult(
            title="Bienestar - Affordable Housing",
            url="https://bienestar-or.org",
            snippet="Latino-focused affordable housing serving Hillsboro, OR.",
        ),
    ]
    enricher = ProPublicaWebsiteEnricher(fetcher, resolver=HomepageResolver(fake_search))

    orgs = [Organization(name="Bienestar Inc", ein="222")]
    enricher.enrich(orgs)

    assert orgs[0].website == "https://bienestar-or.org"
    assert orgs[0].city == "Hillsboro"  # detail filled in the city
    # The resolver query includes the city, not just the name+suffix.
    assert any("Hillsboro" in q for q in fake_search.calls)


def test_enricher_merges_city_and_ntee_classification_into_keywords() -> None:
    fetcher = _StubFetcher({
        "333": {
            "organization": {
                "city": "Salem",
                "ntee_classification": "Family Services",
            },
        },
    })
    enricher = ProPublicaWebsiteEnricher(fetcher, resolver=None)
    orgs = [Organization(name="X", ein="333")]
    enricher.enrich(orgs)

    assert orgs[0].city == "Salem"
    assert "Family Services" in orgs[0].keywords
    assert "propublica_detail" in orgs[0].discovered_via


def test_enricher_tolerates_missing_payloads(fake_search) -> None:
    fetcher = _StubFetcher({"444": None})
    enricher = ProPublicaWebsiteEnricher(fetcher, resolver=HomepageResolver(fake_search))
    orgs = [Organization(name="Missing", ein="444")]
    enricher.enrich(orgs)
    assert orgs[0].website is None  # nothing happened, no crash
