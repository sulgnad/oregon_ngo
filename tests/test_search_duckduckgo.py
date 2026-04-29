from __future__ import annotations

from oregon_ngo_scraper.protocols import HttpResponse
from oregon_ngo_scraper.search.duckduckgo import DDG_HTML_ENDPOINT, DuckDuckGoSearch


def test_parses_results_and_unwraps_redirects(fake_http, load_fixture) -> None:
    fake_http.responses[DDG_HTML_ENDPOINT] = HttpResponse(
        status_code=200,
        text=load_fixture("ddg_results.html"),
        url=DDG_HTML_ENDPOINT,
    )
    engine = DuckDuckGoSearch(fake_http)

    results = engine.search("Bradley Angle")

    assert len(results) == 3
    assert results[0].url == "https://bradleyangle.org/"
    assert results[1].url == "https://www.facebook.com/bradleyangle"
    assert results[2].url.startswith("https://projects.propublica.org/")


def test_returns_empty_on_http_error(fake_http) -> None:
    fake_http.responses[DDG_HTML_ENDPOINT] = HttpResponse(
        status_code=503, text="", url=DDG_HTML_ENDPOINT
    )
    engine = DuckDuckGoSearch(fake_http)
    assert engine.search("anything") == []
