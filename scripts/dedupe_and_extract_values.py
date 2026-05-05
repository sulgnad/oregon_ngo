"""Re-process the existing scrape output: coalesce duplicates and pull values.

Steps:
1. Load every row from ``data/output/orgs.jsonl`` (preserves topics/keywords
   precisely; the CSV would lose typing for sets/lists).
2. Run ``coalesce_duplicates`` to merge www/non-www and EIN/host crossovers.
3. For every org that has a website but no values, crawl it with the
   project's ``PageCrawler`` and run the broadened ``MissionExtractor``.
   Mission text is preserved if already present; only ``values`` is filled in.
4. Re-flush ``orgs.csv`` + ``orgs.jsonl`` with the cleaned data.

Designed to be re-runnable: orgs that already have values are skipped.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from dateutil import parser as date_parser  # type: ignore[import-untyped]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from oregon_ngo_scraper.clock import SystemClock  # noqa: E402
from oregon_ngo_scraper.discovery.base import coalesce_duplicates  # noqa: E402
from oregon_ngo_scraper.extractors.crawler import PageCrawler  # noqa: E402
from oregon_ngo_scraper.extractors.mission import MissionExtractor  # noqa: E402
from oregon_ngo_scraper.http import RequestsHttpClient  # noqa: E402
from oregon_ngo_scraper.mission_store import FilesystemMissionStore  # noqa: E402
from oregon_ngo_scraper.models import Organization, Topic  # noqa: E402
from oregon_ngo_scraper.storage import CsvStorage  # noqa: E402


DATA = PROJECT_ROOT / "data"
OUT = DATA / "output"
JSONL = OUT / "orgs.jsonl"
CSV = OUT / "orgs.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("dedupe_and_extract_values")


def _load_orgs(path: Path) -> list[Organization]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    out: list[Organization] = []
    for r in rows:
        topics = {Topic.from_str(t) for t in (r.get("topics") or []) if t}
        scraped_at = None
        if r.get("scraped_at"):
            try:
                scraped_at = date_parser.parse(r["scraped_at"])
            except (ValueError, TypeError):
                scraped_at = None
        out.append(
            Organization(
                name=r.get("name", ""),
                aka=list(r.get("aka") or []),
                website=r.get("website"),
                ein=r.get("ein"),
                city=r.get("city"),
                county=r.get("county"),
                state=r.get("state") or "OR",
                topics=topics,
                keywords=list(r.get("keywords") or []),
                notes=r.get("notes"),
                verification_status=r.get("verification_status"),
                discovered_via=list(r.get("discovered_via") or []),
                source_urls=list(r.get("source_urls") or []),
                mission=r.get("mission"),
                values=r.get("values"),
                mission_source_url=r.get("mission_source_url"),
                mission_file=r.get("mission_file"),
                scraped_at=scraped_at,
            )
        )
    return out


def main() -> int:
    if not JSONL.exists():
        logger.error("missing %s; run the pipeline first", JSONL)
        return 1

    raw = _load_orgs(JSONL)
    logger.info("loaded %d rows", len(raw))

    deduped = coalesce_duplicates(raw)
    if len(deduped) < len(raw):
        logger.info("coalesced %d -> %d (-%d dupes)", len(raw), len(deduped), len(raw) - len(deduped))

    targets = [o for o in deduped if o.website and not o.values]
    logger.info(
        "values-extraction targets: %d (orgs with website but no values)",
        len(targets),
    )

    http = RequestsHttpClient()
    crawler = PageCrawler(http)
    extractor = MissionExtractor()
    mission_store = FilesystemMissionStore(
        OUT / "missions", path_relative_to=PROJECT_ROOT
    )
    clock = SystemClock()

    for index, org in enumerate(targets, start=1):
        logger.info("[%d/%d] %s -> %s", index, len(targets), org.name, org.website)
        try:
            pages = crawler.crawl(org.website)
        except Exception:
            logger.exception("crawl failed")
            continue
        result = extractor.extract(pages)
        if result.values:
            org.values = result.values
            org.mission_source_url = org.mission_source_url or result.source_url
        if result.mission and not org.mission:
            org.mission = result.mission
            org.mission_source_url = org.mission_source_url or result.source_url
            try:
                org.mission_file = mission_store.write(org, org.mission)
            except Exception:
                logger.exception("mission_store write failed")
        org.scraped_at = clock.now()

    storage = CsvStorage(CSV, jsonl_path=JSONL)
    for o in deduped:
        storage.upsert(o)
    storage.flush()
    logger.info("wrote %d rows to %s", len(deduped), CSV)
    return 0


if __name__ == "__main__":
    sys.exit(main())
