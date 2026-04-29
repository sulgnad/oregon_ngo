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
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Protocol

import yaml

from ..models import Organization, Topic


class SeedReader(Protocol):
    """Read a YAML file as a string. Injected so tests don't need a real FS."""

    def read(self, path: Path) -> str: ...


class FileSystemSeedReader:
    def read(self, path: Path) -> str:
        return Path(path).read_text(encoding="utf-8")


class SeedDiscovery:
    """Yield organizations from a YAML seed file."""

    name = "seeds"

    def __init__(self, path: Path, *, reader: SeedReader | None = None) -> None:
        self._path = Path(path)
        self._reader = reader or FileSystemSeedReader()

    def discover(self) -> Iterable[Organization]:
        try:
            text = self._reader.read(self._path)
        except FileNotFoundError:
            return []
        data = yaml.safe_load(text) or {}
        out: list[Organization] = []
        for raw in data.get("organizations") or []:
            org = _to_org(raw, source_url=str(self._path))
            if org is not None:
                out.append(org)
        return out


def _to_org(raw: dict, *, source_url: str) -> Organization | None:
    name = (raw.get("name") or "").strip()
    if not name:
        return None
    topics: set[Topic] = set()
    for t in raw.get("topics") or []:
        try:
            topics.add(Topic.from_str(str(t)))
        except ValueError:
            continue
    return Organization(
        name=name,
        website=(raw.get("website") or None),
        ein=(raw.get("ein") or None),
        city=(raw.get("city") or None),
        state=(raw.get("state") or "OR"),
        topics=topics,
        discovered_via=["seeds"],
        source_urls=[source_url],
        aka=list(raw.get("aka") or []),
    )
