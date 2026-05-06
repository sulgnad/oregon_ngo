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
        ("Our Approach", "Integrity"),
        ("Our Promise", "Integrity"),
        ("Our Pillars", "Integrity"),
        ("Vision and Values", "Integrity"),
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


def test_values_extractor_phrase_scan_with_following_list() -> None:
    """Inline values: "We believe in:" intro followed by a <ul>."""
    html = """
    <html><body>
    <h1>About Us</h1>
    <p>Acme builds homes for Oregon families. We believe in dignity, equity, and community.</p>
    <ul>
      <li>Dignity for every neighbor</li>
      <li>Equity in housing access</li>
      <li>Community-driven solutions</li>
    </ul>
    </body></html>
    """
    result = MissionExtractor().extract([_page("https://acme.org/", html)])
    assert result.values is not None
    assert "Dignity" in result.values
    assert "phrase_values" in result.strategies


def test_values_extractor_phrase_only_no_list() -> None:
    html = """
    <html><body>
    <p>We are committed to ending homelessness through housing-first policies and community partnership.</p>
    </body></html>
    """
    result = MissionExtractor().extract([_page("https://x", html)])
    assert result.values is not None
    assert "committed to" in result.values.lower()


def test_mission_falls_back_to_og_description_when_nothing_else_fires() -> None:
    html = """
    <html><head>
      <meta property="og:description" content="Acme Coalition is an Oregon nonprofit serving survivors of intimate partner violence statewide.">
    </head><body>
      <p>Welcome to the site.</p>
    </body></html>
    """
    result = MissionExtractor().extract([_page("https://acme.org/", html)])
    assert result.mission is not None
    assert "Acme Coalition" in result.mission
    assert "og_description_mission" in result.strategies
