from datetime import datetime, timezone

import pytest

from oregon_ngo_scraper.models import Organization, Topic


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
