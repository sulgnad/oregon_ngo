"""End-to-end orchestrator: discover \u2192 dedup \u2192 resolve \u2192 extract \u2192 persist."""

from __future__ import annotations

import logging
from typing import Iterable, Sequence

from .discovery.base import dedup_key
from .extractors.crawler import PageCrawler
from .extractors.mission import MissionExtractor
from .models import Organization, Topic
from .protocols import Clock, DiscoverySource, MissionStore, Storage
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
    ) -> None:
        self._sources = list(sources)
        self._resolver = resolver
        self._crawler = crawler
        self._extractor = extractor
        self._storage = storage
        self._clock = clock
        self._mission_store = mission_store

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
        """Resolve URLs (if missing), crawl, extract mission/values, persist."""
        out: list[Organization] = []
        for org in orgs:
            enriched = self._enrich_one(org)
            self._storage.upsert(enriched)
            out.append(enriched)
        self._storage.flush()
        return out

    def run_all(self, *, topic_filter: set[Topic] | None = None) -> list[Organization]:
        discovered = self.discover(topic_filter=topic_filter)
        return self.extract(discovered)

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
