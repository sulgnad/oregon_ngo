from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from oregon_ngo_scraper.mission_store import FilesystemMissionStore
from oregon_ngo_scraper.models import Organization


def test_writes_text_file_and_returns_pointer(tmp_path: Path) -> None:
    store = FilesystemMissionStore(tmp_path / "missions")
    org = Organization(
        name="Bradley Angle",
        ein="930388110",
        website="https://bradleyangle.org",
        mission_source_url="https://bradleyangle.org/about",
        scraped_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    )

    pointer = store.write(org, "We work to end intimate partner violence.")

    file_path = Path(pointer)
    assert file_path.exists()
    contents = file_path.read_text()
    assert "Bradley Angle" in contents
    assert "https://bradleyangle.org" in contents
    assert "https://bradleyangle.org/about" in contents
    assert "2026-01-02T03:04:05+00:00" in contents
    assert "end intimate partner violence" in contents
    # Filename includes slug + EIN to avoid collisions.
    assert file_path.name == "bradley-angle-930388110.txt"


def test_filename_uses_slug_only_when_no_ein(tmp_path: Path) -> None:
    store = FilesystemMissionStore(tmp_path / "missions")
    org = Organization(name="Street Roots")
    pointer = store.write(org, "Newspaper, advocacy, community.")
    assert Path(pointer).name == "street-roots.txt"


def test_pointer_relative_to_root_is_portable(tmp_path: Path) -> None:
    base = tmp_path / "data" / "output" / "missions"
    store = FilesystemMissionStore(base, path_relative_to=tmp_path)
    org = Organization(name="WellMama")

    pointer = store.write(org, "Perinatal mental health.")

    assert pointer == "data/output/missions/wellmama.txt"
    assert (tmp_path / pointer).exists()


def test_rejects_empty_mission(tmp_path: Path) -> None:
    store = FilesystemMissionStore(tmp_path)
    with pytest.raises(ValueError):
        store.write(Organization(name="X"), "")
