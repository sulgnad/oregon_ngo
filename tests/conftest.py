"""Shared pytest fixtures and lightweight fakes for the test suite."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pytest

from oregon_ngo_scraper.models import Organization
from oregon_ngo_scraper.protocols import HttpResponse, SearchResult


FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeHttpClient:
    """A fake HTTP client. Looks up responses by URL prefix.

    The mapping value can be either an ``HttpResponse`` or a callable that
    receives the URL and returns one (useful for tests that need to react to
    pagination params).
    """

    responses: dict[str, HttpResponse | Callable[[str], HttpResponse]] = field(
        default_factory=dict
    )
    calls: list[str] = field(default_factory=list)
    default_status: int = 404

    def get(
        self, url: str, *, timeout: float = 30.0, headers: dict | None = None
    ) -> HttpResponse:
        self.calls.append(url)
        # Prefer exact match; otherwise allow query/fragment-only differences
        # (so a registered URL matches the same URL with ``?...`` appended).
        if url in self.responses:
            value = self.responses[url]
            return value(url) if callable(value) else value
        best_prefix: str | None = None
        for prefix in self.responses:
            if not url.startswith(prefix):
                continue
            remainder = url[len(prefix):]
            if remainder and remainder[0] not in "?#":
                continue
            if best_prefix is None or len(prefix) > len(best_prefix):
                best_prefix = prefix
        if best_prefix is not None:
            value = self.responses[best_prefix]
            return value(url) if callable(value) else value
        return HttpResponse(status_code=self.default_status, text="", url=url)


@dataclass
class FakeSearchEngine:
    by_query: dict[str, list[SearchResult]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def search(self, query: str, *, max_results: int = 10) -> list[SearchResult]:
        self.calls.append(query)
        for needle, results in self.by_query.items():
            if needle in query:
                return results[:max_results]
        return []


class FixedClock:
    def __init__(self, instant: datetime | None = None) -> None:
        self._instant = instant or datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._instant


@dataclass
class FakeBrowser:
    rendered: dict[str, str] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def render(self, url: str, *, timeout: float = 30.0) -> str:
        self.calls.append(url)
        return self.rendered.get(url, "")


class InMemoryStorage:
    def __init__(self) -> None:
        self.records: list[Organization] = []
        self.flushed: int = 0

    def upsert(self, org: Organization) -> None:
        self.records.append(org)

    def all(self) -> list[Organization]:
        return list(self.records)

    def flush(self) -> None:
        self.flushed += 1


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def load_fixture(fixtures_dir: Path):
    def _load(name: str) -> str:
        return (fixtures_dir / name).read_text(encoding="utf-8")

    return _load


@pytest.fixture
def fake_http() -> FakeHttpClient:
    return FakeHttpClient()


@pytest.fixture
def fake_search() -> FakeSearchEngine:
    return FakeSearchEngine()


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock()


@pytest.fixture
def fake_browser() -> FakeBrowser:
    return FakeBrowser()


@pytest.fixture
def in_memory_storage() -> InMemoryStorage:
    return InMemoryStorage()
