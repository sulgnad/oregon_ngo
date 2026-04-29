from __future__ import annotations

from oregon_ngo_scraper.discovery.ocadsv import (
    COALITION_MEMBERS_URL,
    OcadsvDiscovery,
)
from oregon_ngo_scraper.models import Topic
from oregon_ngo_scraper.protocols import HttpResponse


def test_parses_member_programs_grouped_by_region(fake_http, load_fixture) -> None:
    fake_http.responses[COALITION_MEMBERS_URL] = HttpResponse(
        status_code=200,
        text=load_fixture("ocadsv_members.html"),
        url=COALITION_MEMBERS_URL,
    )
    src = OcadsvDiscovery(fake_http)

    orgs = list(src.discover())
    names = [o.name for o in orgs]

    assert "SAFE of Columbia County" in names
    assert "Bradley Angle" in names
    assert "Saving Grace" in names
    # Nav <li> entries like "Home"/"About" must NOT leak in.
    assert "Home" not in names
    assert "About" not in names
    # Every org gets the DSV topic.
    assert all(o.topics == {Topic.DSV} for o in orgs)
    assert all("ocadsv" in o.discovered_via for o in orgs)


def test_extracts_website_when_anchor_present(fake_http, load_fixture) -> None:
    fake_http.responses[COALITION_MEMBERS_URL] = HttpResponse(
        status_code=200,
        text=load_fixture("ocadsv_members.html"),
        url=COALITION_MEMBERS_URL,
    )
    src = OcadsvDiscovery(fake_http)
    orgs = {o.name: o for o in src.discover()}

    assert orgs["Bradley Angle"].website == "https://bradleyangle.org"
    # Plain text item without anchor has no website.
    assert orgs["SAFE of Columbia County"].website is None


def test_returns_empty_on_http_error(fake_http) -> None:
    fake_http.responses[COALITION_MEMBERS_URL] = HttpResponse(
        status_code=500, text="", url=COALITION_MEMBERS_URL
    )
    src = OcadsvDiscovery(fake_http)
    assert list(src.discover()) == []
