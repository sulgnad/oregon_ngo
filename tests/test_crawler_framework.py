from __future__ import annotations

from oregon_ngo_scraper.extractors.crawler import (
    PageCrawler,
    SITEMAP_KEYWORD_RE,
    _iter_sitemap_urls,
    _is_aggregator,
    _same_apex,
)
from oregon_ngo_scraper.protocols import HttpResponse


def _resp(text: str, url: str, status: int = 200) -> HttpResponse:
    return HttpResponse(status_code=status, text=text, url=url)


def test_same_apex_treats_www_and_non_www_equivalent():
    assert _same_apex("https://cpahousing.org", "https://www.cpahousing.org/about") is True
    assert _same_apex("https://acme.org", "https://other.org") is False
    assert _same_apex("", "https://acme.org") is False


def test_is_aggregator_blocks_known_noise_hosts():
    for host in (
        "plaincharity.com",
        "www.f990.org",
        "intellispect.co",
        "providers.healthshareoregon.org",
        "nonprofitlocator.org",
    ):
        assert _is_aggregator(host) is True, host
    assert _is_aggregator("bradleyangle.org") is False


def test_iter_sitemap_urls_parses_loc_tags_and_skips_subindex():
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset>'
        '<url><loc>https://acme.org/about</loc></url>'
        '<url><loc>https://acme.org/mission</loc></url>'
        '<url><loc>https://acme.org/extra-sitemap.xml</loc></url>'
        '</urlset>'
    )
    urls = _iter_sitemap_urls(xml)
    assert "https://acme.org/about" in urls
    assert "https://acme.org/mission" in urls
    assert not any(u.endswith(".xml") for u in urls)


def test_sitemap_keyword_re_matches_path_tokens():
    for path in (
        "/about",
        "/about-us",
        "/about-rose",
        "/our-mission",
        "/mission-values",
        "/who-we-are",
        "/whoweare",
        "/our-story",
        "/about-us/our-mission-and-values/",
        "/approach",
        "/principles",
    ):
        assert SITEMAP_KEYWORD_RE.search(path), path
    for path in ("/", "/donate", "/blog/2024-impact-report", "/contact"):
        assert not SITEMAP_KEYWORD_RE.search(path), path


def test_crawler_refuses_aggregator_homepages(fake_http):
    crawler = PageCrawler(fake_http)
    assert crawler.crawl("https://plaincharity.com") == []
    assert fake_http.calls == []


def test_crawler_uses_final_url_apex_for_same_origin_check(fake_http):
    """Homepage at acme.org returns a response.url pointing at the www
    variant; nav links to www.acme.org should still pass the same-origin
    check and be followed."""
    home_html = (
        '<html><body>'
        '<a href="https://www.acme.org/about">About</a>'
        '</body></html>'
    )
    fake_http.responses["https://acme.org/"] = _resp(
        home_html, "https://www.acme.org/"
    )
    fake_http.responses["https://www.acme.org/about"] = _resp(
        '<html><body><h2>Our Mission</h2>'
        '<p>We do important things across all of Oregon every single day.</p>'
        '</body></html>',
        "https://www.acme.org/about",
    )
    crawler = PageCrawler(fake_http, candidate_paths=("/",), max_pages=4)
    pages = crawler.crawl("https://acme.org")
    urls = [p.url for p in pages]
    assert "https://www.acme.org/about" in urls


def test_crawler_discovers_sitemap_urls_first(fake_http):
    """When the homepage has no useful nav links but /sitemap.xml lists
    /about-rose/our-mission-and-values/, the crawler picks it up."""
    sitemap_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset>'
        '<url><loc>https://rose.org/donate</loc></url>'
        '<url><loc>https://rose.org/about-rose/our-mission-and-values/</loc></url>'
        '<url><loc>https://rose.org/blog/2024-update</loc></url>'
        '</urlset>'
    )
    fake_http.responses["https://rose.org/"] = _resp(
        "<html><body><h1>Welcome</h1></body></html>", "https://rose.org/"
    )
    fake_http.responses["https://rose.org/sitemap.xml"] = _resp(
        sitemap_xml, "https://rose.org/sitemap.xml"
    )
    fake_http.responses["https://rose.org/about-rose/our-mission-and-values/"] = _resp(
        '<html><body><h2>Our Mission</h2>'
        '<p>We build housing dignity for Oregon families everywhere.</p>'
        '</body></html>',
        "https://rose.org/about-rose/our-mission-and-values/",
    )
    crawler = PageCrawler(fake_http, candidate_paths=("/",), max_pages=4)
    pages = crawler.crawl("https://rose.org")
    urls = [p.url for p in pages]
    assert "https://rose.org/about-rose/our-mission-and-values/" in urls


def test_crawler_falls_back_to_www_when_apex_404s(fake_http):
    """If the apex returns 410/404, retry with the www variant before giving up."""
    fake_http.responses["https://hopeandsafety.org/"] = _resp(
        "", "https://hopeandsafety.org/", status=410
    )
    fake_http.responses["https://www.hopeandsafety.org/"] = _resp(
        '<html><body><h1>Hope &amp; Safety</h1></body></html>',
        "https://www.hopeandsafety.org/",
    )
    crawler = PageCrawler(fake_http, candidate_paths=("/",), max_pages=2)
    pages = crawler.crawl("https://hopeandsafety.org")
    urls = [p.url for p in pages]
    assert "https://www.hopeandsafety.org/" in urls
