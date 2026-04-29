"""Filesystem implementation of the ``MissionStore`` protocol.

When the extractor pulls a mission statement out of an organization's website,
the pipeline asks the ``MissionStore`` to persist that text. The store writes
a plain-text file (one per org) and returns a pointer (relative or absolute
path) that gets stored alongside the organization in the CSV/JSONL output.

Keeping mission text in dedicated ``.txt`` files makes them easy to grep,
diff against future scrapes, and feed into downstream analysis tools without
having to parse a CSV cell that may contain commas, quotes or newlines.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import Organization


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.lower()).strip("-")
    return slug or "org"


class FilesystemMissionStore:
    """Writes one mission text file per organization under ``base_dir``.

    Filenames are ``<slug>[-<ein>].txt`` so two orgs with the same name don't
    collide when the EIN is known.

    Args:
        base_dir: Directory in which to place the .txt files. Created on demand.
        path_relative_to: If provided, the pointer returned from ``write``
            is expressed relative to this directory (typically the project
            root) so the CSV stays portable across machines.
    """

    def __init__(
        self,
        base_dir: Path,
        *,
        path_relative_to: Path | None = None,
    ) -> None:
        self._base_dir = Path(base_dir)
        self._relative_to = Path(path_relative_to) if path_relative_to else None

    def write(self, org: Organization, mission: str) -> str:
        if not mission:
            raise ValueError("mission text must not be empty")
        self._base_dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify(org.name)
        if org.ein:
            filename = f"{slug}-{org.ein}.txt"
        else:
            filename = f"{slug}.txt"
        path = self._base_dir / filename
        header = self._build_header(org)
        path.write_text(header + mission.strip() + "\n", encoding="utf-8")
        return self._format_pointer(path)

    def _build_header(self, org: Organization) -> str:
        lines = [f"# {org.name}"]
        if org.website:
            lines.append(f"# Website: {org.website}")
        if org.mission_source_url:
            lines.append(f"# Source: {org.mission_source_url}")
        if org.scraped_at:
            lines.append(f"# Scraped: {org.scraped_at.isoformat()}")
        return "\n".join(lines) + "\n\n"

    def _format_pointer(self, path: Path) -> str:
        if self._relative_to is None:
            return str(path)
        try:
            return str(path.resolve().relative_to(self._relative_to.resolve()))
        except ValueError:
            return str(path)
