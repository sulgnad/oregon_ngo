"""Normalized ``Organization`` / ``Location`` table export.

The headers are asserted against the real workbook where it is available,
because these column names contain misspellings that are easy to "fix" by
accident and that would silently misalign a paste into the sheet.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from oregon_ngo_scraper import ids, relational
from oregon_ngo_scraper.models import Organization, OrgType, Topic
from oregon_ngo_scraper.snmp_storage import SnmpCsvStorage


WORKBOOK = Path.home() / "Downloads" / "SNMP_Main.xlsx"


def _org(**kwargs) -> Organization:
    base = dict(name="Tides of Change", city="Tillamook", county="Tillamook")
    base.update(kwargs)
    return Organization(**base)


def _storage(tmp_path: Path) -> SnmpCsvStorage:
    return SnmpCsvStorage(
        tmp_path / "flat.csv",
        organization_table_path=tmp_path / "orgs.csv",
        location_table_path=tmp_path / "locs.csv",
    )


def _rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open()))


# --- schema fidelity --------------------------------------------------------


def _workbook_header(sheet: str) -> tuple[str, ...]:
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(WORKBOOK, read_only=True, data_only=True)
    header = next(wb[sheet].iter_rows(values_only=True))
    return tuple(str(c) for c in header if c is not None)


@pytest.mark.skipif(not WORKBOOK.exists(), reason="SNMP_Main.xlsx not available")
def test_organization_columns_match_the_workbook() -> None:
    assert _workbook_header("Organization Table") == relational.ORGANIZATION_COLUMNS


@pytest.mark.skipif(not WORKBOOK.exists(), reason="SNMP_Main.xlsx not available")
def test_location_columns_match_the_workbook() -> None:
    assert _workbook_header("(Main) Location Table") == relational.LOCATION_COLUMNS


def test_workbook_misspellings_are_preserved() -> None:
    """Correcting these would misalign a paste into the existing sheets."""
    assert "organziation_description" in relational.ORGANIZATION_COLUMNS
    assert "location_adress" in relational.LOCATION_COLUMNS
    # ...while organization_name really is spelled correctly in the sheet.
    assert "organization_name" in relational.ORGANIZATION_COLUMNS


def test_rows_have_exactly_the_declared_columns() -> None:
    org = _org()
    assert set(relational.to_organization_row(org)) == set(
        relational.ORGANIZATION_COLUMNS
    )
    assert set(relational.to_location_row(org)) == set(relational.LOCATION_COLUMNS)


# --- field mapping ----------------------------------------------------------


def test_organization_row_carries_org_level_contact_details() -> None:
    row = relational.to_organization_row(
        _org(
            email="info@tides.org",
            website="https://tides.org",
            phone="(503) 842-9486",
            mission="We support survivors.",
        )
    )
    assert row["organization_name"] == "Tides of Change"
    assert row["organziation_email"] == "info@tides.org"
    assert row["organziation_website"] == "https://tides.org"
    assert row["organziation_phone"] == "(503) 842-9486"
    assert row["organziation_description"] == "We support survivors."


def test_location_row_carries_the_address() -> None:
    row = relational.to_location_row(
        _org(address="1902 Second St, Tillamook, OR 97141", phone="(503) 842-9486")
    )
    assert row["location_adress"] == "1902 Second St, Tillamook, OR 97141"
    assert row["location_phone"] == "(503) 842-9486"


def test_location_controlled_vocabulary_values() -> None:
    row = relational.to_location_row(_org())
    # Allowed values per the Codebook: Physical/Virtual/Postal, Active/Incative.
    assert row["location_type"] == "Physical"
    assert row["location_status"] == "Active"
    assert row["location_languages"] == "English"


def test_po_box_becomes_a_postal_location() -> None:
    """The Codebook's location_type allows Postal for exactly this case."""
    row = relational.to_location_row(
        _org(address="PO BOX 811, Philomath, OR 97370-0811")
    )
    assert row["location_type"] == "Postal"
    # The box is still recorded; it is only kept off the map.
    assert row["location_adress"] == "PO BOX 811, Philomath, OR 97370-0811"


def test_street_address_stays_a_physical_location() -> None:
    row = relational.to_location_row(
        _org(address="1902 Second St, Tillamook, OR 97141")
    )
    assert row["location_type"] == "Physical"


