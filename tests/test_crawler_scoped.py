"""Path-scoped crawling for pages pinned inside a shared domain.

A department page like ``county.gov/health/health.html`` is not a homepage.
Crawling it from the site root returned another department's mission, so the
crawl is confined to the page's own section, while still following that
section's navigation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from oregon_ngo_scraper.aggregators import is_noise_host
from oregon_ngo_scraper.extractors.crawler import PageCrawler, _PathScope
from oregon_ngo_scraper.models import Organization, OrgType, Topic
from oregon_ngo_scraper.pipeline import Pipeline, _is_pinned_page
from oregon_ngo_scraper.protocols import HttpResponse
from oregon_ngo_scraper.resolver import HomepageResolver
from oregon_ngo_scraper.extractors.mission import MissionExtractor
from oregon_ngo_scraper.storage import CsvStorage


SITE = "https://county.gov"
FILLER = "Lorem ipsum dolor sit amet. " * 12  # keeps pages above the JS-render heuristic


def _page(*links: tuple[str, str], body: str = "") -> str:
    anchors = "".join(f'<a href="{href}">{text}</a>' for href, text in links)
    return f"<html><body>{anchors}<p>{body or FILLER}</p></body></html>"


def _serve(fake_http, url: str, html: str, *, final_url: str | None = None) -> None:
    fake_http.responses[url] = HttpResponse(
        status_code=200, text=html, url=final_url or url
    )


def _urls(pages) -> list[str]:
    return [p.url for p in pages]


# --- scope arithmetic -------------------------------------------------------


@pytest.mark.parametrize(
    ("pinned", "inside", "outside"),
    [
        # A file scopes to its directory.
        (
            f"{SITE}/health/health.html",
            [f"{SITE}/health/health.html", f"{SITE}/health/about.html", f"{SITE}/health/wic/"],
            [f"{SITE}/", f"{SITE}/sheriff/about", f"{SITE}/healthy-living"],
        ),
        # An extensionless path is a section: itself and everything beneath.
        (
            f"{SITE}/publichealth",
            [f"{SITE}/publichealth", f"{SITE}/publichealth/", f"{SITE}/publichealth/about"],
            [f"{SITE}/", f"{SITE}/public", f"{SITE}/publichealth-archive"],
        ),
        # A trailing slash is a section too.
        (
            f"{SITE}/clinics/baker-city/",
            [f"{SITE}/clinics/baker-city", f"{SITE}/clinics/baker-city/ob"],
            [f"{SITE}/clinics/", f"{SITE}/clinics/la-grande/"],
        ),
        # A file at the top of the site has no directory: that page only.
        (
            f"{SITE}/clinic.html",
            [f"{SITE}/clinic.html"],
            [f"{SITE}/", f"{SITE}/about", f"{SITE}/clinic/about"],
        ),
    ],
)
def test_scope_membership(pinned, inside, outside) -> None:
    scope = _PathScope.from_url(pinned)
    for url in inside:
        assert scope.contains(url), url
    for url in outside:
        assert not scope.contains(url), url


def test_scope_is_per_site() -> None:
    scope = _PathScope.from_url(f"{SITE}/health/health.html")
    assert not scope.contains("https://other.org/health/about.html")


def test_scope_treats_www_and_apex_alike() -> None:
    scope = _PathScope.from_url(f"{SITE}/health/health.html")
    assert scope.contains("https://www.county.gov/health/about.html")


def test_scope_prefix_does_not_match_a_longer_sibling_name() -> None:
    """``/health/`` must not admit ``/healthcare``."""
    scope = _PathScope.from_url(f"{SITE}/health/health.html")
    assert not scope.contains(f"{SITE}/healthcare/about")


# --- navigation -------------------------------------------------------------


def test_follows_in_scope_nav_and_skips_root_and_siblings(fake_http) -> None:
    pinned = f"{SITE}/health/health.html"
    _serve(
        fake_http,
        pinned,
        _page(
            ("/health/about-us.html", "About Us"),
            ("/sheriff/about", "About the Sheriff"),
            (f"{SITE}/", "About the County"),
        ),
    )
    _serve(fake_http, f"{SITE}/health/about-us.html", _page())
    _serve(fake_http, f"{SITE}/sheriff/about", _page(body="Sheriff statement"))
    _serve(fake_http, f"{SITE}/", _page(body="County front page"))

    pages = PageCrawler(fake_http).crawl(pinned, scope_to_path=True)

    assert _urls(pages) == [pinned, f"{SITE}/health/about-us.html"]
    assert f"{SITE}/" not in fake_http.calls
    assert f"{SITE}/sheriff/about" not in fake_http.calls


def test_the_pinned_page_is_always_read_first(fake_http) -> None:
    pinned = f"{SITE}/health/health.html"
    _serve(fake_http, pinned, _page(("/health/mission", "Our Mission")))
    _serve(fake_http, f"{SITE}/health/mission", _page())
    pages = PageCrawler(fake_http).crawl(pinned, scope_to_path=True)
    assert pages[0].url == pinned


def test_extensionless_pinned_page_follows_its_own_children(fake_http) -> None:
    pinned = f"{SITE}/publichealth"
    _serve(
        fake_http,
        pinned,
        _page(("/publichealth/about", "About Us"), ("/sheriff", "About the Sheriff")),
    )
    _serve(fake_http, f"{SITE}/publichealth/about", _page())
    _serve(fake_http, f"{SITE}/sheriff", _page())

    pages = PageCrawler(fake_http).crawl(pinned, scope_to_path=True)

    assert _urls(pages) == [pinned, f"{SITE}/publichealth/about"]


def test_top_level_file_page_is_read_alone(fake_http) -> None:
    pinned = f"{SITE}/clinic.html"
    _serve(fake_http, pinned, _page(("/about", "About Us")))
    _serve(fake_http, f"{SITE}/about", _page())

    pages = PageCrawler(fake_http).crawl(pinned, scope_to_path=True)

    assert _urls(pages) == [pinned]
    assert f"{SITE}/about" not in fake_http.calls


def test_unreachable_pinned_page_yields_nothing(fake_http) -> None:
    assert PageCrawler(fake_http).crawl(f"{SITE}/gone", scope_to_path=True) == []


def test_aggregator_host_is_still_refused_when_scoped(fake_http) -> None:
    url = "https://www.guidestar.org/profile/12-3456789"
    assert PageCrawler(fake_http).crawl(url, scope_to_path=True) == []
    assert fake_http.calls == []


# --- sitemap ----------------------------------------------------------------


def test_sitemap_urls_are_confined_to_the_scope(fake_http) -> None:
    pinned = f"{SITE}/health/health.html"
    _serve(fake_http, pinned, _page(body="The department landing page. " * 6))
    _serve(
        fake_http,
        f"{SITE}/sitemap.xml",
        "<urlset>"
        f"<url><loc>{SITE}/about</loc></url>"
        f"<url><loc>{SITE}/sheriff/about</loc></url>"
        f"<url><loc>{SITE}/health/mission</loc></url>"
        "</urlset>",
    )
    _serve(fake_http, f"{SITE}/health/mission", _page(body="The department mission. " * 6))
    _serve(fake_http, f"{SITE}/about", _page(body="County about page. " * 6))

    pages = PageCrawler(fake_http).crawl(pinned, scope_to_path=True)

    assert _urls(pages) == [pinned, f"{SITE}/health/mission"]
    assert f"{SITE}/about" not in fake_http.calls


def test_out_of_scope_sitemap_urls_cannot_crowd_out_in_scope_ones(fake_http) -> None:
    """The scope filter runs before the page-budget cut-off."""
    pinned = f"{SITE}/health/health.html"
    _serve(fake_http, pinned, _page(body="The department landing page. " * 6))
    outside = "".join(
        f"<url><loc>{SITE}/other{i}/mission</loc></url>" for i in range(10)
    )
    _serve(
        fake_http,
        f"{SITE}/sitemap.xml",
        f"<urlset>{outside}<url><loc>{SITE}/health/values</loc></url></urlset>",
    )
    _serve(fake_http, f"{SITE}/health/values", _page(body="The department values. " * 6))

    pages = PageCrawler(fake_http, max_pages=3).crawl(pinned, scope_to_path=True)

    assert f"{SITE}/health/values" in _urls(pages)


# --- redirects --------------------------------------------------------------


def test_same_site_redirect_moves_the_scope_with_it(fake_http) -> None:
    pinned = f"{SITE}/health"
    _serve(
        fake_http,
        pinned,
        _page(("/health/about", "About Us"), ("/sheriff/about", "About the Sheriff")),
        final_url=f"{SITE}/health/index.html",
    )
    _serve(fake_http, f"{SITE}/health/about", _page())
    _serve(fake_http, f"{SITE}/sheriff/about", _page())

    pages = PageCrawler(fake_http).crawl(pinned, scope_to_path=True)

    assert f"{SITE}/health/about" in _urls(pages)
    assert f"{SITE}/sheriff/about" not in _urls(pages)


def test_redirect_to_the_site_root_collapses_to_the_single_page(fake_http) -> None:
    """A moved page that lands on the front page must not widen the crawl."""
    pinned = f"{SITE}/old-health-page"
    _serve(
        fake_http,
        pinned,
        _page(("/sheriff/about", "About the Sheriff")),
        final_url=f"{SITE}/",
    )
    _serve(fake_http, f"{SITE}/sheriff/about", _page())

    pages = PageCrawler(fake_http).crawl(pinned, scope_to_path=True)

    assert len(pages) == 1
    assert f"{SITE}/sheriff/about" not in fake_http.calls


# --- contact pages ----------------------------------------------------------


def test_contact_nav_is_confined_to_the_scope(fake_http) -> None:
    """The department's Contact link is followed; the county-wide one is not."""
    pinned = f"{SITE}/health/health.html"
    _serve(
        fake_http,
        pinned,
        _page(("/health/contact.html", "Contact Us"), ("/contact", "Contact the County")),
    )
    _serve(fake_http, f"{SITE}/health/contact.html", _page(body="Health: 2200 4th St"))
    _serve(fake_http, f"{SITE}/contact", _page(body="Board of Commissioners"))

    pages = PageCrawler(fake_http, include_contact_pages=True).crawl(
        pinned, scope_to_path=True
    )

    assert f"{SITE}/health/contact.html" in _urls(pages)
    assert f"{SITE}/contact" not in fake_http.calls


