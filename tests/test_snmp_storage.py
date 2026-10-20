"""SNMP ``Map Database`` schema mapping and CSV export."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from oregon_ngo_scraper import snmp
from oregon_ngo_scraper.models import Organization, OrgType, Topic
from oregon_ngo_scraper.snmp_storage import SnmpCsvStorage


WORKBOOK = Path.home() / "Downloads" / "SNMP_Main.xlsx"


def _org(**kwargs) -> Organization:
    base = dict(name="Test Org", city="Madras", county="Jefferson")
    base.update(kwargs)
    return Organization(**base)


# --- schema fidelity --------------------------------------------------------


@pytest.mark.skipif(not WORKBOOK.exists(), reason="SNMP_Main.xlsx not available")
def test_columns_match_the_real_workbook_header() -> None:
    """Guards against drift between our tuple and the actual sheet."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(WORKBOOK, read_only=True, data_only=True)
    header = next(wb["Map Database"].iter_rows(values_only=True))
    actual = tuple(str(c) for c in header if c is not None)
    assert actual == snmp.SNMP_COLUMNS


def test_row_has_every_column() -> None:
    row = snmp.to_row(_org())
    assert set(row) == set(snmp.SNMP_OUTPUT_COLUMNS)


def test_id_columns_lead_and_do_not_pollute_the_sheet_tuple() -> None:
    """``SNMP_COLUMNS`` must keep matching the sheet even though we add keys."""
    assert snmp.SNMP_OUTPUT_COLUMNS[:2] == ("Organization_ID", "Location_ID")
    assert snmp.SNMP_OUTPUT_COLUMNS[2:] == snmp.SNMP_COLUMNS
    assert "Organization_ID" not in snmp.SNMP_COLUMNS


def test_manual_columns_are_left_blank() -> None:
    row = snmp.to_row(_org(mission="We help people.", phone="(541) 475-1234"))
    for column in snmp.MANUAL_COLUMNS:
        assert row[column] == "", column


# --- vocabulary mapping -----------------------------------------------------


def test_nonprofit_maps_to_private_city() -> None:
    row = snmp.to_row(_org(org_type=OrgType.NONPROFIT))
    assert row["Org_Agency_Type"] == "Private"
    assert row["Org_Agency_Level"] == "City"


def test_government_maps_to_public_county() -> None:
    row = snmp.to_row(_org(org_type=OrgType.GOVERNMENT))
    assert row["Org_Agency_Type"] == "Public"
    assert row["Org_Agency_Level"] == "County"


def test_tribal_government_uses_the_new_tribal_level() -> None:
    row = snmp.to_row(_org(org_type=OrgType.TRIBAL_GOVERNMENT))
    assert row["Org_Agency_Type"] == "Public"
    assert row["Org_Agency_Level"] == "Tribal"


def test_unknown_org_type_leaves_type_columns_blank() -> None:
    row = snmp.to_row(_org(org_type=OrgType.UNKNOWN))
    assert row["Org_Agency_Type"] == ""
    assert row["Org_Agency_Level"] == ""


def test_county_gains_the_county_suffix() -> None:
    assert snmp.to_row(_org(county="Jefferson"))["County"] == "Jefferson County"


def test_multi_county_value_is_passed_through() -> None:
    row = snmp.to_row(_org(county="Deschutes / Crook / Jefferson"))
    assert row["County"] == "Deschutes / Crook / Jefferson"


def test_county_suffix_is_not_doubled() -> None:
    assert snmp.to_row(_org(county="Tillamook County"))["County"] == "Tillamook County"


def test_topics_map_to_services_and_groups() -> None:
    row = snmp.to_row(_org(topics={Topic.DSV, Topic.HOUSING}))
    assert row["Primary_Resources_Services"] == (
        "Crisis Intervention & Advocacy Services, Housing & Shelter Assistance"
    )
    assert row["Primary_Groups_Served"] == (
        "Survivors of Violence, People Experiencing Homelessness"
    )


def test_topic_ordering_is_deterministic() -> None:
    """Set iteration order must not leak into the output."""
    a = snmp.to_row(_org(topics={Topic.MATERNAL_HEALTH, Topic.DSV}))
    b = snmp.to_row(_org(topics={Topic.DSV, Topic.MATERNAL_HEALTH}))
    assert a["Primary_Resources_Services"] == b["Primary_Resources_Services"]


