"""County scoping: lenient at discovery, strict after enrichment."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from oregon_ngo_scraper.extractors.crawler import PageCrawler
from oregon_ngo_scraper.extractors.mission import MissionExtractor
from oregon_ngo_scraper.models import Organization, Topic
from oregon_ngo_scraper.pipeline import Pipeline
from oregon_ngo_scraper.resolver import HomepageResolver
from oregon_ngo_scraper.storage import CsvStorage


TARGETS = {"Jefferson", "Tillamook"}


class _StaticSource:
    name = "static"

    def __init__(self, orgs: list[Organization]) -> None:
        self._orgs = orgs

    def discover(self) -> Iterable[Organization]:
        return list(self._orgs)


def _pipeline(orgs: list[Organization], fake_http, fake_search, fixed_clock):
    return Pipeline(
        sources=[_StaticSource(orgs)],
        resolver=HomepageResolver(fake_search),
        crawler=PageCrawler(fake_http),
        extractor=MissionExtractor(),
        storage=CsvStorage(Path("/tmp/_unused_county.csv")),  # never flushed
        clock=fixed_clock,
    )


def test_discover_drops_orgs_known_to_be_elsewhere(
    fake_http, fake_search, fixed_clock
) -> None:
    pipeline = _pipeline(
        [
            Organization(name="In County", city="Madras", topics={Topic.DSV}),
            Organization(name="Elsewhere", city="Portland", topics={Topic.DSV}),
            Organization(
                name="By County Field", county="Tillamook", topics={Topic.HOUSING}
            ),
        ],
        fake_http,
        fake_search,
        fixed_clock,
    )
    names = {o.name for o in pipeline.discover(county_filter=TARGETS)}
    assert names == {"In County", "By County Field"}


def test_discover_keeps_orgs_with_unknown_location(
    fake_http, fake_search, fixed_clock
) -> None:
    """An enricher may still supply the city, so don't drop these yet."""
    pipeline = _pipeline(
        [Organization(name="No Location Yet", topics={Topic.DSV})],
        fake_http,
        fake_search,
        fixed_clock,
    )
    names = {o.name for o in pipeline.discover(county_filter=TARGETS)}
    assert names == {"No Location Yet"}


def test_discover_without_county_filter_is_unchanged(
    fake_http, fake_search, fixed_clock
) -> None:
    pipeline = _pipeline(
        [
            Organization(name="A", city="Portland", topics={Topic.DSV}),
            Organization(name="B", city="Madras", topics={Topic.DSV}),
        ],
        fake_http,
        fake_search,
        fixed_clock,
    )
    assert len(pipeline.discover()) == 2


def test_scope_to_counties_backfills_county_from_city(
    fake_http, fake_search, fixed_clock
) -> None:
    pipeline = _pipeline([], fake_http, fake_search, fixed_clock)
    org = Organization(name="X", city="Nehalem", topics={Topic.HOUSING})
    kept = pipeline.scope_to_counties([org], TARGETS)
    assert len(kept) == 1
    assert kept[0].county == "Tillamook"


def test_scope_to_counties_keeps_existing_county_value(
    fake_http, fake_search, fixed_clock
) -> None:
    pipeline = _pipeline([], fake_http, fake_search, fixed_clock)
    org = Organization(
        name="Tillamook Only",
        city="Tillamook",
        county="Tillamook",
        topics={Topic.DSV},
    )
    kept = pipeline.scope_to_counties([org], TARGETS)
    assert [o.name for o in kept] == ["Tillamook Only"]
    assert kept[0].county == "Tillamook"


def test_multi_county_org_needs_a_local_office(
    fake_http, fake_search, fixed_clock
) -> None:
    """A regional agency headquartered elsewhere is not a county org.

    ``Deschutes / Crook / Jefferson`` names a target county, but a Bend
    address means there is no physical presence in Jefferson.
    """
    pipeline = _pipeline([], fake_http, fake_search, fixed_clock)
    org = Organization(
        name="Bend Regional Agency",
        city="Bend",
        county="Deschutes / Crook / Jefferson",
        topics={Topic.HOUSING},
    )
    assert pipeline.scope_to_counties([org], TARGETS) == []


