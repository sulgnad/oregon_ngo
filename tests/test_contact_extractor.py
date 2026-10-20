"""Address / phone / email extraction from HTML."""

from __future__ import annotations

from oregon_ngo_scraper.extractors.contact import ContactExtractor
from oregon_ngo_scraper.models import FetchedPage


def _page(html: str, url: str = "https://example.org/contact") -> FetchedPage:
    return FetchedPage(url=url, html=html)


def _extract(html: str, url: str = "https://example.org/contact"):
    return ContactExtractor().extract([_page(html, url)])


# --- JSON-LD ----------------------------------------------------------------


def test_jsonld_postal_address_phone_and_email() -> None:
    html = """
    <html><head><script type="application/ld+json">
    {"@type": "NGO", "name": "Tides of Change",
     "telephone": "503-842-9486",
     "email": "INFO@Example.org",
     "address": {"@type": "PostalAddress",
                 "streetAddress": "1902 Second St",
                 "addressLocality": "Tillamook",
                 "addressRegion": "OR",
                 "postalCode": "97141"}}
    </script></head><body></body></html>
    """
    result = _extract(html)
    assert result.address == "1902 Second St, Tillamook, OR 97141"
    assert result.phone == "(503) 842-9486"
    assert result.email == "info@example.org"
    assert "jsonld_address" in result.strategies


def test_jsonld_nested_inside_graph() -> None:
    """Yoast and friends wrap nodes in an ``@graph`` array."""
    html = """
    <script type="application/ld+json">
    {"@context":"https://schema.org","@graph":[
      {"@type":"WebSite","name":"site"},
      {"@type":"Organization","telephone":"(541) 475-1234"}]}
    </script>
    """
    assert _extract(html).phone == "(541) 475-1234"


def test_malformed_jsonld_is_ignored() -> None:
    html = '<script type="application/ld+json">{not json</script><p>hi</p>'
    result = _extract(html)
    assert result.address is None and result.phone is None


# --- markup affordances -----------------------------------------------------


def test_tel_and_mailto_links() -> None:
    html = """
    <a href="tel:+15414751234">Call us</a>
    <a href="mailto:hello@example.org?subject=Hi">Email us</a>
    """
    result = _extract(html)
    assert result.phone == "(541) 475-1234"
    assert result.email == "hello@example.org"
    assert "tel_link_phone" in result.strategies


def test_address_tag() -> None:
    html = "<address>164 SE D St, Madras, OR 97741</address>"
    result = _extract(html)
    assert result.address == "164 SE D St, Madras, OR 97741"
    assert "address_tag" in result.strategies


# --- free text --------------------------------------------------------------


def test_address_and_phone_from_body_text() -> None:
    html = "<p>Visit us at 2010 Fourth Street, Tillamook, OR 97141 or call 503-842-8201.</p>"
    result = _extract(html)
    assert result.address == "2010 Fourth Street, Tillamook, OR 97141"
    assert result.phone == "(503) 842-8201"


def test_address_without_comma_before_state_is_normalized() -> None:
    html = "<p>1130 SW Hwy 97 Madras OR 97741</p>"
    assert _extract(html).address == "1130 SW Hwy 97 Madras, OR 97741"


def test_spelled_out_oregon_is_abbreviated() -> None:
    html = "<p>123 Main St, Nehalem, Oregon 97131</p>"
    assert _extract(html).address == "123 Main St, Nehalem, OR 97131"


def test_zip_plus_four_is_accepted() -> None:
    html = "<p>500 N Buff St, Madras, OR 97741-1234</p>"
    assert _extract(html).address is not None


# --- rejection --------------------------------------------------------------


def test_out_of_state_address_is_not_matched() -> None:
    """The pattern is Oregon-only by design."""
    html = "<p>123 Main St, Seattle, WA 98101</p>"
    assert _extract(html).address is None


def test_vendor_email_is_rejected() -> None:
    html = '<a href="mailto:noreply@wixpress.com">x</a>'
    assert _extract(html).email is None


