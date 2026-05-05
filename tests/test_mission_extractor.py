from __future__ import annotations

from oregon_ngo_scraper.extractors.mission import MissionExtractor
from oregon_ngo_scraper.models import FetchedPage


def _page(url: str, html: str) -> FetchedPage:
    return FetchedPage(url=url, html=html)


def test_extracts_mission_and_values_from_about_page(load_fixture) -> None:
    html = load_fixture("sample_about_page.html")
    extractor = MissionExtractor()

    result = extractor.extract([_page("https://example.org/about", html)])

    assert result.mission is not None
    assert "end domestic and sexual violence" in result.mission
    assert result.values is not None
    assert "Survivor-centered" in result.values
    assert result.source_url == "https://example.org/about"
    assert "heading_mission" in result.strategies
    assert "heading_values" in result.strategies


def test_falls_back_to_phrase_match() -> None:
    html = """
    <html><body>
    <p>Welcome to Acme Coalition. Our mission is to support survivors in
    every Oregon county. Contact us at info@acme.org.</p>
    </body></html>
    """
    extractor = MissionExtractor()
    result = extractor.extract([_page("https://acme.org/", html)])
    assert result.mission is not None
    assert result.mission.lower().startswith("our mission is")
    assert "phrase_mission" in result.strategies


def test_returns_empty_when_no_match() -> None:
    extractor = MissionExtractor()
    result = extractor.extract([_page("https://x", "<html><body>hi</body></html>")])
    assert result.mission is None
    assert result.values is None
    assert result.strategies == []


def test_values_extractor_handles_alternate_headings() -> None:
    extractor = MissionExtractor()
    for heading, expected in (
        ("Core Values", "Integrity"),
        ("Our Core Values", "Integrity"),
        ("What We Stand For", "Integrity"),
        ("Guiding Principles", "Integrity"),
        ("Our Beliefs", "Integrity"),
    ):
        html = f"""
        <html><body>
        <h2>{heading}</h2>
        <ul>
          <li>Integrity in everything we do</li>
          <li>Compassion for the communities we serve</li>
          <li>Equity is non-negotiable</li>
        </ul>
        </body></html>
        """
        result = extractor.extract([_page("https://x", html)])
        assert result.values is not None, heading
        assert expected in result.values, heading
