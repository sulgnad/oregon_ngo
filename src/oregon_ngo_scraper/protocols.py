"""Protocol interfaces for dependency-injected collaborators.

Production implementations live alongside in ``http.py``, ``browser.py``,
``clock.py`` and ``search/``. Tests use lightweight fakes from ``conftest.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Protocol, runtime_checkable

from .models import Organization


@dataclass
class HttpResponse:
    """A minimal HTTP response shape used across the codebase."""

    status_code: int
    text: str
    url: str


@runtime_checkable
class HttpClient(Protocol):
    """Synchronous HTTP client used by every component that hits the network."""

    def get(
        self, url: str, *, timeout: float = 30.0, headers: dict[str, str] | None = None
    ) -> HttpResponse: ...


@runtime_checkable
class Browser(Protocol):
    """A headless browser able to render JavaScript-heavy pages."""

    def render(self, url: str, *, timeout: float = 30.0) -> str:
        """Return the fully rendered HTML for ``url``."""


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""


@runtime_checkable
class SearchEngine(Protocol):
    """A simple keyword search interface."""

    def search(self, query: str, *, max_results: int = 10) -> list[SearchResult]: ...


@runtime_checkable
class Clock(Protocol):
    """Time source. Injected so tests can use a frozen clock."""

    def now(self) -> datetime: ...


@runtime_checkable
class Storage(Protocol):
    """Persistence backend for the final organization records."""

    def upsert(self, org: Organization) -> None: ...

    def all(self) -> list[Organization]: ...

    def flush(self) -> None: ...


@runtime_checkable
class RobotsChecker(Protocol):
    """Used by the crawler to honour robots.txt."""

    def is_allowed(self, url: str, user_agent: str) -> bool: ...


@runtime_checkable
class DiscoverySource(Protocol):
    """A pluggable source of candidate organizations."""

    name: str

    def discover(self) -> Iterable[Organization]: ...


@runtime_checkable
class MissionStore(Protocol):
    """Persists extracted mission text to a separate file and returns a
    pointer (file path or URI) that gets stored in the database/CSV."""

    def write(self, org: Organization, mission: str) -> str: ...
