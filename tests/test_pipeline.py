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
from oregon_ngo_scraper.extractors.contact import ContactExtractor
from oregon_ngo_scraper.extractors.crawler import PageCrawler
from oregon_ngo_scraper.extractors.mission import MissionExtractor
from oregon_ngo_scraper.mission_store import FilesystemMissionStore
from oregon_ngo_scraper.models import Organization, OrgType, Topic
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


def test_seeded_mission_is_kept_and_not_credited_to_the_scraped_page(
    tmp_path: Path, fake_http, fake_search, fixed_clock, load_fixture
) -> None:
    """A hand-seeded mission must beat the page text, and its provenance must
    not be rewritten to point at a page that did not produce it."""
    fake_http.responses["https://bradleyangle.org/"] = HttpResponse(
        status_code=200,
        text=load_fixture("sample_home_page.html"),
        url="https://bradleyangle.org/",
    )
    fake_http.responses["https://bradleyangle.org/about"] = HttpResponse(
        status_code=200,
        text=load_fixture("sample_about_page.html"),
        url="https://bradleyangle.org/about",
    )
    seeded = Organization(
        name="Bradley Angle",
        website="https://bradleyangle.org",
        topics={Topic.DSV},
        mission="Hand-verified mission text.",
    )
    pipeline = Pipeline(
        sources=[_StaticSeed([seeded])],
        resolver=HomepageResolver(fake_search),
        crawler=PageCrawler(
            fake_http, candidate_paths=("/", "/about"), max_pages=4
        ),
        extractor=MissionExtractor(),
        storage=CsvStorage(tmp_path / "orgs.csv"),
        clock=fixed_clock,
    )
    result = pipeline.run_all()[0]
    assert result.mission == "Hand-verified mission text."
    assert result.mission_source_url is None


def _contact_pipeline(tmp_path: Path, org: Organization, html: str, fake_http, fake_search, fixed_clock):
    url = org.website.rstrip("/") + "/"
    fake_http.responses[url] = HttpResponse(status_code=200, text=html, url=url)
    return Pipeline(
        sources=[_StaticSeed([org])],
        resolver=HomepageResolver(fake_search),
        crawler=PageCrawler(fake_http, candidate_paths=("/",), max_pages=2),
        extractor=MissionExtractor(),
        storage=CsvStorage(tmp_path / "orgs.csv"),
        clock=fixed_clock,
        contact_extractor=ContactExtractor(),
    )


_COMMISSIONER_FOOTER = '<a href="mailto:commissioner@county.gov">Commissioner</a>'


def test_scraped_email_is_ignored_for_shared_host_government_orgs(
    tmp_path: Path, fake_http, fake_search, fixed_clock
) -> None:
    """A county site links other officials' mailboxes; the domain match proves
    nothing about which department an address belongs to."""
    org = Organization(
        name="County Health Dept",
        website="https://county.gov",
        org_type=OrgType.GOVERNMENT,
        topics={Topic.MATERNAL_HEALTH},
    )
    pipeline = _contact_pipeline(
        tmp_path, org, _COMMISSIONER_FOOTER, fake_http, fake_search, fixed_clock
    )
    assert pipeline.run_all()[0].email is None


def test_seeded_email_is_kept_for_government_orgs(
    tmp_path: Path, fake_http, fake_search, fixed_clock
) -> None:
    org = Organization(
        name="County Health Dept",
        website="https://county.gov",
        email="health@county.gov",
        org_type=OrgType.GOVERNMENT,
        topics={Topic.MATERNAL_HEALTH},
    )
    pipeline = _contact_pipeline(
        tmp_path, org, _COMMISSIONER_FOOTER, fake_http, fake_search, fixed_clock
    )
    assert pipeline.run_all()[0].email == "health@county.gov"


def test_tribal_government_email_is_not_scraped_either(
    tmp_path: Path, fake_http, fake_search, fixed_clock
) -> None:
    org = Organization(
        name="Tribal Program",
        website="https://county.gov",
        org_type=OrgType.TRIBAL_GOVERNMENT,
        topics={Topic.DSV},
    )
    pipeline = _contact_pipeline(
        tmp_path, org, _COMMISSIONER_FOOTER, fake_http, fake_search, fixed_clock
    )
    assert pipeline.run_all()[0].email is None


def test_scraped_email_is_still_used_for_nonprofits(
    tmp_path: Path, fake_http, fake_search, fixed_clock
) -> None:
    """A nonprofit owns its domain, so a same-domain address is its own."""
    org = Organization(
        name="Some Nonprofit",
        website="https://nonprofit.org",
        org_type=OrgType.NONPROFIT,
        topics={Topic.DSV},
    )
    html = '<a href="mailto:help@nonprofit.org">help</a>'
    pipeline = _contact_pipeline(
        tmp_path, org, html, fake_http, fake_search, fixed_clock
    )
    assert pipeline.run_all()[0].email == "help@nonprofit.org"


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
