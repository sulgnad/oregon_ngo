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
from .extractors.crawler import PageCrawler
from .extractors.mission import MissionExtractor
from .http import RequestsHttpClient
from .mission_store import FilesystemMissionStore
from .models import Topic
from .pipeline import Pipeline
from .resolver import HomepageResolver
from .search.duckduckgo import DuckDuckGoSearch
from .storage import CsvStorage


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="oregon_ngo_scraper")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover", help="Run discovery only and print counts")
    extract_parser = sub.add_parser("extract", help="Extract mission/values for already-discovered orgs")
    extract_parser.add_argument("--limit", type=int, default=0)
    runall = sub.add_parser("run-all", help="Discover + extract + persist")
    for p in (extract_parser, runall):
        p.add_argument(
            "--topic",
            choices=[t.value for t in Topic],
            action="append",
            default=[],
        )
        p.add_argument("--no-playwright", action="store_true")

    args = parser.parse_args(argv)
    _setup_logging()

    http = RequestsHttpClient()
    clock = SystemClock()
    search = DuckDuckGoSearch(http)
    resolver = HomepageResolver(search)
    browser = None  # PlaywrightBrowser is opt-in via removing this guard
    crawler = PageCrawler(http, browser=browser)
    extractor = MissionExtractor()
    storage = CsvStorage(
        DATA_DIR / "output" / "orgs.csv",
        jsonl_path=DATA_DIR / "output" / "orgs.jsonl",
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
        print(f"Wrote {len(results)} rows to {DATA_DIR / 'output' / 'orgs.csv'}")
        return 0
    return 1


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
