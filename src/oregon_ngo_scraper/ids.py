"""Stable GUIDs for the SNMP relationship key fields.

The workbook's relational tables use sequential string keys (``ORG_001``,
``LOC_001``). Sequential keys don't survive a scraper: rows are discovered in
whatever order the sources return them, so a counter would renumber every
organization whenever discovery output shifted, silently repointing any
``location_id -> organization_id`` link recorded from an earlier run.

Per your decision these are GUIDs instead, but *derived* ones — UUIDv5 over a
natural key rather than random UUIDv4. UUIDv5 hashes a name inside a
namespace, so the same organization always yields the same GUID: re-running
the collector, or running it on a different machine, reproduces byte-identical
IDs. Random v4 would mint new IDs on every run and break exactly the
relationships these columns exist to express.

The organization's natural key is :func:`~.discovery.base.dedup_key`, which is
already the pipeline's answer to "are these two records the same org?" —
reusing it means two records that merge during collection cannot end up with
divergent GUIDs.
"""

from __future__ import annotations

import re
import uuid

from .discovery.base import dedup_key
from .models import Organization


#: Root namespace for this project. Derived (not random) so it is reproducible
#: from source alone; the DNS name is a namespace label, not a real host.
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "snmp.oregon-ngo-scraper.invalid")

#: Separate child namespaces keep an organization key and a location key from
#: ever hashing to the same GUID.
ORGANIZATION_NAMESPACE = uuid.uuid5(NAMESPACE, "organization")
LOCATION_NAMESPACE = uuid.uuid5(NAMESPACE, "location")

_NOISE_RE = re.compile(r"[^a-z0-9]+")


def _normalize(value: str | None) -> str:
    """Lowercase and strip punctuation so cosmetic edits don't change the ID.

    ``"164 SE D St., Madras, OR 97741"`` and ``"164 SE D St Madras OR 97741"``
    describe one place and must produce one GUID.
    """
    return _NOISE_RE.sub(" ", (value or "").lower()).strip()


def organization_key(org: Organization) -> str:
    """Natural key an organization's GUID is derived from."""
    return dedup_key(org)


def location_key(org: Organization) -> str:
    """Natural key for the organization's primary location.

    Scoped by the organization key so that two organizations sharing a
    building (common for county service hubs) keep distinct location GUIDs.
    Falls back through address, then city/county, then the organization
    itself, so a row with no known address still gets a stable ID.
    """
    place = _normalize(org.address)
    if not place:
        place = _normalize(" ".join(filter(None, (org.city, org.county, org.state))))
    return f"{organization_key(org)}|{place}"


def organization_id(org: Organization) -> str:
    return str(uuid.uuid5(ORGANIZATION_NAMESPACE, organization_key(org)))


def location_id(org: Organization) -> str:
    return str(uuid.uuid5(LOCATION_NAMESPACE, location_key(org)))
