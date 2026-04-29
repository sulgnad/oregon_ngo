"""OCADSV (Oregon Coalition Against Domestic & Sexual Violence) discovery.

Scrapes the public Coalition Members page, which lists every member program
grouped under regional headings. Output organizations are tagged with the
``DSV`` topic.
"""

from __future__ import annotations

from typing import Iterable

from bs4 import BeautifulSoup

from ..models import Organization, Topic
from ..protocols import HttpClient
from .base import BaseDiscoverySource


COALITION_MEMBERS_URL = "https://www.ocadsv.org/about-us/coalition-members"


class OcadsvDiscovery(BaseDiscoverySource):
    """Yield DSV-tagged organizations from the OCADSV member directory."""

    name = "ocadsv"

    def __init__(self, http: HttpClient, *, url: str = COALITION_MEMBERS_URL) -> None:
        super().__init__(http)
        self._url = url

    def discover(self) -> Iterable[Organization]:
        resp = self._http.get(self._url)
        if resp.status_code >= 400:
            return []
        return list(self._parse(resp.text))

    def _parse(self, html: str) -> Iterable[Organization]:
        soup = BeautifulSoup(html, "lxml")
        # Member programs appear inside <ul> blocks following region <h4>s.
        # Be permissive: any <li> within the "member programs" region of the
        # page that has plain text and is not a navigation/sidebar item.
        seen: set[str] = set()

        # Restrict to lists that follow a region heading (h4 with "Region")
        for heading in soup.find_all(["h3", "h4"]):
            heading_text = heading.get_text(" ", strip=True).lower()
            if "region" not in heading_text and "member program" not in heading_text:
                continue
            ul = heading.find_next("ul")
            if ul is None:
                continue
            for li in ul.find_all("li"):
                name = li.get_text(" ", strip=True)
                if not name or len(name) > 200:
                    continue
                # Pull a website if the li wraps an <a>.
                link = li.find("a", href=True)
                website = link["href"] if link else None
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                yield Organization(
                    name=name,
                    website=_clean_url(website),
                    topics={Topic.DSV},
                    discovered_via=[self.name],
                    source_urls=[self._url],
                )


def _clean_url(href: str | None) -> str | None:
    if not href:
        return None
    href = href.strip()
    if href.startswith(("http://", "https://")):
        return href
    return None
