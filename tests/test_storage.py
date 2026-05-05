from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from oregon_ngo_scraper.models import Organization, Topic
from oregon_ngo_scraper.storage import CSV_COLUMNS, CsvStorage


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open() as f:
        return list(csv.DictReader(f))


def test_writes_csv_with_expected_columns(tmp_path: Path) -> None:
    csv_path = tmp_path / "orgs.csv"
    storage = CsvStorage(csv_path)
    storage.upsert(
        Organization(
            name="Bradley Angle",
            website="https://bradleyangle.org",
            topics={Topic.DSV},
            mission="end intimate partner violence",
            values="survivor-centered",
            mission_source_url="https://bradleyangle.org/about",
            mission_file="data/output/missions/bradley-angle.txt",
            ein="930388110",
            city="Portland",
            county="Multnomah",
            state="OR",
            keywords=["domestic violence", "LGBTQIA+"],
            notes="OCADSV member.",
            verification_status="Verified",
            discovered_via=["ocadsv", "propublica"],
            scraped_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        )
    )
    storage.flush()

    rows = _read_rows(csv_path)
    assert len(rows) == 1
    assert list(rows[0].keys()) == list(CSV_COLUMNS)
    # The mission text intentionally does NOT live in the CSV; only the
    # pointer to the .txt file does.
    assert "mission" not in rows[0]
    row = rows[0]
    assert row["name"] == "Bradley Angle"
    assert row["topics"] == "dsv"
    assert row["discovered_via"] == "ocadsv;propublica"
    assert row["mission_source_url"] == "https://bradleyangle.org/about"
    assert row["mission_file"] == "data/output/missions/bradley-angle.txt"
    assert row["county"] == "Multnomah"
    assert row["keywords"] == "domestic violence;LGBTQIA+"
    assert row["notes"] == "OCADSV member."
    assert row["verification_status"] == "Verified"
    assert row["scraped_at"] == "2026-01-02T03:04:05+00:00"


def test_dedupes_on_repeated_upsert(tmp_path: Path) -> None:
    storage = CsvStorage(tmp_path / "orgs.csv")
    storage.upsert(
        Organization(
            name="X",
            ein="1",
            topics={Topic.DSV},
            discovered_via=["a"],
        )
    )
    storage.upsert(
        Organization(
            name="X",
            ein="1",
            website="https://x.org",
            topics={Topic.HOUSING},
            discovered_via=["b"],
        )
    )
    storage.flush()
    rows = _read_rows(tmp_path / "orgs.csv")
    assert len(rows) == 1
    assert rows[0]["website"] == "https://x.org"
    assert rows[0]["topics"] == "dsv;housing"
    assert rows[0]["discovered_via"] == "a;b"


def test_writes_jsonl_sidecar_when_path_supplied(tmp_path: Path) -> None:
    csv_path = tmp_path / "orgs.csv"
    jsonl_path = tmp_path / "orgs.jsonl"
    storage = CsvStorage(csv_path, jsonl_path=jsonl_path)
    storage.upsert(Organization(name="X", topics={Topic.DSV}))
    storage.flush()

    assert jsonl_path.exists()
    line = jsonl_path.read_text().strip()
    assert '"name": "X"' in line
    assert '"dsv"' in line


def test_creates_parent_directory(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "dir" / "orgs.csv"
    storage = CsvStorage(out)
    storage.upsert(Organization(name="Z", topics={Topic.HOUSING}))
    storage.flush()
    assert out.exists()
