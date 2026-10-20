"""Per-county routing and the split SNMP table export."""

from __future__ import annotations

import csv
from pathlib import Path

from oregon_ngo_scraper import snmp
from oregon_ngo_scraper.county_storage import (
    CountySplitStorage,
    county_paths,
    county_slug,
    route_county,
)
from oregon_ngo_scraper.models import Organization


COUNTIES = ["Baker", "Jefferson", "Tillamook"]


def _org(**kwargs) -> Organization:
    base = dict(name="Test Org")
    base.update(kwargs)
    return Organization(**base)


def _rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open()))


# --- routing ----------------------------------------------------------------


def test_routes_by_stated_county() -> None:
    assert route_county(_org(county="Baker"), COUNTIES) == "baker"


def test_routes_by_city_when_county_is_missing() -> None:
    assert route_county(_org(city="Madras"), COUNTIES) == "jefferson"


def test_tri_county_agency_follows_its_city() -> None:
    """Physical-office rule: the Madras office files under Jefferson."""
    org = _org(county="Deschutes / Crook / Jefferson", city="Madras")
    assert route_county(org, COUNTIES) == "jefferson"


def test_multi_target_county_cell_prefers_the_city() -> None:
    org = _org(county="Baker / Jefferson", city="Madras")
    assert route_county(org, COUNTIES) == "jefferson"


def test_multi_target_county_cell_without_city_match_takes_first() -> None:
    org = _org(county="Jefferson / Baker", city="Bend")
    assert route_county(org, COUNTIES) == "jefferson"


def test_unroutable_org_returns_none() -> None:
    assert route_county(_org(county="Multnomah", city="Portland"), COUNTIES) is None
    assert route_county(_org(), COUNTIES) is None


def test_county_not_in_targets_is_not_routed() -> None:
    assert route_county(_org(county="Baker"), ["Tillamook"]) is None


# --- naming -----------------------------------------------------------------


def test_slug_handles_multiword_counties() -> None:
    assert county_slug("Hood River") == "hood-river"
    assert county_slug("Baker County") == "baker"


def test_county_paths_are_distinct_per_county(tmp_path: Path) -> None:
    baker = county_paths(tmp_path, "Baker")
    jeff = county_paths(tmp_path, "Jefferson")
    assert set(baker) == {"flat", "organizations", "locations", "jsonl"}
    assert baker["flat"].name == "baker_snmp.csv"
    assert baker["organizations"].name == "baker_snmp_organizations.csv"
    assert not set(baker.values()) & set(jeff.values())


# --- storage ----------------------------------------------------------------


def test_each_county_gets_only_its_own_rows(tmp_path: Path) -> None:
    storage = CountySplitStorage(tmp_path, COUNTIES)
    storage.upsert(_org(name="Baker Org", county="Baker", website="https://b.org"))
    storage.upsert(_org(name="Madras Org", city="Madras", website="https://m.org"))
    storage.upsert(_org(name="Tillamook Org", county="Tillamook", website="https://t.org"))
    storage.flush()

    def names(county: str) -> list[str]:
        return [
            r["Org_Agency_Name"]
            for r in _rows(county_paths(tmp_path, county)["flat"])
        ]

    assert names("Baker") == ["Baker Org"]
    assert names("Jefferson") == ["Madras Org"]
    assert names("Tillamook") == ["Tillamook Org"]


def test_all_three_tables_are_written_per_county(tmp_path: Path) -> None:
    storage = CountySplitStorage(tmp_path, ["Baker"])
    storage.upsert(_org(county="Baker", website="https://b.org"))
    storage.flush()

    paths = county_paths(tmp_path, "Baker")
    for role in ("flat", "organizations", "locations", "jsonl"):
        assert paths[role].exists(), role
    assert list(_rows(paths["flat"])[0]) == list(snmp.SNMP_OUTPUT_COLUMNS)


def test_foreign_keys_resolve_within_each_county(tmp_path: Path) -> None:
    storage = CountySplitStorage(tmp_path, COUNTIES)
    storage.upsert(_org(name="A", county="Baker", website="https://a.org"))
    storage.upsert(_org(name="B", county="Tillamook", website="https://b.org"))
    storage.flush()

    for county in ("Baker", "Tillamook"):
        paths = county_paths(tmp_path, county)
        org_ids = {r["organization_id"] for r in _rows(paths["organizations"])}
        fks = {r["organization_id"] for r in _rows(paths["locations"])}
        assert fks and fks <= org_ids


def test_empty_county_still_gets_header_only_files(tmp_path: Path) -> None:
    storage = CountySplitStorage(tmp_path, ["Baker", "Jefferson"])
    storage.upsert(_org(county="Baker", website="https://b.org"))
    storage.flush()

    jeff = county_paths(tmp_path, "Jefferson")
    assert _rows(jeff["flat"]) == []
    assert jeff["flat"].read_text().startswith("Organization_ID")


def test_stale_file_is_overwritten_by_an_empty_county(tmp_path: Path) -> None:
    jeff = county_paths(tmp_path, "Jefferson")["flat"]
    jeff.write_text("stale data from an earlier run\n")
    CountySplitStorage(tmp_path, ["Jefferson"]).flush()
    assert "stale" not in jeff.read_text()


def test_unroutable_orgs_are_reported_not_filed(tmp_path: Path) -> None:
    storage = CountySplitStorage(tmp_path, ["Baker"])
    storage.upsert(_org(name="Elsewhere", county="Multnomah", city="Portland"))
    storage.flush()

    assert [o.name for o in storage.unrouted] == ["Elsewhere"]
    assert storage.all() == []
    assert _rows(county_paths(tmp_path, "Baker")["flat"]) == []


def test_counts_follow_requested_order(tmp_path: Path) -> None:
    storage = CountySplitStorage(tmp_path, ["Tillamook", "Baker"])
    storage.upsert(_org(name="A", county="Baker", website="https://a.org"))
    assert storage.counts() == {"Tillamook": 0, "Baker": 1}


def test_duplicate_records_merge_within_a_county(tmp_path: Path) -> None:
    storage = CountySplitStorage(tmp_path, ["Baker"])
    storage.upsert(_org(name="A", county="Baker", website="https://a.org"))
    storage.upsert(
        _org(name="A", county="Baker", website="https://a.org", phone="(541) 523-0000")
    )
    storage.flush()
    rows = _rows(county_paths(tmp_path, "Baker")["flat"])
    assert len(rows) == 1
    assert rows[0]["Phone"] == "(541) 523-0000"
