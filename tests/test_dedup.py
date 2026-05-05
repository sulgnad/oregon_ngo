from __future__ import annotations

from oregon_ngo_scraper.discovery.base import (
    apex_host,
    coalesce_duplicates,
    dedup_key,
)
from oregon_ngo_scraper.models import Organization, Topic


def test_apex_host_strips_scheme_www_and_path() -> None:
    assert apex_host("https://www.bradleyangle.org/about") == "bradleyangle.org"
    assert apex_host("http://bradleyangle.org") == "bradleyangle.org"
    assert apex_host("bradleyangle.org") == "bradleyangle.org"
    assert apex_host("bradleyangle.org/x/y") == "bradleyangle.org"
    assert apex_host("") == ""
    assert apex_host(None) == ""


def test_dedup_key_uses_apex_host_so_www_variants_collapse() -> None:
    a = Organization(name="X", website="https://www.bradleyangle.org")
    b = Organization(name="X", website="https://bradleyangle.org/about")
    assert dedup_key(a) == dedup_key(b)
    assert dedup_key(a) == "site:bradleyangle.org"


def test_coalesce_merges_orgs_sharing_apex_host() -> None:
    orgs = [
        Organization(
            name="Bradley Angle",
            website="https://www.bradleyangle.org",
            topics={Topic.DSV},
            discovered_via=["xlsx_starter"],
        ),
        Organization(
            name="Bradley Angle Inc",
            website="https://bradleyangle.org",
            ein="930388110",
            topics={Topic.DSV},
            discovered_via=["propublica"],
        ),
    ]
    result = coalesce_duplicates(orgs)
    assert len(result) == 1
    merged = result[0]
    # Topics and sources unioned, ein gained from the second record.
    assert merged.ein == "930388110"
    assert "xlsx_starter" in merged.discovered_via
    assert "propublica" in merged.discovered_via


def test_coalesce_merges_orgs_sharing_ein_even_with_different_hosts() -> None:
    orgs = [
        Organization(name="A", ein="111", website="https://a.org"),
        Organization(name="A", ein="111", website="https://aprogram.org"),
    ]
    result = coalesce_duplicates(orgs)
    assert len(result) == 1


def test_coalesce_keeps_distinct_orgs_separate() -> None:
    orgs = [
        Organization(name="Foundation For Affordable Housing Inc", ein="111"),
        Organization(name="Foundation For Affordable Housing V Inc", ein="222"),
        Organization(name="Network For Oregon Affordable Housing", ein="333"),
    ]
    result = coalesce_duplicates(orgs)
    assert len(result) == 3
