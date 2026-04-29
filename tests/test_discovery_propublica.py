from __future__ import annotations

import json

from oregon_ngo_scraper.discovery.propublica import (
    SEARCH_ENDPOINT,
    ProPublicaDiscovery,
    _topics_for_ntee,
)
from oregon_ngo_scraper.models import Topic
from oregon_ngo_scraper.protocols import HttpResponse


def test_topics_for_ntee_maps_dsv_housing_maternal() -> None:
    assert _topics_for_ntee("I71") == {Topic.DSV}
    assert _topics_for_ntee("L21") == {Topic.HOUSING}
    assert _topics_for_ntee("E40") == {Topic.MATERNAL_HEALTH}
    assert _topics_for_ntee("B82") == set()
    assert _topics_for_ntee("") == set()


def test_search_filters_to_relevant_ntee_codes(fake_http, load_fixture) -> None:
    payload = load_fixture("propublica_search.json")
    fake_http.responses[SEARCH_ENDPOINT] = HttpResponse(
        status_code=200,
        text=payload,
        url=SEARCH_ENDPOINT,
    )
    src = ProPublicaDiscovery(
        fake_http,
        ntee_major_groups=(5,),
        max_pages_per_group=1,
    )

    orgs = list(src.discover())
    by_name = {o.name: o for o in orgs}

    # Three relevant NTEE matches; one ("Some Unrelated Charity") gets filtered.
    assert set(by_name) == {
        "Bradley Angle",
        "Habitat For Humanity Portland Region",
        "Maternity Support Services Of Oregon",
    }
    assert by_name["Bradley Angle"].topics == {Topic.DSV}
    assert by_name["Bradley Angle"].ein == "930388110"
    assert by_name["Habitat For Humanity Portland Region"].topics == {Topic.HOUSING}
    assert by_name["Maternity Support Services Of Oregon"].topics == {Topic.MATERNAL_HEALTH}


def test_pagination_stops_when_num_pages_reached(fake_http) -> None:
    page0 = json.dumps({
        "num_pages": 1,
        "organizations": [{"ein": 1, "name": "A", "ntee_code": "I71"}],
    })
    fake_http.responses[SEARCH_ENDPOINT] = HttpResponse(
        status_code=200, text=page0, url=SEARCH_ENDPOINT
    )

    src = ProPublicaDiscovery(
        fake_http,
        ntee_major_groups=(5,),
        max_pages_per_group=10,
    )
    list(src.discover())

    # Should have stopped after one page since num_pages == 1.
    assert len(fake_http.calls) == 1


def test_dedupes_eins_across_groups(fake_http) -> None:
    body = json.dumps({
        "num_pages": 1,
        "organizations": [{"ein": 1, "name": "Same", "ntee_code": "I71"}],
    })
    fake_http.responses[SEARCH_ENDPOINT] = HttpResponse(
        status_code=200, text=body, url=SEARCH_ENDPOINT
    )
    src = ProPublicaDiscovery(
        fake_http,
        ntee_major_groups=(4, 5),
        max_pages_per_group=1,
    )
    orgs = list(src.discover())
    assert len(orgs) == 1
