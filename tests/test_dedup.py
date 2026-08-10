from __future__ import annotations

from oregon_ngo_scraper.discovery.base import (
    apex_host,
    canonical_name,
    coalesce_duplicates,
    dedup_key,
    shares_host_with_siblings,
)
from oregon_ngo_scraper.models import Organization, OrgType, Topic


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


def test_canonical_name_drops_parenthesized_acronyms_and_connectives() -> None:
    assert canonical_name("Center for Hope and Safety") == canonical_name(
        "Center for Hope and Safety (CHS)"
    )
    assert canonical_name("Hope & Safety Alliance (formerly Womenspace)") == canonical_name(
        "Hope and Safety Alliance"
    )
    assert canonical_name("IRCO - Refugee and Immigrant Family Strengthening (RIFS)") == canonical_name(
        "IRCO -Refugee and Immigrant Family Strengthening"
    )
    # Ordinals and place names are preserved (different orgs stay separate).
    assert canonical_name("Foundation For Affordable Housing Inc") != canonical_name(
        "Foundation For Affordable Housing V Inc"
    )
    assert canonical_name("Habitat for Humanity Portland Region") != canonical_name(
        "Benton Habitat for Humanity"
    )


def test_coalesce_merges_site_keyed_with_name_only_via_canonical_name() -> None:
    """OCADSV row with no website should fold into xlsx row with the same
    canonical name (parenthesized acronyms ignored)."""
    orgs = [
        Organization(
            name="Center for Hope and Safety",
            website="https://hopeandsafety.org",
            discovered_via=["xlsx_starter"],
        ),
        Organization(
            name="Center for Hope and Safety (CHS)",
            discovered_via=["ocadsv"],
        ),
    ]
    result = coalesce_duplicates(orgs)
    assert len(result) == 1
    merged = result[0]
    assert merged.website == "https://hopeandsafety.org"
    assert "ocadsv" in merged.discovered_via
    assert "xlsx_starter" in merged.discovered_via


def test_coalesce_merges_smart_quote_variants() -> None:
    """Curly vs straight apostrophe shouldn't keep two records apart."""
    orgs = [
        Organization(name="Clackamas Women's Services (CWS)", website="https://www.cwsor.org"),
        Organization(name="Clackamas Women\u2019s Services (CWS)"),
    ]
    result = coalesce_duplicates(orgs)
    assert len(result) == 1


# --- shared-host government / tribal programs ------------------------------


def test_shares_host_with_siblings_only_for_gov_and_tribal() -> None:
    assert shares_host_with_siblings(
        Organization(name="X", org_type=OrgType.GOVERNMENT)
    )
    assert shares_host_with_siblings(
        Organization(name="X", org_type=OrgType.TRIBAL_GOVERNMENT)
    )
    assert not shares_host_with_siblings(
        Organization(name="X", org_type=OrgType.NONPROFIT)
    )
    # Default (UNKNOWN) keeps the original host-based behaviour.
    assert not shares_host_with_siblings(Organization(name="X"))


def test_dedup_key_falls_back_to_name_for_tribal_programs() -> None:
    """Warm Springs programs share one domain but are distinct orgs."""
    victims = Organization(
        name="Warm Springs Victims of Crime Services",
        website="https://warmsprings-nsn.gov/program/victims-of-crime/",
        org_type=OrgType.TRIBAL_GOVERNMENT,
    )
    housing = Organization(
        name="Warm Springs Housing Authority",
        website="https://warmsprings-nsn.gov/program/housing/",
        org_type=OrgType.TRIBAL_GOVERNMENT,
    )
    assert dedup_key(victims) != dedup_key(housing)
    assert dedup_key(victims).startswith("name:")


def test_coalesce_keeps_tribal_programs_on_one_host_separate() -> None:
    orgs = [
        Organization(
            name="Warm Springs Victims of Crime Services",
            website="https://warmsprings-nsn.gov/program/victims-of-crime/",
            topics={Topic.DSV},
            org_type=OrgType.TRIBAL_GOVERNMENT,
        ),
        Organization(
            name="Warm Springs Housing Authority",
            website="https://warmsprings-nsn.gov/program/housing/",
            topics={Topic.HOUSING},
            org_type=OrgType.TRIBAL_GOVERNMENT,
        ),
        Organization(
            name="Warm Springs Community Counseling",
            website="https://warmsprings-nsn.gov/program/counseling/",
            topics={Topic.DSV},
            org_type=OrgType.TRIBAL_GOVERNMENT,
        ),
    ]
    result = coalesce_duplicates(orgs)
    assert len(result) == 3


def test_coalesce_keeps_county_government_programs_separate() -> None:
    orgs = [
        Organization(
            name="Tillamook County Housing Commission",
            website="https://www.tillamookcounty.gov/bc-hc",
            org_type=OrgType.GOVERNMENT,
        ),
        Organization(
            name="Tillamook County Victims Assistance Program",
            website="https://www.tillamookcounty.gov/victims-assistance",
            org_type=OrgType.GOVERNMENT,
        ),
    ]
    assert len(coalesce_duplicates(orgs)) == 2


def test_gov_programs_still_merge_on_ein() -> None:
    """An explicit EIN is still authoritative regardless of org type."""
    orgs = [
        Organization(name="Program A", ein="123", org_type=OrgType.GOVERNMENT),
        Organization(name="Program A Alt", ein="123", org_type=OrgType.GOVERNMENT),
    ]
    assert len(coalesce_duplicates(orgs)) == 1


def test_nonprofit_host_dedup_is_unaffected() -> None:
    """Guard against the fix regressing the existing statewide behaviour."""
    orgs = [
        Organization(name="Tides of Change", website="https://www.tidesofchangenw.org"),
        Organization(name="Tides of Change NW", website="https://tidesofchangenw.org/about"),
    ]
    assert len(coalesce_duplicates(orgs)) == 1
