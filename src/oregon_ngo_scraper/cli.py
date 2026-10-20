"""Command-line entry point. Composes real implementations and runs them.

This module is the only place where production adapters are instantiated; the
rest of the codebase only ever depends on the protocols.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .clock import SystemClock
from .discovery.link_list import HousingAllianceDiscovery, MaternalHealthDiscovery
from .discovery.ocadsv import OcadsvDiscovery
from .discovery.oregon_sos import OregonSosDiscovery
from .discovery.propublica import ProPublicaDiscovery
from .discovery.seeds import SeedDiscovery
from .discovery.xlsx_starter import XlsxStarterListDiscovery
from .enrichers.propublica_website import (
    ProPublicaDetailFetcher,
    ProPublicaWebsiteEnricher,
)
from .extractors.contact import ContactExtractor
from .extractors.crawler import PageCrawler
from .extractors.mission import MissionExtractor
from .http import RequestsHttpClient
from .mission_store import FilesystemMissionStore
from .county_storage import CountySplitStorage, county_paths, county_slug
from .models import Topic
from .pipeline import Pipeline
from .resolver import HomepageResolver
from .search.duckduckgo import DuckDuckGoSearch
from .storage import CsvStorage


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

#: Counties collected by ``collect-counties`` when ``--county`` is not given.
DEFAULT_COUNTIES = ("Jefferson", "Tillamook")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="oregon_ngo_scraper")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover", help="Run discovery only and print counts")
    extract_parser = sub.add_parser("extract", help="Extract mission/values for already-discovered orgs")
    extract_parser.add_argument("--limit", type=int, default=0)
    runall = sub.add_parser("run-all", help="Discover + extract + persist")
    counties_parser = sub.add_parser(
        "collect-counties",
        help="Discover + extract + persist, scoped to one or more counties",
    )
    counties_parser.add_argument(
        "--county",
        action="append",
        default=[],
        help=(
            "County to collect for; repeatable. "
            f"Defaults to {' and '.join(DEFAULT_COUNTIES)}."
        ),
    )
    counties_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Directory for the per-county tables. Each county gets its own "
            "<county>_snmp*.csv files. Defaults to data/output."
        ),
    )
    for p in (extract_parser, runall, counties_parser):
        p.add_argument(
            "--topic",
            choices=[t.value for t in Topic],
            action="append",
            default=[],
        )
        p.add_argument("--no-playwright", action="store_true")

    args = parser.parse_args(argv)
    _setup_logging()

    counties: list[str] = list(getattr(args, "county", None) or DEFAULT_COUNTIES)
    county_scoped = args.cmd == "collect-counties"
    output_dir = Path(getattr(args, "output_dir", None) or DATA_DIR / "output")
    csv_path = DATA_DIR / "output" / "orgs.csv"
    jsonl_path = DATA_DIR / "output" / "orgs.jsonl"

    http = RequestsHttpClient()
    clock = SystemClock()
    search = DuckDuckGoSearch(http)
    resolver = HomepageResolver(search)
    browser = None  # PlaywrightBrowser is opt-in via removing this guard
    # The county collection targets a schema with address/phone columns, so it
    # pays for the extra contact-page fetches; the statewide run does not.
    crawler = PageCrawler(http, browser=browser, include_contact_pages=county_scoped)
    extractor = MissionExtractor()
    contact_extractor = ContactExtractor() if county_scoped else None
    # County runs write one set of tables per county; the statewide run keeps
    # the project's own single 15-column file and is never overwritten by a
    # narrower collection.
    storage = (
        CountySplitStorage(output_dir, counties)
        if county_scoped
        else CsvStorage(csv_path, jsonl_path=jsonl_path)
    )
    mission_store = FilesystemMissionStore(
        DATA_DIR / "output" / "missions",
        path_relative_to=PROJECT_ROOT,
    )

    sources = [
        # The Voices Project starter list is the canonical hand-curated source;
        # listed first so its city/county/keywords/notes are preferred during
        # de-duplication merges.
        XlsxStarterListDiscovery(DATA_DIR / "seeds" / "oregon_starter_list.xlsx"),
        SeedDiscovery(DATA_DIR / "seeds" / "seed_orgs.yml"),
        OcadsvDiscovery(http),
        ProPublicaDiscovery(http),
        OregonSosDiscovery(DATA_DIR / "seeds" / "oregon_sos.csv"),
        HousingAllianceDiscovery(http),
        MaternalHealthDiscovery(http),
    ]
    if county_scoped:
        # Hand-curated county orgs go first so their county/keywords/notes win
        # during merges, same rationale as the starter list above.
        for seed_name, seed_path in reversed(_county_seed_files(counties)):
            sources.insert(0, SeedDiscovery(seed_path, name=seed_name))
    enrichers = [
        # Hits ProPublica's per-org detail endpoint to grab verified address
        # info and (when present) any URL-shaped fields. Falls back to a
        # city-scoped DDG search via the resolver, so ProPublica-discovered
        # orgs that lacked a website at discovery time gain one here.
        ProPublicaWebsiteEnricher(
            ProPublicaDetailFetcher(http),
            resolver=resolver,
        ),
    ]

    pipeline = Pipeline(
        sources=sources,
        resolver=resolver,
        crawler=crawler,
        extractor=extractor,
        storage=storage,
        clock=clock,
        mission_store=mission_store,
        enrichers=enrichers,
        contact_extractor=contact_extractor,
    )

    topic_filter: set[Topic] | None = None
    if getattr(args, "topic", None):
        topic_filter = {Topic.from_str(t) for t in args.topic}

    if args.cmd == "discover":
        orgs = pipeline.discover(topic_filter=topic_filter)
        print(f"Discovered {len(orgs)} unique organizations")
        return 0
    if args.cmd == "extract":
        discovered = pipeline.discover(topic_filter=topic_filter)
        if args.limit:
            discovered = discovered[: args.limit]
        results = pipeline.extract(discovered)
        print(f"Extracted mission/values for {len(results)} organizations")
        return 0
    if args.cmd == "run-all":
        results = pipeline.run_all(topic_filter=topic_filter)
        print(f"Wrote {len(results)} rows to {csv_path}")
        return 0
    if args.cmd == "collect-counties":
        results = pipeline.run_all(
            topic_filter=topic_filter, county_filter=set(counties)
        )
        print(f"Wrote {len(results)} rows across {len(counties)} counties:")
        for county, count in storage.counts().items():
            print(f"  {county}: {count} organizations")
            for role, path in county_paths(output_dir, county).items():
                print(f"    {role:<14} {path}")
        if storage.unrouted:
            print(f"  {len(storage.unrouted)} organizations matched no target county")
        return 0
    return 1


#: Jefferson and Tillamook were curated together before the collection went
#: per-county, so one seed file still covers both. Every other county has its
#: own file under ``data/seeds/counties/``.
_LEGACY_SEED_FILE = "jefferson_tillamook.yml"
_LEGACY_SEED_COUNTIES = frozenset({"jefferson", "tillamook"})


def _county_seed_files(counties: list[str]) -> list[tuple[str, Path]]:
    """Seed files that exist for the requested counties, as (name, path).

    A county with no seed file is not an error: it simply relies on the
    automated sources, which is much weaker for small rural counties.
    """
    seeds_dir = DATA_DIR / "seeds"
    found: list[tuple[str, Path]] = []
    if _LEGACY_SEED_COUNTIES & {county_slug(c) for c in counties}:
        legacy = seeds_dir / _LEGACY_SEED_FILE
        if legacy.exists():
            found.append(("seeds:jefferson_tillamook", legacy))
    for county in counties:
        slug = county_slug(county)
        if slug in _LEGACY_SEED_COUNTIES:
            continue
        path = seeds_dir / "counties" / f"{slug}.yml"
        if path.exists():
            found.append((f"seeds:{slug}", path))
    return found


def _setup_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOGS_DIR / "scraper.log"),
            logging.StreamHandler(sys.stdout),
        ],
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
