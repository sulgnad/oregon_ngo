from __future__ import annotations

from pathlib import Path

from oregon_ngo_scraper.discovery.seeds import SeedDiscovery
from oregon_ngo_scraper.models import Topic


class _FakeReader:
    def __init__(self, content: str) -> None:
        self.content = content

    def read(self, path: Path) -> str:
        return self.content


def test_loads_yaml_seeds_via_injected_reader(load_fixture) -> None:
    content = load_fixture("seed_orgs.yml")
    src = SeedDiscovery(Path("seed.yml"), reader=_FakeReader(content))

    orgs = list(src.discover())
    by_name = {o.name: o for o in orgs}

    # Bad rows (empty name, unknown topic) get skipped at parse time.
    assert "" not in by_name
    assert by_name["Bradley Angle"].topics == {Topic.DSV}
    assert by_name["Bradley Angle"].website == "https://bradleyangle.org"
    assert by_name["Street Roots"].topics == {Topic.HOUSING}
    assert by_name["Oregon Doula Association"].topics == {Topic.MATERNAL_HEALTH}
    # An entry with only an unknown topic produces an org with empty topics.
    assert by_name["Bad Topic Org"].topics == set()


def test_missing_file_yields_empty_list(tmp_path) -> None:
    src = SeedDiscovery(tmp_path / "missing.yml")
    assert list(src.discover()) == []


def test_seeded_mission_is_read_and_whitespace_collapsed() -> None:
    content = (
        "organizations:\n"
        '  - name: "Clinic"\n'
        "    mission: >-\n"
        "      Provides prenatal care\n"
        "      to county residents.\n"
    )
    org = list(SeedDiscovery(Path("s.yml"), reader=_FakeReader(content)).discover())[0]
    assert org.mission == "Provides prenatal care to county residents."


def test_mission_is_none_when_not_seeded() -> None:
    content = 'organizations:\n  - name: "Clinic"\n'
    org = list(SeedDiscovery(Path("s.yml"), reader=_FakeReader(content)).discover())[0]
    assert org.mission is None


def _one(content: str):
    return list(SeedDiscovery(Path("s.yml"), reader=_FakeReader(content)).discover())[0]


def test_agency_level_is_read_and_canonicalized() -> None:
    org = _one('organizations:\n  - name: "Clinic"\n    agency_level: "state"\n')
    assert org.agency_level == "State"


def test_agency_level_is_none_when_not_seeded() -> None:
    assert _one('organizations:\n  - name: "Clinic"\n').agency_level is None


def test_unknown_agency_level_is_dropped_with_a_warning(caplog) -> None:
    """A typo must not discard the record or the rest of the file."""
    content = (
        "organizations:\n"
        '  - name: "Clinic"\n'
        '    agency_level: "Statewide"\n'
        '  - name: "Other"\n'
    )
    with caplog.at_level("WARNING"):
        orgs = list(SeedDiscovery(Path("s.yml"), reader=_FakeReader(content)).discover())
    assert [o.name for o in orgs] == ["Clinic", "Other"]
    assert orgs[0].agency_level is None
    assert "Statewide" in caplog.text


def test_blank_mission_is_treated_as_absent() -> None:
    content = 'organizations:\n  - name: "Clinic"\n    mission: "   "\n'
    org = list(SeedDiscovery(Path("s.yml"), reader=_FakeReader(content)).discover())[0]
    assert org.mission is None
