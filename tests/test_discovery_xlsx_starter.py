from __future__ import annotations

from pathlib import Path

from oregon_ngo_scraper.discovery.xlsx_starter import (
    XlsxStarterListDiscovery,
    parse_issue_areas,
    parse_keywords,
)
from oregon_ngo_scraper.models import Topic


class _FakeXlsxReader:
    """Returns a pre-baked list of rows for ``read_rows``."""

    def __init__(self, rows: list[list[object | None]]) -> None:
        self.rows = rows
        self.calls: list[tuple[Path, str]] = []

    def read_rows(self, path: Path, sheet: str) -> list[list[object | None]]:
        self.calls.append((path, sheet))
        return list(self.rows)


HEADER = [
    "Organization Name",
    "URL",
    "City",
    "County",
    "Issue Area(s)",
    "Keywords (preliminary)",
    "Notes",
    "Verification Status",
]


def test_parse_issue_areas_handles_multi_topic_strings() -> None:
    assert parse_issue_areas("DV/SV") == {Topic.DSV}
    assert parse_issue_areas("DV/SV; Housing") == {Topic.DSV, Topic.HOUSING}
    assert parse_issue_areas("Maternal") == {Topic.MATERNAL_HEALTH}
    assert parse_issue_areas("DV/SV; Housing; Maternal/Family") == {
        Topic.DSV,
        Topic.HOUSING,
        Topic.MATERNAL_HEALTH,
    }
    assert parse_issue_areas(None) == set()
    assert parse_issue_areas("") == set()


def test_parse_keywords_splits_semicolon_separated() -> None:
    assert parse_keywords(None) == []
    assert parse_keywords("a; b ;c") == ["a", "b", "c"]
    assert parse_keywords("a\nb;c") == ["a", "b", "c"]


def test_xlsx_discovery_maps_columns_to_fields() -> None:
    reader = _FakeXlsxReader([
        HEADER,
        [
            "Bradley Angle",
            "https://bradleyangle.org",
            "Portland",
            "Multnomah",
            "DV/SV",
            "domestic violence; LGBTQIA+ culturally-specific",
            "OCADSV member.",
            None,
        ],
        [
            "Siuslaw Outreach Services (SOS)",
            "https://www.siuslawoutreachservices.org",
            "Florence",
            "Lane",
            "DV/SV; Housing",
            "domestic violence; emergency housing",
            "OCADSV member.",
            "Verified",
        ],
        [None, None, None, None, None, None, None, None],  # blank row \u2192 skipped
    ])

    src = XlsxStarterListDiscovery(Path("starter.xlsx"), reader=reader)
    orgs = list(src.discover())

    assert [o.name for o in orgs] == [
        "Bradley Angle",
        "Siuslaw Outreach Services (SOS)",
    ]
    bradley = orgs[0]
    assert bradley.website == "https://bradleyangle.org"
    assert bradley.city == "Portland"
    assert bradley.county == "Multnomah"
    assert bradley.topics == {Topic.DSV}
    assert "domestic violence" in bradley.keywords
    assert bradley.notes == "OCADSV member."
    assert bradley.verification_status is None
    assert bradley.discovered_via == ["xlsx_starter"]

    siuslaw = orgs[1]
    assert siuslaw.topics == {Topic.DSV, Topic.HOUSING}
    assert siuslaw.verification_status == "Verified"


def test_returns_empty_when_file_missing(tmp_path: Path) -> None:
    src = XlsxStarterListDiscovery(tmp_path / "nope.xlsx")
    assert list(src.discover()) == []


def test_real_starter_list_loads(tmp_path: Path) -> None:
    """Smoke-test against the actual project starter list."""
    starter = Path(__file__).resolve().parents[1] / "data" / "seeds" / "oregon_starter_list.xlsx"
    if not starter.exists():
        return  # file not provisioned in this checkout
    src = XlsxStarterListDiscovery(starter)
    orgs = list(src.discover())
    assert len(orgs) > 80  # spec'd 94 entries
    # Every org has a name and at least one topic.
    assert all(o.name for o in orgs)
    untagged = [o for o in orgs if not o.topics]
    assert len(untagged) < 5  # tolerate a couple of edge cases
    # Counties from the README summary are present.
    counties = {o.county for o in orgs if o.county}
    assert "Lane" in counties
    assert "Multnomah" in counties
