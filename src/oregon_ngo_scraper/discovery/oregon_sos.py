"""Oregon Secretary of State nonprofit-registry discovery.

The SOS registry is an ASP.NET form that requires session cookies and a CSV
export step that varies depending on user interaction. For v1 this discovery
source consumes a CSV that the user has manually exported and dropped into
``data/seeds/oregon_sos.csv``. We then keyword-filter the names against a
topic-aware vocabulary.

This keeps the project free/keyless and avoids fighting the SOS form.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Iterable, Protocol

from ..models import Organization, Topic


# Heuristic keyword \u2192 topic map applied to the org *name*.
KEYWORD_TOPICS: dict[str, set[Topic]] = {
    "domestic violence": {Topic.DSV},
    "sexual assault": {Topic.DSV},
    "sexual violence": {Topic.DSV},
    "rape crisis": {Topic.DSV},
    "women's shelter": {Topic.DSV},
    "womens shelter": {Topic.DSV},
    "advocacy center": {Topic.DSV},
    "shelter": {Topic.HOUSING},
    "housing": {Topic.HOUSING},
    "homeless": {Topic.HOUSING},
    "habitat for humanity": {Topic.HOUSING},
    "transitional housing": {Topic.HOUSING},
    "doula": {Topic.MATERNAL_HEALTH},
    "maternal": {Topic.MATERNAL_HEALTH},
    "mothers": {Topic.MATERNAL_HEALTH},
    "pregnancy": {Topic.MATERNAL_HEALTH},
    "birth": {Topic.MATERNAL_HEALTH},
}


class CsvReader(Protocol):
    def read(self, path: Path) -> str: ...


class FileSystemCsvReader:
    def read(self, path: Path) -> str:
        return Path(path).read_text(encoding="utf-8", errors="replace")


class OregonSosDiscovery:
    """Filter a SOS export CSV by topic-relevant keywords in the name field."""

    name = "oregon_sos"

    def __init__(self, path: Path, *, reader: CsvReader | None = None) -> None:
        self._path = Path(path)
        self._reader = reader or FileSystemCsvReader()

    def discover(self) -> Iterable[Organization]:
        try:
            raw = self._reader.read(self._path)
        except FileNotFoundError:
            return []
        return list(self._iter_rows(raw))

    def _iter_rows(self, raw: str) -> Iterable[Organization]:
        reader = csv.DictReader(io.StringIO(raw))
        for row in reader:
            name = (row.get("EntityName") or row.get("Name") or "").strip()
            if not name:
                continue
            topics = _topics_for_name(name)
            if not topics:
                continue
            yield Organization(
                name=name,
                city=(row.get("Mailing City") or row.get("City") or None) or None,
                state="OR",
                topics=topics,
                discovered_via=["oregon_sos"],
                source_urls=[str(self._path)],
            )


def _topics_for_name(name: str) -> set[Topic]:
    n = name.lower()
    out: set[Topic] = set()
    for keyword, topics in KEYWORD_TOPICS.items():
        if keyword in n:
            out |= topics
    return out