def test_multi_county_org_kept_when_office_is_in_county(
    fake_http, fake_search, fixed_clock
) -> None:
    """Saving Grace/NeighborImpact qualify for Jefferson via Madras offices."""
    pipeline = _pipeline([], fake_http, fake_search, fixed_clock)
    org = Organization(
        name="Saving Grace",
        city="Madras",
        county="Deschutes / Crook / Jefferson",
        topics={Topic.DSV},
    )
    assert [o.name for o in pipeline.scope_to_counties([org], TARGETS)] == [
        "Saving Grace"
    ]


def test_discovery_stage_still_admits_multi_county_orgs(
    fake_http, fake_search, fixed_clock
) -> None:
    """The office rule is strict-stage only; enrichment may yet supply a city."""
    pipeline = _pipeline(
        [
            Organization(
                name="Regional",
                county="Deschutes / Crook / Jefferson",
                topics={Topic.HOUSING},
            )
        ],
        fake_http,
        fake_search,
        fixed_clock,
    )
    assert [o.name for o in pipeline.discover(county_filter=TARGETS)] == ["Regional"]


def test_baker_city_org_is_scoped_into_baker(
    fake_http, fake_search, fixed_clock
) -> None:
    pipeline = _pipeline([], fake_http, fake_search, fixed_clock)
    org = Organization(name="MayDay", city="Baker City", topics={Topic.DSV})
    kept = pipeline.scope_to_counties([org], {"Baker"})
    assert [o.county for o in kept] == ["Baker"]


def test_union_county_org_is_not_scoped_into_baker(
    fake_http, fake_search, fixed_clock
) -> None:
    """North Powder is just over the line in Union County."""
    pipeline = _pipeline([], fake_http, fake_search, fixed_clock)
    org = Organization(name="X", city="North Powder", topics={Topic.DSV})
    assert pipeline.scope_to_counties([org], {"Baker"}) == []


def test_regional_agency_needs_a_baker_office(
    fake_http, fake_search, fixed_clock
) -> None:
    """A La Grande agency listing Baker in its service area has no Baker office."""
    pipeline = _pipeline([], fake_http, fake_search, fixed_clock)
    org = Organization(
        name="La Grande Regional",
        city="La Grande",
        county="Union / Baker / Wallowa / Grant",
        topics={Topic.HOUSING},
    )
    assert pipeline.scope_to_counties([org], {"Baker"}) == []


def test_scope_to_counties_drops_unknown_locations(
    fake_http, fake_search, fixed_clock
) -> None:
    """Strict stage: no location by now means we can't attribute it."""
    pipeline = _pipeline([], fake_http, fake_search, fixed_clock)
    kept = pipeline.scope_to_counties(
        [
            Organization(name="Unknown", topics={Topic.DSV}),
            Organization(name="Known", city="Tillamook", topics={Topic.DSV}),
        ],
        TARGETS,
    )
    assert [o.name for o in kept] == ["Known"]


def test_scope_to_counties_with_no_targets_is_a_noop(
    fake_http, fake_search, fixed_clock
) -> None:
    pipeline = _pipeline([], fake_http, fake_search, fixed_clock)
    orgs = [Organization(name="A"), Organization(name="B", city="Portland")]
    assert len(pipeline.scope_to_counties(orgs, set())) == 2


def test_run_all_applies_the_strict_filter(
    fake_http, fake_search, fixed_clock
) -> None:
    pipeline = _pipeline(
        [
            Organization(name="Madras Org", city="Madras", topics={Topic.HOUSING}),
            Organization(name="Nowhere Org", topics={Topic.HOUSING}),
        ],
        fake_http,
        fake_search,
        fixed_clock,
    )
    results = pipeline.run_all(county_filter=TARGETS)
    assert [o.name for o in results] == ["Madras Org"]
