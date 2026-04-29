from __future__ import annotations

from oregon_ngo_scraper.extractors.crawler import PageCrawler
from oregon_ngo_scraper.protocols import HttpResponse


def _resp(text: str, url: str) -> HttpResponse:
    return HttpResponse(status_code=200, text=text, url=url)


def test_visits_homepage_and_followups(fake_http, load_fixture) -> None:
    home_html = load_fixture("sample_home_page.html")
    about_html = load_fixture("sample_about_page.html")

    fake_http.responses["https://example.org/"] = _resp(home_html, "https://example.org/")
    fake_http.responses["https://example.org/about"] = _resp(about_html, "https://example.org/about")
    fake_http.responses["https://example.org/values"] = _resp(about_html, "https://example.org/values")

    crawler = PageCrawler(fake_http, candidate_paths=("/", "/about", "/values"), max_pages=10)
    pages = crawler.crawl("https://example.org/")

    urls = [p.url for p in pages]
    assert "https://example.org/" in urls
    assert "https://example.org/about" in urls
    assert "https://example.org/values" in urls


def test_skips_404_pages(fake_http) -> None:
    fake_http.responses["https://example.org/"] = _resp("<html><body>hi</body></html>", "https://example.org/")
    # /about returns default 404 from FakeHttpClient.

    crawler = PageCrawler(fake_http, candidate_paths=("/", "/about"))
    pages = crawler.crawl("https://example.org/")

    urls = [p.url for p in pages]
    assert urls == ["https://example.org/"]


def test_returns_empty_for_invalid_url(fake_http) -> None:
    crawler = PageCrawler(fake_http)
    assert crawler.crawl("") == []
    assert crawler.crawl("not-a-url") == []


def test_respects_robots_disallow(fake_http) -> None:
    class _DenyAll:
        def is_allowed(self, url: str, user_agent: str) -> bool:
            return False

    fake_http.responses["https://example.org/"] = _resp("<html></html>", "https://example.org/")
    crawler = PageCrawler(fake_http, robots=_DenyAll())
    assert crawler.crawl("https://example.org/") == []
