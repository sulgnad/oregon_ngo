from __future__ import annotations

import pytest

from oregon_ngo_scraper.discovery.directory import (
    DirectoryConfig,
    ResourceDirectoryDiscovery,
    clean_org_name,
    infer_org_type,
    is_plausible_org_name,
    resolve_org_type,
)
from oregon_ngo_scraper.models import OrgType, Topic
from oregon_ngo_scraper.protocols import HttpResponse


DIRECTORY_URL = "https://www.protectkidsco.org/help-in-jefferson-county"


def _config(**overrides) -> DirectoryConfig:
    base = dict(
        name="jefferson_protect_kids",
        url=DIRECTORY_URL,
        county="Jefferson",
        container_selector="main",
    )
    base.update(overrides)
    return DirectoryConfig(**base)


@pytest.fixture
def orgs(fake_http, load_fixture):
    fake_http.responses[DIRECTORY_URL] = HttpResponse(
        status_code=200,
        text=load_fixture("jefferson_directory.html"),
        url=DIRECTORY_URL,
    )
    source = ResourceDirectoryDiscovery(fake_http, _config())
    return {o.name: o for o in source.discover()}


def test_extracts_orgs_from_list_sections(orgs) -> None:
    assert "Madras Gospel Misson" in orgs
    assert "Jefferson County Faith Based Network" in orgs
    assert "Saving Grace" in orgs


def test_strips_address_and_phone_from_names(orgs) -> None:
    # The source markup runs the name straight into the street address with
    # no separator: "Madras Gospel Misson164 SE D StMadras, OR 97741".
    assert "Madras Gospel Misson" in orgs
    assert all("541-" not in name for name in orgs)
    assert all("97741" not in name for name in orgs)


def test_topics_come_from_the_category_heading(orgs) -> None:
    # "Saving Grace" says nothing about DSV on its own; the heading does.
    assert orgs["Saving Grace"].topics == {Topic.DSV}
    assert Topic.HOUSING in orgs["Jefferson County Faith Based Network"].topics


def test_drops_entries_with_no_matching_topic(orgs) -> None:
    # The "Food" heading matches no topic and neither do its entries.
    assert "Jefferson County Food Bank" not in orgs
    assert "Madras Community Food Pantry" not in orgs
    # "Medical / Dental" is likewise uninformative, so a dental clinic under
    # it is dropped even though its neighbours in the same table are kept.
    assert "High Desert Dental" not in orgs


def test_parses_table_rows_and_skips_header_row(orgs) -> None:
    # Under an uninformative heading the entry's own name is the signal.
    assert "Pregnancy Resource Centers of Central Oregon" in orgs
    assert orgs["Pregnancy Resource Centers of Central Oregon"].topics == {
        Topic.MATERNAL_HEALTH
    }
    assert "Organization and Program Name" not in orgs


def test_captures_external_website_only(orgs) -> None:
    assert orgs["Saving Grace"].website == "https://saving-grace.org"
    assert (
        orgs["Jefferson County Faith Based Network"].website
        == "https://www.jcfbn.org"
    )
    # No link in the markup for this one.
    assert orgs["Madras Gospel Misson"].website is None


def test_skips_navigation_links(orgs) -> None:
    assert "Home" not in orgs
    assert "About" not in orgs
    assert "Facebook" not in orgs


def test_assigns_county_and_city(orgs) -> None:
    org = orgs["Madras Gospel Misson"]
    assert org.county == "Jefferson"
    assert org.city == "Madras"
    assert org.state == "OR"


def test_tags_tribal_and_government_org_types(orgs) -> None:
    tribal = orgs["Warm Springs Victims of Crime Services"]
    assert tribal.org_type is OrgType.TRIBAL_GOVERNMENT

    gov = orgs["Jefferson County Public Health – Healthy Families Oregon"]
    assert gov.org_type is OrgType.GOVERNMENT

    # A county-named 501(c)(3) must NOT be mistaken for government.
    assert orgs["Jefferson County Faith Based Network"].org_type is (
        OrgType.NONPROFIT
    )


def test_records_provenance(orgs) -> None:
    org = orgs["Saving Grace"]
    assert org.discovered_via == ["jefferson_protect_kids"]
    assert org.source_urls == [DIRECTORY_URL]
    assert org.notes is not None
    assert "Domestic Violence" in org.notes


