"""End-to-end orchestrator: discover \u2192 dedup \u2192 resolve \u2192 extract \u2192 persist."""

from __future__ import annotations

import logging
from typing import Iterable, Sequence

from .discovery.base import coalesce_duplicates, dedup_key
from .extractors.crawler import PageCrawler
from .extractors.mission import MissionExtractor
from .models import Organization, Topic
from .protocols import Clock, DiscoverySource, Enricher, MissionStore, Storage
from .resolver import HomepageResolver


logger = logging.getLogger(__name__)


class Pipeline:
    """Wires together every collaborator and runs the full job.

    Every collaborator is injected via the constructor; this class itself
    performs no I/O. ``cli.py`` is responsible for constructing real
    implementations.
    """

    def __init__(
        self,
        *,
        sources: Sequence[DiscoverySource],
        resolver: HomepageResolver,
        crawler: PageCrawler,
        extractor: MissionExtractor,
        storage: Storage,
        clock: Clock,
        mission_store: MissionStore | None = None,
        enrichers: Sequence[Enricher] = (),
    ) -> None:
        self._sources = list(sources)
        self._resolver = resolver
        self._crawler = crawler
        self._extractor = extractor
        self._storage = storage
        self._clock = clock
        self._mission_store = mission_store
        self._enrichers = list(enrichers)

    def discover(self, *, topic_filter: set[Topic] | None = None) -> list[Organization]:
        """Run every discovery source and return the deduped result."""
        merged: dict[str, Organization] = {}
        for source in self._sources:
            try:
                produced = list(source.discover())
            except Exception:  # pragma: no cover - defensive
                logger.exception("discovery source %s failed", source.name)
                continue
            for org in produced:
                if topic_filter and not (org.topics & topic_filter):
                    continue
                key = dedup_key(org)
                merged[key] = (
                    merged[key].merge(org) if key in merged else org
                )
        return list(merged.values())

    def extract(self, orgs: Iterable[Organization]) -> list[Organization]:
        """Resolve URLs (if missing), crawl, extract mission/values, persist.

        Flushes the storage backend after every org so a partial run still
        produces usable output if interrupted.
        """
        out: list[Organization] = []
        orgs_list = list(orgs)
        total = len(orgs_list)
        for index, org in enumerate(orgs_list, start=1):
            logger.info("[%d/%d] %s", index, total, org.name)
            enriched = self._enrich_one(org)
            self._storage.upsert(enriched)
            out.append(enriched)
            try:
                self._storage.flush()
            except Exception:  # pragma: no cover - defensive
                logger.exception("flush failed mid-run")
        return out

    def run_all(self, *, topic_filter: set[Topic] | None = None) -> list[Organization]:
        discovered = self.discover(topic_filter=topic_filter)
        enriched = self.enrich(discovered)
        # After enrichment some EIN-only orgs gain a website that may match
        # an xlsx-keyed row — a second-pass union-find collapses them.
        deduped = coalesce_duplicates(enriched)
        if len(deduped) < len(enriched):
            logger.info(
                "coalesced %d -> %d organizations", len(enriched), len(deduped)
            )
        return self.extract(deduped)

    def enrich(self, orgs: list[Organization]) -> list[Organization]:
        """Run every registered enricher in order."""
        result = list(orgs)
        for enricher in self._enrichers:
            try:
                result = list(enricher.enrich(result))
            except Exception:  # pragma: no cover - defensive
                logger.exception("enricher %s failed", getattr(enricher, "name", enricher))
        return result

    def _enrich_one(self, org: Organization) -> Organization:
        if not org.website:
            try:
                resolved = self._resolver.resolve(org.name)
            except Exception:  # pragma: no cover - defensive
                logger.exception("resolver failed for %s", org.name)
                resolved = None
            if resolved:
                org.website = resolved
        if not org.website:
            org.scraped_at = self._clock.now()
            return org
        try:
            pages = self._crawler.crawl(org.website)
        except Exception:  # pragma: no cover - defensive
            logger.exception("crawl failed for %s (%s)", org.name, org.website)
            pages = []
        result = self._extractor.extract(pages)
        org.mission = org.mission or result.mission
        org.values = org.values or result.values
        org.mission_source_url = org.mission_source_url or result.source_url
        org.scraped_at = self._clock.now()
        # Write mission text to its own .txt file and record a pointer in the
        # database so downstream tools can grep/diff missions individually.
        if org.mission and self._mission_store is not None and not org.mission_file:
            try:
                org.mission_file = self._mission_store.write(org, org.mission)
            except Exception:  # pragma: no cover - defensive
                logger.exception("mission_store failed for %s", org.name)
        return org