def test_no_topics_falls_back_to_all_community_members() -> None:
    assert snmp.to_row(_org())["Primary_Groups_Served"] == "All Community Members"


def test_constant_columns() -> None:
    row = snmp.to_row(_org())
    assert row["Languages_Offered"] == "English"
    assert row["Operations_Status"] == "Normal operations"


# --- summary text -----------------------------------------------------------


def test_mission_populates_both_summary_columns() -> None:
    row = snmp.to_row(_org(mission="We  end\ndomestic violence."))
    assert row["Services_Summary"] == "We end domestic violence."
    assert row["Org_Agency_Bio"] == row["Services_Summary"]


def test_notes_are_used_when_no_mission_was_extracted() -> None:
    row = snmp.to_row(_org(notes="County warming shelter."))
    assert row["Services_Summary"] == "County warming shelter."


def test_mission_wins_over_notes() -> None:
    row = snmp.to_row(_org(mission="Mission text.", notes="Note text."))
    assert row["Services_Summary"] == "Mission text."


# --- contact columns --------------------------------------------------------


def test_contact_fields_are_written() -> None:
    row = snmp.to_row(
        _org(
            address="164 SE D St, Madras, OR 97741",
            phone="(541) 475-1234",
            email="info@example.org",
            website="https://example.org",
        )
    )
    assert row["Primary_Location_Address"] == "164 SE D St, Madras, OR 97741"
    assert row["Phone"] == "(541) 475-1234"
    assert row["Email"] == "info@example.org"
    assert row["URL"] == "https://example.org"


# --- storage ----------------------------------------------------------------


def test_flush_writes_header_and_rows(tmp_path: Path) -> None:
    storage = SnmpCsvStorage(tmp_path / "out.csv")
    storage.upsert(_org(name="Beta", website="https://beta.org"))
    storage.upsert(_org(name="Alpha", website="https://alpha.org"))
    storage.flush()

    rows = list(csv.DictReader((tmp_path / "out.csv").open()))
    assert list(rows[0]) == list(snmp.SNMP_OUTPUT_COLUMNS)
    # Sorted case-insensitively by name, matching CsvStorage.
    assert [r["Org_Agency_Name"] for r in rows] == ["Alpha", "Beta"]


def test_upsert_merges_duplicate_records(tmp_path: Path) -> None:
    storage = SnmpCsvStorage(tmp_path / "out.csv")
    storage.upsert(_org(name="Tides", website="https://tides.org"))
    storage.upsert(_org(name="Tides", website="https://tides.org", phone="(503) 842-9486"))
    storage.flush()

    rows = list(csv.DictReader((tmp_path / "out.csv").open()))
    assert len(rows) == 1
    assert rows[0]["Phone"] == "(503) 842-9486"


def test_jsonl_sidecar_keeps_fields_the_sheet_cannot_hold(tmp_path: Path) -> None:
    import json

    storage = SnmpCsvStorage(tmp_path / "out.csv", jsonl_path=tmp_path / "out.jsonl")
    storage.upsert(
        _org(name="Tides", topics={Topic.DSV}, org_type=OrgType.NONPROFIT, ein="123")
    )
    storage.flush()

    record = json.loads((tmp_path / "out.jsonl").read_text().strip())
    assert record["org_type"] == "nonprofit"
    assert record["topics"] == ["dsv"]
    assert record["ein"] == "123"


def test_sidecar_ids_join_against_the_csv(tmp_path: Path) -> None:
    import json

    storage = SnmpCsvStorage(tmp_path / "out.csv", jsonl_path=tmp_path / "out.jsonl")
    storage.upsert(_org(name="Tides", website="https://tides.org"))
    storage.flush()

    csv_row = next(iter(csv.DictReader((tmp_path / "out.csv").open())))
    record = json.loads((tmp_path / "out.jsonl").read_text().strip())
    assert record["organization_id"] == csv_row["Organization_ID"]
    assert record["location_id"] == csv_row["Location_ID"]


def test_flush_creates_missing_parent_directory(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "out.csv"
    storage = SnmpCsvStorage(target)
    storage.upsert(_org())
    storage.flush()
    assert target.exists()
