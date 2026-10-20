"""Seed-file discovery source.

Reads a YAML file of hand-curated organizations. Useful for orgs that none of
the automated sources surface, or for known-good orgs we want to guarantee
appear in the run.

Schema:

    organizations:
      - name: "Bradley Angle"
        website: "https://bradleyangle.org"
        topics: ["dsv"]
        city: "Portland"
      - name: "Street Roots"
        website: "https://www.streetroots.org"
        topics: ["housing"]

Every field is optional except ``name``. County-scoped seed files also carry
``county``, ``keywords``, ``notes``, ``org_type`` and ``verification_status``;
these are hand-curated facts that no automated source reliably supplies, so
they are preserved verbatim rather than re-derived.

``mission`` is also accepted. Set it when the organization's own site yields
no usable text — a hero banner, a placeholder page, or a parent health
system's boilerplate — so the scraped value would be wrong rather than merely
absent. A seeded mission is never overwritten by the extractor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Protocol

import yaml

from ..models import Organization, OrgType, Topic


class SeedReader(Protocol):
    """Read a YAML file as a string. Injected so tests don't need a real FS."""

    def read(self, path: Path) -> str: ...


class FileSystemSeedReader:
    def read(self, path: Path) -> str:
        return Path(path).read_text(encoding="utf-8")


class SeedDiscovery:
    """Yield organizations from a YAML seed file."""

    name = "seeds"

    def __init__(
        self,
        path: Path,
        *,
        reader: SeedReader | None = None,
        name: str | None = None,
    ) -> None:
        self._path = Path(path)
        self._reader = reader or FileSystemSeedReader()
        if name:
            self.name = name

    def discover(self) -> Iterable[Organization]:
        try:
            text = self._reader.read(self._path)
        except FileNotFoundError:
            return []
        data = yaml.safe_load(text) or {}
        out: list[Organization] = []
        for raw in data.get("organizations") or []:
            org = _to_org(raw, source_url=str(self._path), via=self.name)
            if org is not None:
                out.append(org)
        return out


def _clean_text(value: object) -> str:
    """Collapse YAML folded-scalar whitespace into single spaces."""
    return " ".join(str(value).split()) if value else ""


def _to_org(raw: dict, *, source_url: str, via: str = "seeds") -> Organization | None:
    name = (raw.get("name") or "").strip()
    if not name:
        return None
    topics: set[Topic] = set()
    for t in raw.get("topics") or []:
        try:
            topics.add(Topic.from_str(str(t)))
        except ValueError:
            continue
    try:
        org_type = OrgType.from_str(str(raw.get("org_type") or "unknown"))
    except ValueError:
        org_type = OrgType.UNKNOWN
    return Organization(
        name=name,
        website=(raw.get("website") or None),
        ein=(raw.get("ein") or None),
        # Hand-verified contact details win over anything the crawler finds,
        # because merge() prefers the first non-empty value and seed sources
        # are registered ahead of the automated ones.
        address=(raw.get("address") or None),
        phone=(raw.get("phone") or None),
        email=(raw.get("email") or None),
        city=(raw.get("city") or None),
        county=(raw.get("county") or None),
        state=(raw.get("state") or "OR"),
        topics=topics,
        keywords=[str(k) for k in (raw.get("keywords") or [])],
        notes=(raw.get("notes") or None),
        org_type=org_type,
        verification_status=(raw.get("verification_status") or None),
        mission=(_clean_text(raw.get("mission")) or None),
        discovered_via=[via],
        source_urls=[source_url],
        aka=list(raw.get("aka") or []),
    )