def test_static_contact_paths_resolve_inside_the_scope(fake_http) -> None:
    pinned = f"{SITE}/health/health.html"
    _serve(fake_http, pinned, _page())
    _serve(fake_http, f"{SITE}/health/contact", _page(body="Health: 2200 4th St"))

    pages = PageCrawler(fake_http, include_contact_pages=True).crawl(
        pinned, scope_to_path=True
    )

    assert f"{SITE}/health/contact" in _urls(pages)
    assert f"{SITE}/contact" not in fake_http.calls
    assert f"{SITE}/contact-us" not in fake_http.calls


def test_top_level_page_makes_no_static_contact_guesses(fake_http) -> None:
    """With no directory of its own there is nothing to resolve them against."""
    pinned = f"{SITE}/clinic.html"
    _serve(fake_http, pinned, _page())
    PageCrawler(fake_http, include_contact_pages=True).crawl(
        pinned, scope_to_path=True
    )
    assert f"{SITE}/contact" not in fake_http.calls


# --- fragments and soft-404 duplicates (found crawling live county sites) ---


def test_tab_fragments_do_not_become_separate_pages(fake_http) -> None:
    """``/page#tab-1`` and ``/page#tab-2`` are the same document."""
    pinned = f"{SITE}/health/health.html"
    _serve(
        fake_http,
        pinned,
        _page(
            ("#tab-1", "About Us"),
            (f"{pinned}#tab-2", "About the Program"),
            ("/health/about.html#history", "Our Story"),
        ),
    )
    _serve(fake_http, f"{SITE}/health/about.html", _page(body="The about page."))

    pages = PageCrawler(fake_http).crawl(pinned, scope_to_path=True)

    assert _urls(pages) == [pinned, f"{SITE}/health/about.html"]
    assert not any("#" in url for url in fake_http.calls)


