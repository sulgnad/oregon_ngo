"""Storage that writes a separate set of SNMP tables for each county.

Wraps one :class:`~.snmp_storage.SnmpCsvStorage` per target county and routes
each organization to the right one, so a multi-county run produces, for every
county ``<slug>``::

    <slug>_snmp.csv                  flat Map Database sheet
    <slug>_snmp_organizations.csv    Organization table
    <slug>_snmp_locations.csv        Location table
    <slug>_snmp.jsonl                full-payload sidecar

Implements the ``Storage`` protocol, so it drops into the pipeline unchanged.

Each organization lands in exactly one county. Organizations are single-row
entities here (one org, one primary location), so one that genuinely has
offices in two target counties is filed under the county of its recorded city
rather than duplicated; see :func:`route_county`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from . import geo
from .models import Organization
from .snmp_storage import SnmpCsvStorage


logger = logging.getLogger(__name__)


def county_slug(county: str) -> str:
    """``\"Hood River\"`` -> ``\"hood-river\"``; used in output file names."""
    return geo.normalize_place(county).replace(" ", "-")


def county_paths(output_dir: Path, county: str) -> dict[str, Path]:
    """Every output file for ``county``, keyed by role."""
    stem = f"{county_slug(county)}_snmp"
    return {
        "flat": output_dir / f"{stem}.csv",
        "organizations": output_dir / f"{stem}_organizations.csv",
        "locations": output_dir / f"{stem}_locations.csv",
        "jsonl": output_dir / f"{stem}.jsonl",
    }


def route_county(org: Organization, targets: Iterable[str]) -> str | None:
    """Pick which target county ``org`` belongs to, or ``None``.

    Candidates are the target counties named in the org's ``county`` cell. When
    there are several (a tri-county agency), the county of the org's own city
    wins, which is the physical-office rule the pipeline already applies. A
    candidate list with no city match falls back to its first entry, and an org
    with no stated county is placed by its city alone.
    """
    wanted = [geo.normalize_place(t) for t in targets]
    city_county = geo.normalize_place(geo.county_for_city(org.city))
    named = [
        geo.normalize_place(c)
        for c in geo.counties_in(org.county, include_also_serves=True)
    ]
    candidates = [c for c in named if c in wanted]
    if not candidates:
        return city_county if city_county in wanted else None
    if city_county in candidates:
        return city_county
    return candidates[0]


class CountySplitStorage:
    """Route organizations into per-county :class:`SnmpCsvStorage` instances."""

    def __init__(self, output_dir: Path, counties: Iterable[str]) -> None:
        self._output_dir = Path(output_dir)
        self._counties = [c for c in counties]
        self._stores: dict[str, SnmpCsvStorage] = {}
        # Created up front so a county with no organizations still produces
        # header-only files, and so a stale file from an earlier run is
        # overwritten instead of silently surviving.
        for county in self._counties:
            key = geo.normalize_place(county)
            paths = county_paths(self._output_dir, county)
            self._stores[key] = SnmpCsvStorage(
                paths["flat"],
                jsonl_path=paths["jsonl"],
                organization_table_path=paths["organizations"],
                location_table_path=paths["locations"],
            )
        self.unrouted: list[Organization] = []

    def upsert(self, org: Organization) -> None:
        county = route_county(org, self._counties)
        if county is None:
            # Scoping should make this unreachable. Keep the record visible
            # rather than filing it under a county it may not belong to.
            logger.warning(
                "no target county for %s (city=%r county=%r); not written",
                org.name,
                org.city,
                org.county,
            )
            self.unrouted.append(org)
            return
        self._stores[county].upsert(org)

    def all(self) -> list[Organization]:
        return [org for store in self._stores.values() for org in store.all()]

    def counts(self) -> dict[str, int]:
        """Organizations written per county, in the order requested."""
        return {
            county: len(self._stores[geo.normalize_place(county)].all())
            for county in self._counties
        }

    def flush(self) -> None:
        for store in self._stores.values():
            store.flush()
