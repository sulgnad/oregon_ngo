from datetime import datetime, timezone

import pytest

from oregon_ngo_scraper.models import Organization, OrgType, Topic


def test_topic_from_str_normalizes() -> None:
    assert Topic.from_str("DSV") is Topic.DSV
    assert Topic.from_str("maternal-health") is Topic.MATERNAL_HEALTH
    assert Topic.from_str("Maternal Health") is Topic.MATERNAL_HEALTH


def test_topic_from_str_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        Topic.from_str("not-a-topic")


def test_organization_merge_unions_topics_and_sources() -> None:
    a = Organization(
        name="Bradley Angle",
        topics={Topic.DSV},
        discovered_via=["ocadsv"],
        source_urls=["https://ocadsv.org/x"],
    )
    b = Organization(
        name="Bradley Angle",
        ein="930388110",
        topics={Topic.DSV},
        discovered_via=["propublica"],
        source_urls=["https://propublica.org/x"],
    )

    merged = a.merge(b)

    assert merged.name == "Bradley Angle"
    assert merged.ein == "930388110"
    assert merged.topics == {Topic.DSV}
    assert merged.discovered_via == ["ocadsv", "propublica"]
    assert merged.source_urls == ["https://ocadsv.org/x", "https://propublica.org/x"]


def test_organization_merge_prefers_self_for_scalars() -> None:
    a = Organization(name="X", website="https://a.org")
    b = Organization(name="X", website="https://b.org")
    assert a.merge(b).website == "https://a.org"


def test_organization_to_jsonable_serializes_datetime_and_topics() -> None:
    org = Organization(
        name="X",
        topics={Topic.DSV, Topic.HOUSING},
        scraped_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    )
    payload = org.to_jsonable()
    assert payload["topics"] == ["dsv", "housing"]
    assert payload["scraped_at"] == "2026-01-02T03:04:05+00:00"


def test_org_type_from_str_normalizes() -> None:
    assert OrgType.from_str("nonprofit") is OrgType.NONPROFIT
    assert OrgType.from_str("tribal-government") is OrgType.TRIBAL_GOVERNMENT
    assert OrgType.from_str("Tribal Government") is OrgType.TRIBAL_GOVERNMENT
    with pytest.raises(ValueError):
        OrgType.from_str("not-a-type")


def test_org_type_defaults_to_unknown() -> None:
    assert Organization(name="X").org_type is OrgType.UNKNOWN


def test_merge_takes_org_type_from_other_when_self_is_unknown() -> None:
    unknown = Organization(name="X")
    typed = Organization(name="X", org_type=OrgType.TRIBAL_GOVERNMENT)
    assert unknown.merge(typed).org_type is OrgType.TRIBAL_GOVERNMENT


def test_merge_prefers_self_org_type_when_known() -> None:
    a = Organization(name="X", org_type=OrgType.GOVERNMENT)
    b = Organization(name="X", org_type=OrgType.NONPROFIT)
    assert a.merge(b).org_type is OrgType.GOVERNMENT


def test_org_type_is_serialized_to_json() -> None:
    org = Organization(name="X", org_type=OrgType.GOVERNMENT)
    assert org.to_jsonable()["org_type"] == "government"


def test_agency_level_defaults_to_none() -> None:
    assert Organization(name="X").agency_level is None


def test_merge_prefers_self_agency_level_and_falls_back_to_other() -> None:
    seeded = Organization(name="X", agency_level="State")
    scraped = Organization(name="X", agency_level="County")
    assert seeded.merge(scraped).agency_level == "State"
    assert Organization(name="X").merge(seeded).agency_level == "State"


def test_agency_level_is_serialized_to_json() -> None:
    payload = Organization(name="X", agency_level="State").to_jsonable()
    assert payload["agency_level"] == "State"
    assert Organization(name="X").to_jsonable()["agency_level"] is None
