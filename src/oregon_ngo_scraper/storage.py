"""Storage backends for the final ``Organization`` records."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path

from .discovery.base import dedup_key
from .models import Organization


CSV_COLUMNS = (
    "name",
    "website",
    "topics",
    "mission",
    "values",
    "mission_source_url",
    "mission_file",
    "ein",
    "city",
    "county",
    "state",
    "keywords",
    "notes",
    "verification_status",
    "discovered_via",
    "scraped_at",
)


class CsvStorage:
    """Write organization records to a CSV (with optional JSONL sidecar).

    Records are buffered in memory and merged via ``Organization.merge`` so
    repeated calls to ``upsert`` for the same org coalesce into one row. Call
    ``flush`` to atomically persist the file.
    """

    def __init__(
        self,
        csv_path: Path,
        *,
        jsonl_path: Path | None = None,
    ) -> None:
        self._csv_path = Path(csv_path)
        self._jsonl_path = Path(jsonl_path) if jsonl_path else None
        self._records: dict[str, Organization] = {}

    def upsert(self, org: Organization) -> None:
        key = dedup_key(org)
        existing = self._records.get(key)
        self._records[key] = org if existing is None else existing.merge(org)

    def all(self) -> list[Organization]:
        return list(self._records.values())

    def flush(self) -> None:
        self._csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write_csv()
        if self._jsonl_path is not None:
            self._jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write_jsonl()

    def _atomic_write_csv(self) -> None:
        fd, tmp = tempfile.mkstemp(
            prefix=self._csv_path.name + ".",
            suffix=".tmp",
            dir=str(self._csv_path.parent),
        )
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writeheader()
                for org in sorted(self._records.values(), key=lambda o: o.name.lower()):
                    writer.writerow(_to_csv_row(org))
            os.replace(tmp, self._csv_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _atomic_write_jsonl(self) -> None:
        assert self._jsonl_path is not None
        fd, tmp = tempfile.mkstemp(
            prefix=self._jsonl_path.name + ".",
            suffix=".tmp",
            dir=str(self._jsonl_path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for org in sorted(self._records.values(), key=lambda o: o.name.lower()):
                    f.write(json.dumps(org.to_jsonable(), ensure_ascii=False) + "\n")
            os.replace(tmp, self._jsonl_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def _to_csv_row(org: Organization) -> dict[str, str]:
    return {
        "name": org.name or "",
        "website": org.website or "",
        "topics": ";".join(sorted(t.value for t in org.topics)),
        "mission": (org.mission or "").replace("\n", " ").strip(),
        "values": (org.values or "").replace("\n", " ").strip(),
        "mission_source_url": org.mission_source_url or "",
        "mission_file": org.mission_file or "",
        "ein": org.ein or "",
        "city": org.city or "",
        "county": org.county or "",
        "state": org.state or "",
        "keywords": ";".join(org.keywords),
        "notes": (org.notes or "").replace("\n", " ").strip(),
        "verification_status": org.verification_status or "",
        "discovered_via": ";".join(org.discovered_via),
        "scraped_at": org.scraped_at.isoformat() if org.scraped_at else "",
    }
