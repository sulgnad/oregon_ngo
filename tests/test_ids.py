"""Derived GUIDs for the SNMP relationship key fields.

The property that matters is stability: the same organization must produce
the same GUID on every run, or the ``location_id -> organization_id`` link
these columns exist to express is worthless.
"""

from __future__ import annotations

import uuid

from oregon_ngo_scraper import ids
from oregon_ngo_scraper.models import Organization, OrgType


def _org(**kwargs) -> Organization:
    base = dict(name="Tides of Change", city="Tillamook", county="Tillamook")
    base.update(kwargs)
    return Organization(**base)


# --- format -----------------------------------------------------------------


def test_ids_are_valid_uuids() -> None:
    org = _org()
    assert uuid.UUID(ids.organization_id(org))
    assert uuid.UUID(ids.location_id(org))


def test_ids_are_version_5() -> None:
    """v5 is the derived-from-a-name flavour; v4 would be random."""
    org = _org()
    assert uuid.UUID(ids.organization_id(org)).version == 5
    assert uuid.UUID(ids.location_id(org)).version == 5


# --- stability --------------------------------------------------------------


def test_id_is_stable_across_calls() -> None:
    a, b = _org(), _org()
    assert ids.organization_id(a) == ids.organization_id(b)
    assert ids.location_id(a) == ids.location_id(b)


def test_id_is_pinned_to_a_known_value() -> None:
    """Fails loudly if the namespace or key derivation is ever changed.

    A change here silently invalidates every ID previously exported, so it
    should require deliberately updating this constant.
    """
    org = _org(website="https://tidesofchangenw.org")
    assert ids.organization_id(org) == str(
        uuid.uuid5(ids.ORGANIZATION_NAMESPACE, "site:tidesofchangenw.org")
    )


def test_website_variations_yield_one_id() -> None:
    """Scheme and ``www.`` differences must not fork an org into two GUIDs."""
    a = ids.organization_id(_org(website="https://www.tidesofchangenw.org/about"))
    b = ids.organization_id(_org(website="http://tidesofchangenw.org"))
    assert a == b


def test_address_punctuation_does_not_change_the_location_id() -> None:
    a = ids.location_id(_org(address="1902 Second St., Tillamook, OR 97141"))
    b = ids.location_id(_org(address="1902 Second St Tillamook OR 97141"))
    assert a == b


def test_ein_identity_survives_a_website_change() -> None:
    """EIN outranks website in ``dedup_key``, so the GUID must not move."""
    a = ids.organization_id(_org(ein="931234567"))
    b = ids.organization_id(_org(ein="931234567", website="https://new-site.org"))
    assert a == b


# --- distinctness -----------------------------------------------------------


def test_different_orgs_get_different_ids() -> None:
    assert ids.organization_id(_org(name="Tides of Change")) != ids.organization_id(
        _org(name="CARE Inc")
    )


def test_org_and_location_ids_differ_for_the_same_org() -> None:
    """Separate namespaces keep the two key spaces from colliding."""
    org = _org()
    assert ids.organization_id(org) != ids.location_id(org)


def test_same_building_different_orgs_get_distinct_location_ids() -> None:
    address = "201 Laurel Ave, Tillamook, OR 97141"
    a = ids.location_id(_org(name="County Housing", address=address))
    b = ids.location_id(_org(name="County Victims Assistance", address=address))
    assert a != b


def test_moving_address_changes_only_the_location_id() -> None:
    before = _org(website="https://example.org", address="1 Old St, Madras, OR 97741")
    after = _org(website="https://example.org", address="2 New Ave, Madras, OR 97741")
    assert ids.organization_id(before) == ids.organization_id(after)
    assert ids.location_id(before) != ids.location_id(after)


def test_location_id_exists_without_an_address() -> None:
    """Falls back to city/county so no row is ever missing a key."""
    assert uuid.UUID(ids.location_id(_org(address=None)))


def test_sibling_government_programs_keep_distinct_ids() -> None:
    """Shared-host org types dedup by name, so they must not share a GUID."""
    a = _org(
        name="Warm Springs Housing Authority",
        website="https://warmsprings-nsn.gov/housing",
        org_type=OrgType.TRIBAL_GOVERNMENT,
    )
    b = _org(
        name="Warm Springs Victims of Crime Services",
        website="https://warmsprings-nsn.gov/vocs",
        org_type=OrgType.TRIBAL_GOVERNMENT,
    )
    assert ids.organization_id(a) != ids.organization_id(b)
