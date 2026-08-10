from __future__ import annotations

import pytest

from oregon_ngo_scraper import geo


@pytest.mark.parametrize(
    ("city", "expected"),
    [
        ("Madras", "Jefferson"),
        ("madras", "Jefferson"),
        ("  Warm Springs  ", "Jefferson"),
        ("Culver", "Jefferson"),
        ("Tillamook", "Tillamook"),
        ("Rockaway Beach", "Tillamook"),
        ("Pacific City", "Tillamook"),
        ("Nehalem", "Tillamook"),
        # Outside the two target counties -> deliberately unmapped.
        ("Portland", None),
        ("Bend", None),
        ("", None),
        (None, None),
    ],
)
def test_county_for_city(city, expected) -> None:
    assert geo.county_for_city(city) == expected


def test_normalize_place_drops_county_suffix() -> None:
    assert geo.normalize_place("Tillamook County") == "tillamook"
    assert geo.normalize_place("  JEFFERSON  ") == "jefferson"


def test_parse_county_field_splits_multi_county_cells() -> None:
    primary, also = geo.parse_county_field("Deschutes / Crook / Jefferson")
    assert primary == ["Deschutes", "Crook", "Jefferson"]
    assert also == []


def test_parse_county_field_drops_non_county_qualifiers() -> None:
    # "(HQ)" is a qualifier, not a county.
    assert geo.parse_county_field("Multnomah (HQ)") == (["Multnomah"], [])
    # An em dash placeholder yields nothing rather than a bogus county.
    assert geo.parse_county_field("—") == ([], [])
    assert geo.parse_county_field("") == ([], [])


def test_parse_county_field_separates_also_serves() -> None:
    primary, also = geo.parse_county_field(
        "Wasco (also serves Sherman/Gilliam/Wheeler)"
    )
    assert primary == ["Wasco"]
    assert also == ["Sherman", "Gilliam", "Wheeler"]


def test_county_matches_handles_tri_county_strings() -> None:
    assert geo.county_matches("Deschutes / Crook / Jefferson", ["Jefferson"])
    assert not geo.county_matches("Deschutes / Crook", ["Jefferson"])
    assert geo.county_matches("Tillamook", ["jefferson", "tillamook"])
    assert not geo.county_matches("", ["Jefferson"])
    assert not geo.county_matches("Jefferson", [])


def test_county_matches_can_include_also_serves() -> None:
    value = "Wasco (also serves Sherman/Gilliam/Wheeler)"
    assert not geo.county_matches(value, ["Sherman"])
    assert geo.county_matches(value, ["Sherman"], include_also_serves=True)


def test_cities_for_county() -> None:
    assert "madras" in geo.cities_for_county("Jefferson")
    assert "nehalem" in geo.cities_for_county("tillamook county")
    assert geo.cities_for_county("Multnomah") == frozenset()


def test_find_city_extracts_from_address_text() -> None:
    text = "Madras Gospel Mission 164 SE D St Madras, OR 97741"
    assert geo.find_city(text, "Jefferson") == "Madras"


def test_find_city_prefers_longest_match() -> None:
    # "Rockaway Beach" must win over the shorter "Beaver"/"Bay City" entries.
    text = "Hope Chest Thrift Shop, 123 Main St, Rockaway Beach, OR 97136"
    assert geo.find_city(text, "Tillamook") == "Rockaway Beach"


def test_find_city_returns_none_for_other_counties() -> None:
    assert geo.find_city("123 Main St, Madras, OR", "Tillamook") is None
    assert geo.find_city("no city here", "Jefferson") is None
    assert geo.find_city(None, "Jefferson") is None