def test_fragment_is_stripped_in_unscoped_crawls_too(fake_http) -> None:
    _serve(fake_http, f"{SITE}/", _page(("/about#team", "About Us")))
    _serve(fake_http, f"{SITE}/about", _page(body="About text"))

    PageCrawler(fake_http).crawl(f"{SITE}/")

    assert not any("#" in url for url in fake_http.calls)


def test_soft_404_copies_of_the_pinned_page_are_discarded(fake_http) -> None:
    """Some CMSes answer any unknown path under a section with the section's
    own page. Guessed contact paths must not be kept as extra pages."""
    pinned = f"{SITE}/health/health.html"
    same = _page(body="Public health department. 2200 4th St, Baker City." * 4)
    _serve(fake_http, pinned, same)
    for guess in ("contact", "contact-us", "contactus"):
        _serve(fake_http, f"{SITE}/health/{guess}", same)

    pages = PageCrawler(fake_http, include_contact_pages=True).crawl(
        pinned, scope_to_path=True
    )

    assert _urls(pages) == [pinned]


def test_soft_404_copies_do_not_use_up_the_contact_budget(fake_http) -> None:
    """A real contact page found after the copies must still be reached."""
    pinned = f"{SITE}/health/health.html"
    same = _page(body="Public health department landing page text. " * 4)
    _serve(fake_http, pinned, same)
    for guess in ("contact", "contact-us", "contactus"):
        _serve(fake_http, f"{SITE}/health/{guess}", same)
    _serve(
        fake_http,
        f"{SITE}/health/locations",
        _page(body="Our clinic is at 2200 4th St, Baker City, OR 97814." * 2),
    )

    pages = PageCrawler(
        fake_http, include_contact_pages=True, contact_page_budget=1
    ).crawl(pinned, scope_to_path=True)

    assert f"{SITE}/health/locations" in _urls(pages)