def test_missing_address_stays_physical() -> None:
    """Unknown is not the same as postal-only."""
    assert relational.to_location_row(_org())["location_type"] == "Physical"


def test_unscrapable_location_fields_are_left_blank() -> None:
    row = relational.to_location_row(
        _org(address="1902 Second St, Tillamook, OR 97141", mission="Text.")
    )
    for column in relational.MANUAL_LOCATION_COLUMNS:
        assert row[column] == "", column


def test_description_falls_back_to_notes() -> None:
    org = _org(notes="County warming shelter.")
    assert (
        relational.to_organization_row(org)["organziation_description"]
        == "County warming shelter."
    )


# --- keys and referential integrity ----------------------------------------


def test_location_foreign_key_matches_the_organization_primary_key() -> None:
    org = _org(website="https://tides.org")
    org_row = relational.to_organization_row(org)
    loc_row = relational.to_location_row(org)
    assert loc_row["organization_id"] == org_row["organization_id"]
    assert loc_row["location_id"] != loc_row["organization_id"]


def test_keys_are_the_same_guids_the_flat_export_uses() -> None:
    """The three files must be joinable on these columns."""
    org = _org(website="https://tides.org")
    assert relational.to_organization_row(org)["organization_id"] == ids.organization_id(
        org
    )
    assert relational.to_location_row(org)["location_id"] == ids.location_id(org)


# --- storage ----------------------------------------------------------------


def test_flush_writes_both_tables_with_headers(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    storage.upsert(_org(name="Beta", website="https://beta.org"))
    storage.upsert(_org(name="Alpha", website="https://alpha.org"))
    storage.flush()

    org_rows = _rows(tmp_path / "orgs.csv")
    loc_rows = _rows(tmp_path / "locs.csv")
    assert list(org_rows[0]) == list(relational.ORGANIZATION_COLUMNS)
    assert list(loc_rows[0]) == list(relational.LOCATION_COLUMNS)
    # Sorted case-insensitively by name, matching the flat export.
    assert [r["organization_name"] for r in org_rows] == ["Alpha", "Beta"]
    assert [r["location_name"] for r in loc_rows] == ["Alpha", "Beta"]


def test_every_location_resolves_to_an_organization(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    storage.upsert(_org(name="Alpha", website="https://alpha.org"))
    storage.upsert(_org(name="Beta", org_type=OrgType.GOVERNMENT, topics={Topic.DSV}))
    storage.flush()

    org_ids = {r["organization_id"] for r in _rows(tmp_path / "orgs.csv")}
    loc_fks = {r["organization_id"] for r in _rows(tmp_path / "locs.csv")}
    assert loc_fks <= org_ids
    assert len(org_ids) == 2


def test_tables_join_against_the_flat_export(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    storage.upsert(_org(name="Alpha", website="https://alpha.org"))
    storage.flush()

    flat = _rows(tmp_path / "flat.csv")[0]
    org_row = _rows(tmp_path / "orgs.csv")[0]
    loc_row = _rows(tmp_path / "locs.csv")[0]
    assert flat["Organization_ID"] == org_row["organization_id"]
    assert flat["Location_ID"] == loc_row["location_id"]


def test_merged_duplicates_produce_one_row_per_table(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    storage.upsert(_org(name="Tides", website="https://tides.org"))
    storage.upsert(
        _org(name="Tides", website="https://tides.org", phone="(503) 842-9486")
    )
    storage.flush()

    assert len(_rows(tmp_path / "orgs.csv")) == 1
    assert len(_rows(tmp_path / "locs.csv")) == 1


def test_relational_tables_are_opt_in(tmp_path: Path) -> None:
    """The statewide run passes no table paths and must not emit them."""
    storage = SnmpCsvStorage(tmp_path / "flat.csv")
    storage.upsert(_org())
    storage.flush()

    assert (tmp_path / "flat.csv").exists()
    assert list(tmp_path.glob("*.csv")) == [tmp_path / "flat.csv"]


def test_flush_creates_missing_parent_directories(tmp_path: Path) -> None:
    storage = SnmpCsvStorage(
        tmp_path / "a" / "flat.csv",
        organization_table_path=tmp_path / "b" / "orgs.csv",
        location_table_path=tmp_path / "c" / "locs.csv",
    )
    storage.upsert(_org())
    storage.flush()

    assert (tmp_path / "b" / "orgs.csv").exists()
    assert (tmp_path / "c" / "locs.csv").exists()
