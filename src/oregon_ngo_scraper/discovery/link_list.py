"""Generic discovery for "list of partner organizations" web pages.

Many coalitions publish a flat HTML page that simply lists their member
organizations as anchor tags. This module factors out that pattern:

    LinkListDiscovery(http, name="housing_alliance", url=..., topics={Topic.HOUSING})

Subclasses (``HousingAllianceDiscovery``, ``MaternalHealthDiscovery``)
parametrise the source name, URL, topic tag and an optional CSS selector that
narrows where on the page the anchor list lives.
"""

from __future__ import annotations

from typing import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..models import Organization, Topic
from ..protocols import HttpClient
from .base import BaseDiscoverySource


class LinkListDiscovery(BaseDiscoverySource):
    """Yield organizations from anchor tags on a directory-style page."""

    def __init__(
        self,
        http: HttpClient,
        *,
        name: str,
        url: str,
        topics: set[Topic],
        container_selector: str | None = "main, article, .content, body",
        skip_hosts: tuple[str, ...] = (
            "facebook.com",
            "twitter.com",
            "x.com",
            "instagram.com",
            "linkedin.com",
            "youtube.com",
            "mailto:",
            "tel:",
        ),
    ) -> None:
        super().__init__(http)
        self.name = name
        self._url = url
        self._topics = set(topics)
        self._container_selector = container_selector
        self._skip_hosts = skip_hosts

    def discover(self) -> Iterable[Organization]:
        resp = self._http.get(self._url)
        if resp.status_code >= 400:
            return []
        return list(self._parse(resp.text))

    def _parse(self, html: str) -> Iterable[Organization]:
        soup = BeautifulSoup(html, "lxml")
        scopes = (
            soup.select(self._container_selector) if self._container_selector else [soup]
        )
        scope = scopes[0] if scopes else soup
        seen: set[str] = set()
        page_host = urlparse(self._url).netloc.lower()
        for link in scope.find_all("a", href=True):
            href = link["href"].strip()
            text = link.get_text(" ", strip=True)
            if not text or len(text) < 3 or len(text) > 200:
                continue
            if any(text.lower() == kw for kw in ("home", "about", "contact", "menu")):
                continue
            if any(skip in href.lower() for skip in self._skip_hosts):
                continue
            absolute = urljoin(self._url, href)
            host = urlparse(absolute).netloc.lower()
            if not host or host == page_host:
                continue
            key = host
            if key in seen:
                continue
            seen.add(key)
            yield Organization(
                name=text,
                website=f"https://{host}",
                topics=set(self._topics),
                discovered_via=[self.name],
                source_urls=[self._url],
            )


class HousingAllianceDiscovery(LinkListDiscovery):
    """Oregon Housing Alliance member list."""

    def __init__(
        self,
        http: HttpClient,
        *,
        url: str = "https://oregonhousingalliance.org/membership/",
    ) -> None:
        super().__init__(
            http,
            name="housing_alliance",
            url=url,
            topics={Topic.HOUSING},
        )


class MaternalHealthDiscovery(LinkListDiscovery):
    """Generic maternal-health coalition partner page.

    Default URL points at the Oregon Doula Association directory; the caller
    can override ``url`` to use any other partner page.
    """

    def __init__(
        self,
        http: HttpClient,
        *,
        url: str = "https://www.oregondoulas.org/find-a-doula",
    ) -> None:
        super().__init__(
            http,
            name="maternal_health",
            url=url,
            topics={Topic.MATERNAL_HEALTH},
        )