def test_identical_in_scope_page_is_collapsed_by_design(fake_http) -> None:
    """An in-scope page with exactly the same text as one already kept adds
    nothing, so it is dropped. This is deliberate, not an accident of the
    soft-404 handling: its URL is still recorded as seen and not re-fetched."""
    pinned = f"{SITE}/health/health.html"
    body = "Identical department text for both addresses. " * 5
    _serve(fake_http, pinned, _page(("/health/mirror.html", "About Us"), body=body))
    # Same visible text; the extra link text above is the only difference, so
    # give the mirror the same link text to make the two truly identical.
    _serve(fake_http, f"{SITE}/health/mirror.html", _page(("/health/mirror.html", "About Us"), body=body))

    pages = PageCrawler(fake_http).crawl(pinned, scope_to_path=True)

    assert _urls(pages) == [pinned]
    assert fake_http.calls.count(f"{SITE}/health/mirror.html") == 1


def test_distinct_short_pages_are_not_mistaken_for_duplicates(fake_http) -> None:
    """Two near-empty shells say nothing about each other."""
    pinned = f"{SITE}/health/health.html"
    _serve(fake_http, pinned, "<html><body><a href='/health/about'>About Us</a>x</body></html>")
    _serve(fake_http, f"{SITE}/health/about", "<html><body>x</body></html>")

    pages = PageCrawler(fake_http).crawl(pinned, scope_to_path=True)

    assert len(pages) == 2


# --- default behaviour is unchanged ----------------------------------------


