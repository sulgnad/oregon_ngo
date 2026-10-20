"""Storage backend that writes rows in the SNMP ``Map Database`` schema.

Implements the same ``Storage`` protocol as :class:`~.storage.CsvStorage`, so
the pipeline can swap between the project's native 15-column format and this
28-column export without any other change.

Optionally also writes the workbook's normalized ``Organization`` and
``Location`` tables (see :mod:`.relational`). All three files are produced
from one set of merged records in a single ``flush``, which is the point of
putting them here rather than in a second backend: the flat sheet and the
relational tables cannot drift apart or disagree about an ID.

The JSONL sidecar keeps the full :class:`~.models.Organization` payload
(mission text, source URLs, org_type, topics) that the flat sheet has no
column for, so nothing is lost by exporting in this format.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path

from .discovery.base import dedup_key
from .ids import location_id, organization_id
from .models import Organization
from .relational import (
    LOCATION_COLUMNS,
    ORGANIZATION_COLUMNS,
    to_location_row,
    to_organization_row,
)
from .snmp import SNMP_OUTPUT_COLUMNS, to_row


class SnmpCsvStorage:
    """Buffer organizations and write them as SNMP ``Map Database`` rows.

    Mirrors ``CsvStorage``: records coalesce through ``Organization.merge``
    on ``upsert``, and ``flush`` writes atomically via a temp file so an
    interrupted run cannot leave a half-written CSV behind.
    """

    def __init__(
        self,
        csv_path: Path,
        *,
        jsonl_path: Path | None = None,
        organization_table_path: Path | None = None,
        location_table_path: Path | None = None,
    ) -> None:
        self._csv_path = Path(csv_path)
        self._jsonl_path = Path(jsonl_path) if jsonl_path else None
        self._organization_table_path = (
            Path(organization_table_path) if organization_table_path else None
        )
        self._location_table_path = (
            Path(location_table_path) if location_table_path else None
        )
        self._records: dict[str, Organization] = {}

    def upsert(self, org: Organization) -> None:
        key = dedup_key(org)
        existing = self._records.get(key)
        self._records[key] = org if existing is None else existing.merge(org)

    def all(self) -> list[Organization]:
        return list(self._records.values())

    def flush(self) -> None:
        self._write(self._csv_path, self._write_csv)
        self._write(self._organization_table_path, self._write_organization_table)
        self._write(self._location_table_path, self._write_location_table)
        self._write(self._jsonl_path, self._write_jsonl)

    def _write(self, path: Path | None, write) -> None:
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(path, write)

    def _sorted(self) -> list[Organization]:
        return sorted(self._records.values(), key=lambda o: o.name.lower())

    def _write_csv(self, handle) -> None:
        self._write_table(handle, SNMP_OUTPUT_COLUMNS, to_row)

    def _write_organization_table(self, handle) -> None:
        self._write_table(handle, ORGANIZATION_COLUMNS, to_organization_row)

    def _write_location_table(self, handle) -> None:
        self._write_table(handle, LOCATION_COLUMNS, to_location_row)

    def _write_table(self, handle, columns, to_row_fn) -> None:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for org in self._sorted():
            writer.writerow(to_row_fn(org))

    def _write_jsonl(self, handle) -> None:
        for org in self._sorted():
            # IDs are derived rather than stored on the model, so add them here
            # to keep the sidecar joinable against the CSV.
            record = {
                "organization_id": organization_id(org),
                "location_id": location_id(org),
                **org.to_jsonable(),
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _atomic_write(self, path: Path, write) -> None:
        fd, tmp = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
                write(handle)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