def test_skip_headings_excludes_whole_sections(fake_http, load_fixture) -> None:
    fake_http.responses[DIRECTORY_URL] = HttpResponse(
        status_code=200,
        text=load_fixture("jefferson_directory.html"),
        url=DIRECTORY_URL,
    )
    source = ResourceDirectoryDiscovery(
        fake_http, _config(skip_headings=("Domestic Violence",))
    )
    names = {o.name for o in source.discover()}
    assert "Saving Grace" not in names
    assert "Madras Gospel Misson" in names


def test_extra_topics_applied_for_single_subject_pages(
    fake_http, load_fixture
) -> None:
    fake_http.responses[DIRECTORY_URL] = HttpResponse(
        status_code=200,
        text=load_fixture("jefferson_directory.html"),
        url=DIRECTORY_URL,
    )
    source = ResourceDirectoryDiscovery(
        fake_http,
        _config(extra_topics=frozenset({Topic.HOUSING}), require_topic=True),
    )
    orgs = {o.name: o for o in source.discover()}
    # The food bank now survives because every entry gets HOUSING.
    assert Topic.HOUSING in orgs["Jefferson County Food Bank"].topics


def test_returns_empty_on_http_error(fake_http) -> None:
    fake_http.responses[DIRECTORY_URL] = HttpResponse(
        status_code=503, text="", url=DIRECTORY_URL
    )
    source = ResourceDirectoryDiscovery(fake_http, _config())
    assert list(source.discover()) == []


# --- unit tests for the helpers --------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Madras Gospel Misson164 SE D StMadras, OR 97741", "Madras Gospel Misson"),
        ("Coast Kids 805-284-1707", "Coast Kids"),
        ("Animal Haven by the Sea Rescue PO Box 371", "Animal Haven by the Sea Rescue"),
        (
            "Warm Springs Housing Authority 1238 SW Veterans Way",
            "Warm Springs Housing Authority",
        ),
        ("Tides of Change", "Tides of Change"),
        ("  Spaced   Out  Name  ", "Spaced Out Name"),
        ("", ""),
    ],
)
def test_clean_org_name(raw, expected) -> None:
    assert clean_org_name(raw) == expected


def test_clean_org_name_keeps_leading_digits_in_real_names() -> None:
    # "211info" and "1st Choice" start with digits but aren't addresses.
    assert clean_org_name("211info") == "211info"
    assert clean_org_name("1st Choice Assisted Care") == "1st Choice Assisted Care"


@pytest.mark.parametrize(
    "name", ["Tides of Change", "CARE Inc", "211info"]
)
def test_is_plausible_org_name_accepts_real_names(name) -> None:
    assert is_plausible_org_name(name)


@pytest.mark.parametrize(
    "name", ["", "ab", "Home", "Read more", "https://example.org", "12345", "—"]
)
def test_is_plausible_org_name_rejects_junk(name) -> None:
    assert not is_plausible_org_name(name)


def test_infer_org_type_from_host() -> None:
    assert (
        infer_org_type("Warm Springs Housing", "https://warmsprings-nsn.gov/x")
        is OrgType.TRIBAL_GOVERNMENT
    )
    assert (
        infer_org_type("Public Health", "https://www.jeffersoncountyor.gov/a")
        is OrgType.GOVERNMENT
    )
    assert (
        infer_org_type("Tides of Change", "https://tidesofchangenw.org")
        is OrgType.NONPROFIT
    )


def test_infer_org_type_from_name_when_no_website() -> None:
    assert (
        infer_org_type("Confederated Tribes of Warm Springs", None)
        is OrgType.TRIBAL_GOVERNMENT
    )


def test_infer_org_type_does_not_treat_county_in_name_as_government() -> None:
    assert (
        infer_org_type("Tillamook County Habitat for Humanity", None)
        is OrgType.NONPROFIT
    )


def test_resolve_org_type_applies_overrides_first() -> None:
    # Jefferson County's real site is jeffco.net, which no .gov rule catches.
    overrides = (("jeffco.net", OrgType.GOVERNMENT),)
    assert (
        resolve_org_type(
            "Jefferson County Public Health",
            "https://www.jeffco.net/publichealth",
            overrides=overrides,
        )
        is OrgType.GOVERNMENT
    )