def test_unscoped_crawl_still_starts_from_the_site_root(fake_http) -> None:
    _serve(fake_http, f"{SITE}/", _page(("/about", "About Us")))
    _serve(fake_http, f"{SITE}/about", _page())

    pages = PageCrawler(fake_http).crawl(f"{SITE}/health/health.html")

    assert _urls(pages)[0] == f"{SITE}/"
    assert f"{SITE}/health/health.html" not in fake_http.calls


# --- which orgs are pinned --------------------------------------------------


def _org(website: str | None, *, via=("seeds:baker",), org_type=OrgType.NONPROFIT):
    return Organization(
        name="Org", website=website, discovered_via=list(via), org_type=org_type
    )


def test_seeded_deep_url_is_pinned() -> None:
    assert _is_pinned_page(_org(f"{SITE}/health/health.html"))


def test_seeded_root_url_is_not_pinned() -> None:
    assert not _is_pinned_page(_org("https://noccbaker.org"))
    assert not _is_pinned_page(_org("https://noccbaker.org/"))


def test_unseeded_nonprofit_with_a_path_is_not_pinned() -> None:
    """For a resolved URL the path is an accident of search."""
    assert not _is_pinned_page(_org("https://example.org/about", via=("propublica",)))


def test_unseeded_government_org_with_a_path_is_pinned() -> None:
    """Its host is shared, so its front page speaks for the whole body."""
    org = _org(f"{SITE}/health", via=("ocadsv",), org_type=OrgType.GOVERNMENT)
    assert _is_pinned_page(org)


def test_tribal_government_with_a_path_is_pinned() -> None:
    org = _org(
        "https://tribe.gov/vocs", via=("propublica",), org_type=OrgType.TRIBAL_GOVERNMENT
    )
    assert _is_pinned_page(org)


def test_no_website_is_not_pinned() -> None:
    assert not _is_pinned_page(_org(None))


def test_merged_record_keeps_its_seed_provenance() -> None:
    """After a merge ``discovered_via`` is a union, so any seed source counts."""
    org = _org(f"{SITE}/health", via=("propublica", "seeds:baker"))
    assert _is_pinned_page(org)


def test_scheme_less_website_is_handled() -> None:
    assert _is_pinned_page(_org("county.gov/health/health.html"))
    assert not _is_pinned_page(_org("county.gov"))


# --- end to end -------------------------------------------------------------


def test_pipeline_reads_the_department_page_not_the_county_front_page(
    tmp_path: Path, fake_http, fake_search, fixed_clock
) -> None:
    """The regression behind the whole change: Public Health got the
    Detention Center's mission because the crawl started at the root."""
    pinned = f"{SITE}/publichealth"
    _serve(
        fake_http,
        pinned,
        _page(
            body=(
                "Our mission is to protect and improve the health of everyone "
                "who lives in the county through prevention and education."
            )
        ),
    )
    _serve(
        fake_http,
        f"{SITE}/",
        _page(
            body=(
                "Our mission is to operate a safe and secure detention center "
                "for the county."
            )
        ),
    )
    seeded = Organization(
        name="County Public Health",
        website=pinned,
        org_type=OrgType.GOVERNMENT,
        topics={Topic.MATERNAL_HEALTH},
        discovered_via=["seeds:county"],
    )

    class _Seed:
        name = "seeds:county"

        def discover(self):
            return [seeded]

    pipeline = Pipeline(
        sources=[_Seed()],
        resolver=HomepageResolver(fake_search),
        crawler=PageCrawler(fake_http),
        extractor=MissionExtractor(),
        storage=CsvStorage(tmp_path / "orgs.csv"),
        clock=fixed_clock,
    )
    result = pipeline.run_all()[0]

    assert f"{SITE}/" not in fake_http.calls
    assert result.mission is not None
    assert "detention" not in result.mission.lower()


def test_charityscoop_is_treated_as_an_aggregator() -> None:
    assert is_noise_host("https://charityscoop.info/org/123")