def test_placeholder_phone_is_rejected() -> None:
    html = "<p>call 000-000-0000</p>"
    assert _extract(html).phone is None


def test_zip_code_is_not_mistaken_for_a_phone() -> None:
    html = "<p>Mail to PO Box 22, Warm Springs, OR 97761</p>"
    assert _extract(html).phone is None


def test_empty_pages_yield_empty_result() -> None:
    result = ContactExtractor().extract([])
    assert result.address is None
    assert result.phone is None
    assert result.email is None


# --- multi-page behaviour ---------------------------------------------------


def test_fields_accumulate_across_pages() -> None:
    """Phone from the homepage footer, address from /contact."""
    pages = [
        _page('<a href="tel:5414751234">call</a>', "https://example.org/"),
        _page("<p>164 SE D St, Madras, OR 97741</p>", "https://example.org/contact"),
    ]
    result = ContactExtractor().extract(pages)
    assert result.phone == "(541) 475-1234"
    assert result.address == "164 SE D St, Madras, OR 97741"


def test_first_page_wins_for_a_given_field() -> None:
    pages = [
        _page('<a href="tel:5414751234">a</a>', "https://example.org/"),
        _page('<a href="tel:5035550000">b</a>', "https://example.org/contact"),
    ]
    assert ContactExtractor().extract(pages).phone == "(541) 475-1234"


def test_jsonld_wins_over_body_text_on_the_same_page() -> None:
    html = """
    <script type="application/ld+json">
    {"@type":"Organization","telephone":"541-475-1111"}</script>
    <p>Old number: 541-475-9999</p>
    """
    assert _extract(html).phone == "(541) 475-1111"


# --- county-aware ranking ---------------------------------------------------


JEFFERSON = {"madras", "warm springs", "culver", "metolius"}


def test_in_county_office_beats_headquarters_listed_first() -> None:
    """A tri-county agency leads with its Bend HQ; we want the Madras office."""
    html = """
    <p>Headquarters: 1130 NW Harriman St, Bend, OR 97701</p>
    <p>Jefferson County office: 164 SE D St, Madras, OR 97741</p>
    """
    result = ContactExtractor().extract([_page(html)], cities=JEFFERSON)
    assert result.address == "164 SE D St, Madras, OR 97741"


def test_headquarters_is_left_blank_when_target_cities_are_known() -> None:
    html = "<p>1130 NW Harriman St, Bend, OR 97701</p>"
    result = ContactExtractor().extract([_page(html)], cities=JEFFERSON)
    assert result.address is None


def test_headquarters_is_used_when_no_target_cities_are_given() -> None:
    html = "<p>1130 NW Harriman St, Bend, OR 97701</p>"
    result = ContactExtractor().extract([_page(html)])
    assert result.address == "1130 NW Harriman St, Bend, OR 97701"


def test_in_county_address_outranks_an_explicit_out_of_county_one() -> None:
    """City match must beat the confidence bonus for structured markup."""
    html = """
    <address>1130 NW Harriman St, Bend, OR 97701</address>
    <p>164 SE D St, Madras, OR 97741</p>
    """
    result = ContactExtractor().extract([_page(html)], cities=JEFFERSON)
    assert result.address == "164 SE D St, Madras, OR 97741"


def test_phone_near_the_in_county_office_is_preferred() -> None:
    pages = [
        _page('<div>Bend HQ <a href="tel:5413829227">call</a></div>', "https://x.org/"),
        _page(
            '<div>Madras office <a href="tel:5414751234">call</a></div>',
            "https://x.org/contact",
        ),
    ]
    result = ContactExtractor().extract(pages, cities=JEFFERSON)
    assert result.phone == "(541) 475-1234"


# --- address quality --------------------------------------------------------


def test_number_followed_by_city_is_not_an_address() -> None:
    """``489 Tillamook, OR 97141`` is a fragment, not a street line."""
    assert _extract("<p>489 Tillamook, OR 97141</p>").address is None


