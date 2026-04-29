"""Discovery source for the Voices Project Oregon Starter List spreadsheet.

The starter list is the project's canonical hand-curated input. The expected
schema (sheet ``Organizations``) is::

    Organization Name | URL | City | County | Issue Area(s) | Keywords | Notes | Verification Status

Issue area strings are free-form (e.g. ``"DV/SV; Housing"``); we map their
substrings to ``Topic`` values.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

from ..models import Organization, Topic


@dataclass
class _SheetRow:
    name: str
    url: str | None
    city: str | None
    county: str | None
    issue_areas: str | None
    keywords: str | None
    notes: str | None
    verification_status: str | None


class XlsxWorkbookReader(Protocol):
    """Read an .xlsx file and return rows for the target sheet.

    Returning rows as ``list[list[str | None]]`` decouples discovery code
    from openpyxl so tests can inject a tiny dict-of-rows fake without ever
    touching the disk.
    """

    def read_rows(self, path: Path, sheet: str) -> list[list[object | None]]: ...


class OpenpyxlWorkbookReader:
    """Production reader backed by ``openpyxl``."""

    def read_rows(self, path: Path, sheet: str) -> list[list[object | None]]:
        # Local import keeps ``openpyxl`` optional for callers that only run
        # the YAML / web-based discovery sources.
        import openpyxl  # type: ignore[import-not-found]

        wb = openpyxl.load_workbook(filename=str(path), data_only=True, read_only=True)
        try:
            ws = wb[sheet]
            return [list(row) for row in ws.iter_rows(values_only=True)]
        finally:
            wb.close()


# Substring -> Topic mapping applied to the "Issue Area(s)" column.
_ISSUE_AREA_TOPICS: tuple[tuple[str, Topic], ...] = (
    ("dv/sv", Topic.DSV),
    ("dv", Topic.DSV),
    ("sv", Topic.DSV),
    ("domestic", Topic.DSV),
    ("sexual", Topic.DSV),
    ("housing", Topic.HOUSING),
    ("shelter", Topic.HOUSING),
    ("maternal", Topic.MATERNAL_HEALTH),
    ("perinatal", Topic.MATERNAL_HEALTH),
    ("doula", Topic.MATERNAL_HEALTH),
    ("family", Topic.MATERNAL_HEALTH),
)


def parse_issue_areas(value: str | None) -> set[Topic]:
    """Map a free-form issue-area cell to one or more ``Topic`` values."""
    if not value:
        return set()
    s = value.lower()
    out: set[Topic] = set()
    for needle, topic in _ISSUE_AREA_TOPICS:
        if needle in s:
            out.add(topic)
    return out


def parse_keywords(value: str | None) -> list[str]:
    if not value:
        return []
    parts = [p.strip() for p in str(value).replace("\n", ";").split(";")]
    return [p for p in parts if p]


class XlsxStarterListDiscovery:
    """Yield organizations from the Voices Project starter spreadsheet."""

    name = "xlsx_starter"

    def __init__(
        self,
        path: Path,
        *,
        sheet: str = "Organizations",
        reader: XlsxWorkbookReader | None = None,
    ) -> None:
        self._path = Path(path)
        self._sheet = sheet
        self._reader = reader or OpenpyxlWorkbookReader()

    def discover(self) -> Iterable[Organization]:
        try:
            rows = self._reader.read_rows(self._path, self._sheet)
        except FileNotFoundError:
            return []
        if not rows:
            return []

        header = [_norm(c) for c in rows[0]]
        idx = _column_indices(header)
        if idx["name"] is None:
            return []

        out: list[Organization] = []
        for raw in rows[1:]:
            record = self._row_to_record(raw, idx)
            if record is None:
                continue
            org = self._record_to_org(record)
            if org is not None:
                out.append(org)
        return out

    def _row_to_record(self, raw: list[object | None], idx: dict[str, int | None]) -> _SheetRow | None:
        def cell(key: str) -> str | None:
            i = idx.get(key)
            if i is None or i >= len(raw):
                return None
            value = raw[i]
            if value is None:
                return None
            text = str(value).strip()
            return text or None

        name = cell("name")
        if not name:
            return None
        return _SheetRow(
            name=name,
            url=cell("url"),
            city=cell("city"),
            county=cell("county"),
            issue_areas=cell("issue_areas"),
            keywords=cell("keywords"),
            notes=cell("notes"),
            verification_status=cell("verification_status"),
        )

    def _record_to_org(self, row: _SheetRow) -> Organization | None:
        topics = parse_issue_areas(row.issue_areas)
        return Organization(
            name=row.name,
            website=row.url,
            city=row.city,
            county=row.county,
            state="OR",
            topics=topics,
            keywords=parse_keywords(row.keywords),
            notes=row.notes,
            verification_status=row.verification_status,
            discovered_via=[self.name],
            source_urls=[str(self._path)],
        )


# --- helpers ----------------------------------------------------------------


def _norm(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("organization name", "name", "org", "organization"),
    "url": ("url", "website"),
    "city": ("city",),
    "county": ("county",),
    "issue_areas": ("issue area(s)", "issue area", "issue areas", "topics"),
    "keywords": ("keywords (preliminary)", "keywords"),
    "notes": ("notes",),
    "verification_status": ("verification status", "status"),
}


def _column_indices(header: list[str]) -> dict[str, int | None]:
    indices: dict[str, int | None] = {key: None for key in _HEADER_ALIASES}
    for col, cell in enumerate(header):
        for key, aliases in _HEADER_ALIASES.items():
            if cell in aliases and indices[key] is None:
                indices[key] = col
    return indices
