"""End-to-end pipeline test using injected fakes.

Drives the full discover \u2192 resolve \u2192 crawl \u2192 extract \u2192 persist flow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from oregon_ngo_scraper.discovery.ocadsv import (
    COALITION_MEMBERS_URL,
    OcadsvDiscovery,
)
from oregon_ngo_scraper.discovery.propublica import (
    SEARCH_ENDPOINT,
    ProPublicaDiscovery,
)
from oregon_ngo_scraper.extractors.crawler import PageCrawler
from oregon_ngo_scraper.extractors.mission import MissionExtractor
from oregon_ngo_scraper.mission_store import FilesystemMissionStore
from oregon_ngo_scraper.models import Organization, Topic
from oregon_ngo_scraper.pipeline import Pipeline
from oregon_ngo_scraper.protocols import HttpResponse, SearchResult
from oregon_ngo_scraper.resolver import HomepageResolver
from oregon_ngo_scraper.storage import CsvStorage


class _StaticSeed:
    name = "static"

    def __init__(self, orgs: list[Organization]) -> None:
        self._orgs = orgs

    def discover(self) -> Iterable[Organization]:
        return list(self._orgs)


def test_full_pipeline_writes_csv(
    tmp_path: Path,
    fake_http,
    fake_search,
    fixed_clock,
    load_fixture,
) -> None:
    # --- Discovery responses ---
    fake_http.responses[COALITION_MEMBERS_URL] = HttpResponse(
        status_code=200,
        text=load_fixture("ocadsv_members.html"),
        url=COALITION_MEMBERS_URL,
    )
    fake_http.responses[SEARCH_ENDPOINT] = HttpResponse(
        status_code=200,
        text=load_fixture("propublica_search.json"),
        url=SEARCH_ENDPOINT,
    )

    # --- Crawl + extract responses ---
    home_html = load_fixture("sample_home_page.html")
    about_html = load_fixture("sample_about_page.html")
    fake_http.responses["https://bradleyangle.org/"] = HttpResponse(
        status_code=200, text=home_html, url="https://bradleyangle.org/"
    )
    fake_http.responses["https://bradleyangle.org/about"] = HttpResponse(
        status_code=200, text=about_html, url="https://bradleyangle.org/about"
    )

    # --- Resolver (only used when a discovered org has no website) ---
    fake_search.by_query["Tides of Change"] = [
        SearchResult(
            title="Tides of Change",
            url="https://tidesofchangenw.org",
            snippet="Tillamook County DV agency",
        ),
    ]

    # Build the real pipeline with fake collaborators.
    csv_path = tmp_path / "orgs.csv"
    storage = CsvStorage(csv_path)
    mission_store = FilesystemMissionStore(
        tmp_path / "missions", path_relative_to=tmp_path
    )
    crawler = PageCrawler(
        fake_http,
        candidate_paths=("/", "/about"),
        max_pages=4,
    )
    pipeline = Pipeline(
        sources=[
            OcadsvDiscovery(fake_http),
            ProPublicaDiscovery(
                fake_http,
                ntee_major_groups=(5,),
                max_pages_per_group=1,
            ),
        ],
        resolver=HomepageResolver(fake_search),
        crawler=crawler,
        extractor=MissionExtractor(),
        storage=storage,
        clock=fixed_clock,
        mission_store=mission_store,
    )

    results = pipeline.run_all()

    # CSV exists and has rows for orgs we discovered.
    assert csv_path.exists()
    contents = csv_path.read_text()
    assert "Bradley Angle" in contents
    # Bradley Angle's mission was extracted from the about page.
    bradley = next(o for o in results if o.name == "Bradley Angle")
    assert bradley.website == "https://bradleyangle.org"
    assert bradley.mission is not None
    assert "end domestic and sexual violence" in bradley.mission
    assert bradley.values is not None
    assert bradley.mission_source_url == "https://bradleyangle.org/about"
    # Topics merged across OCADSV and ProPublica.
    assert Topic.DSV in bradley.topics
    # Scraped-at populated from the injected clock.
    assert bradley.scraped_at == fixed_clock.now()
    # Mission text was written to its own .txt file and the pointer recorded.
    assert bradley.mission_file is not None
    mission_path = tmp_path / bradley.mission_file
    assert mission_path.exists()
    assert "end domestic and sexual violence" in mission_path.read_text()
    # The CSV row carries the same pointer.
    assert bradley.mission_file in contents


def test_topic_filter_excludes_other_topics(fake_http, fake_search, fixed_clock) -> None:
    seed = _StaticSeed([
        Organization(name="A", topics={Topic.DSV}),
        Organization(name="B", topics={Topic.HOUSING}),
    ])
    storage = CsvStorage(Path("/tmp/_unused.csv"))  # never flushed
    pipeline = Pipeline(
        sources=[seed],
        resolver=HomepageResolver(fake_search),
        crawler=PageCrawler(fake_http),
        extractor=MissionExtractor(),
        storage=storage,
        clock=fixed_clock,
    )
    discovered = pipeline.discover(topic_filter={Topic.DSV})
    assert [o.name for o in discovered] == ["A"]
