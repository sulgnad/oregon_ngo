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
        ("Baker City", "Baker"),
        ("halfway", "Baker"),
        ("Sumpter", "Baker"),
        # Union County town just north of Baker; must not be claimed by Baker.
        ("North Powder", None),
        ("Corvallis", "Benton"),
        ("Philomath", "Benton"),
        # Albany is the Linn County seat; Linn is not enumerated.
        ("Albany", None),
        ("Oregon City", "Clackamas"),
        ("Lake Oswego", "Clackamas"),
        ("Happy Valley", "Clackamas"),
        ("Astoria", "Clatsop"),
        ("Cannon Beach", "Clatsop"),
        ("St. Helens", "Columbia"),
        ("St Helens", "Columbia"),
        ("Saint Helens", "Columbia"),
        ("Scappoose", "Columbia"),
        ("Coos Bay", "Coos"),
        ("North Bend", "Coos"),
        ("Bandon", "Coos"),
        # Fairview is a Multnomah County city, so Coos must not claim it.
        ("Fairview", None),
        # Outside the enumerated counties -> deliberately unmapped.
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
    assert "baker city" in geo.cities_for_county("Baker County")
    assert geo.cities_for_county("Multnomah") == frozenset()


def test_city_table_is_consistent_with_county_table() -> None:
    """Every enumerated county is a real county and no city is claimed twice."""
    assert set(geo.COUNTY_CITIES) <= geo.OREGON_COUNTIES
    seen: dict[str, str] = {}
    for county, cities in geo.COUNTY_CITIES.items():
        for city in cities:
            assert city == city.lower(), city
            assert city not in seen, f"{city} in both {seen[city]} and {county}"
            seen[city] = county


def test_ambiguous_place_names_are_not_enumerated() -> None:
    """Each of these collides with a street word or another county's town."""
    omitted = {
        "benton": {"alpine", "wren"},
        "clackamas": {"boring", "barlow"},
        "columbia": {"warren", "prescott", "quincy"},
        "coos": {"fairview"},
    }
    for county, names in omitted.items():
        assert not names & geo.COUNTY_CITIES[county], county


def test_st_helens_spelling_variants_all_resolve() -> None:
    for spelling in ("St. Helens", "St Helens", "Saint Helens", "st. helens"):
        assert geo.county_for_city(spelling) == "Columbia", spelling


def test_find_city_prefers_longest_match_for_multiword_cities() -> None:
    """``Government Camp`` and ``Oregon City`` must not be cut short."""
    text = "123 Main St, Oregon City, OR 97045"
    assert geo.find_city(text, "Clackamas") == "Oregon City"


def test_baker_omits_names_that_are_common_street_words() -> None:
    """Word-boundary matching would accept any \"Pine St\" as a Baker address."""
    assert "pine" not in geo.BAKER_CITIES
    assert "lime" not in geo.BAKER_CITIES


def test_find_city_resolves_baker_addresses() -> None:
    text = "Community Connection, 2810 Cedar St, Baker City, OR 97814"
    assert geo.find_city(text, "Baker") == "Baker City"


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
