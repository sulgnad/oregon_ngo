"""End-to-end orchestrator: discover \u2192 dedup \u2192 resolve \u2192 extract \u2192 persist."""

from __future__ import annotations

import logging
from typing import Iterable, Sequence

from . import geo
from .discovery.base import coalesce_duplicates, dedup_key
from .extractors.crawler import PageCrawler
from .extractors.mission import MissionExtractor
from .models import Organization, Topic
from .protocols import Clock, DiscoverySource, Enricher, MissionStore, Storage
from .resolver import HomepageResolver


logger = logging.getLogger(__name__)

# Outcomes of comparing an organization's location against the target counties.
_IN_COUNTY = "in_county"
_ELSEWHERE = "elsewhere"
_UNKNOWN_LOCATION = "unknown"


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

    def discover(
        self,
        *,
        topic_filter: set[Topic] | None = None,
        county_filter: set[str] | None = None,
    ) -> list[Organization]:
        """Run every discovery source and return the deduped result.

        ``county_filter`` is applied *leniently* here: an organization is
        dropped only when we can already tell it belongs to another county.
        Records with no location yet survive, because an enricher may still
        supply the city. :meth:`scope_to_counties` applies the strict filter
        after enrichment.
        """
        targets = _normalize_counties(county_filter)
        merged: dict[str, Organization] = {}
        skipped = 0
        for source in self._sources:
            try:
                produced = list(source.discover())
            except Exception:  # pragma: no cover - defensive
                logger.exception("discovery source %s failed", source.name)
                continue
            for org in produced:
                if topic_filter and not (org.topics & topic_filter):
                    continue
                if targets and _county_relevance(org, targets) == _ELSEWHERE:
                    skipped += 1
                    continue
                key = dedup_key(org)
                merged[key] = (
                    merged[key].merge(org) if key in merged else org
                )
        if skipped:
            logger.info("skipped %d organizations outside the target counties", skipped)
        return list(merged.values())

    def scope_to_counties(
        self, orgs: Iterable[Organization], counties: set[str]
    ) -> list[Organization]:
        """Backfill ``county`` from ``city`` and keep only in-county orgs.

        Unlike the lenient filter in :meth:`discover`, this drops records
        whose location is still unknown — by this point every enricher has
        run, so an org with no resolvable county cannot be attributed to one
        of the target counties with any confidence.
        """
        targets = _normalize_counties(counties)
        if not targets:
            return list(orgs)
        kept: list[Organization] = []
        for org in orgs:
            _backfill_county(org)
            if _county_relevance(org, targets) == _IN_COUNTY:
                kept.append(org)
            else:
                logger.debug(
                    "dropping %s (city=%r county=%r) — outside target counties",
                    org.name,
                    org.city,
                    org.county,
                )
        return kept

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

    def run_all(
        self,
        *,
        topic_filter: set[Topic] | None = None,
        county_filter: set[str] | None = None,
    ) -> list[Organization]:
        discovered = self.discover(
            topic_filter=topic_filter, county_filter=county_filter
        )
        enriched = self.enrich(discovered)
        # Enrichment fills in verified cities, so the strict county filter runs
        # here — after enrichment, before the coalesce pass, so we never waste
        # a crawl on an out-of-county org.
        if county_filter:
            scoped = self.scope_to_counties(enriched, county_filter)
            logger.info(
                "county scoping: %d -> %d organizations", len(enriched), len(scoped)
            )
            enriched = scoped
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


# --- county scoping helpers -------------------------------------------------


def _normalize_counties(counties: Iterable[str] | None) -> set[str]:
    if not counties:
        return set()
    return {
        normalized
        for normalized in (geo.normalize_place(c) for c in counties)
        if normalized
    }


def _backfill_county(org: Organization) -> None:
    """Fill in ``county`` from ``city`` when the source didn't supply one."""
    if org.county:
        return
    resolved = geo.county_for_city(org.city)
    if resolved:
        org.county = resolved


def _county_relevance(org: Organization, targets: set[str]) -> str:
    """Classify an org's location against the target counties.

    Returns ``_IN_COUNTY``, ``_ELSEWHERE`` or ``_UNKNOWN_LOCATION``.

    A stated county wins over the city. ``"Deschutes / Crook / Jefferson"``
    counts as in-county for Jefferson, since multi-county service areas are
    how the starter list records tri-county agencies.

    A city that we cannot map to a target county is treated as ``_ELSEWHERE``
    rather than ``_UNKNOWN_LOCATION``. That is what keeps a county run
    tractable: ProPublica returns a city for essentially every Oregon
    nonprofit, so without this the lenient discovery filter would let the
    whole statewide result set through to the (network-bound) enrichment
    stage. The cost is that an org listed under an unrecognised community
    name gets dropped — add it to ``geo`` or to the seed YAML if that
    happens.
    """
    if org.county:
        found = geo.counties_in(org.county, include_also_serves=True)
        if found:
            matched = any(geo.normalize_place(c) in targets for c in found)
            return _IN_COUNTY if matched else _ELSEWHERE
    if org.city:
        resolved = geo.county_for_city(org.city)
        if resolved:
            return _IN_COUNTY if geo.normalize_place(resolved) in targets else _ELSEWHERE
        return _ELSEWHERE
    return _UNKNOWN_LOCATION