def test_street_line_without_a_street_type_is_rejected() -> None:
    assert _extract("<p>413 Seaside, OR 97138</p>").address is None


def test_doubled_leading_number_is_trimmed() -> None:
    """A suite/year number preceding the street number is dropped."""
    html = "<p>1870 906 Main Ave, Tillamook, OR 97141</p>"
    assert _extract(html).address == "906 Main Ave, Tillamook, OR 97141"


def test_po_box_counts_as_a_street_line() -> None:
    html = "<p>1233 Veterans St PO Box C, Warm Springs, OR 97761</p>"
    assert _extract(html).address is not None


# --- email domain filtering -------------------------------------------------


def test_partner_email_is_rejected_when_domain_is_known() -> None:
    """Footers frequently carry a partner agency's address."""
    html = '<a href="mailto:ida@neighborhoodpartnerships.org">partner</a>'
    result = ContactExtractor().extract([_page(html)], domain="wscat.org")
    assert result.email is None


def test_own_domain_email_is_kept() -> None:
    html = '<a href="mailto:info@wscat.org">us</a>'
    result = ContactExtractor().extract([_page(html)], domain="wscat.org")
    assert result.email == "info@wscat.org"


def test_subdomain_email_is_kept() -> None:
    html = '<a href="mailto:info@mail.wscat.org">us</a>'
    result = ContactExtractor().extract([_page(html)], domain="wscat.org")
    assert result.email == "info@mail.wscat.org"


def test_freemail_is_kept_even_when_it_does_not_match_the_domain() -> None:
    """Small orgs legitimately publish a Gmail address."""
    html = '<a href="mailto:madrasgospelmission@gmail.com">us</a>'
    result = ContactExtractor().extract([_page(html)], domain="madrasgospel.org")
    assert result.email == "madrasgospelmission@gmail.com"


def test_own_domain_email_is_preferred_over_freemail() -> None:
    html = """
    <a href="mailto:volunteer@gmail.com">volunteer</a>
    <a href="mailto:info@wscat.org">office</a>
    """
    result = ContactExtractor().extract([_page(html)], domain="wscat.org")
    assert result.email == "info@wscat.org"


def test_any_email_is_accepted_when_the_domain_is_unknown() -> None:
    html = '<a href="mailto:someone@elsewhere.org">x</a>'
    assert _extract(html).email == "someone@elsewhere.org"


# --- role mailboxes ---------------------------------------------------------


def test_webmaster_mailbox_is_rejected_even_on_the_orgs_own_domain() -> None:
    """A county site footer carries webmaster@ on every page."""
    html = '<a href="mailto:webmaster@bakercountyor.gov">Contact webmaster</a>'
    result = ContactExtractor().extract([_page(html)], domain="bakercountyor.gov")
    assert result.email is None


def test_real_contact_beats_the_webmaster_footer_link() -> None:
    html = """
    <a href="mailto:webmaster@bakercountyor.gov">webmaster</a>
    <a href="mailto:health@bakercountyor.gov">Health Department</a>
    """
    result = ContactExtractor().extract([_page(html)], domain="bakercountyor.gov")
    assert result.email == "health@bakercountyor.gov"


def test_other_role_mailboxes_are_rejected() -> None:
    for local in ("postmaster", "hostmaster", "abuse", "noreply", "no-reply", "donotreply"):
        html = f'<a href="mailto:{local}@example.org">x</a>'
        assert _extract(html).email is None, local


def test_info_and_admin_mailboxes_are_still_accepted() -> None:
    """For small orgs these are often the one real contact address."""
    assert _extract('<a href="mailto:info@example.org">x</a>').email == "info@example.org"
    assert _extract('<a href="mailto:admin@example.org">x</a>').email == "admin@example.org"


def test_role_filter_matches_the_whole_local_part_only() -> None:
    """``webmaster.jane`` is a person, not the role mailbox."""
    html = '<a href="mailto:abuse.prevention@example.org">x</a>'
    assert _extract(html).email == "abuse.prevention@example.org"
