"""ProPublica Nonprofit Explorer discovery.

Uses the free, keyless ProPublica API to list Oregon-based 501(c)(3)s in the
Health (NTEE major group 4) and Human Services (5) categories, then
post-filters per-org NTEE codes to tag DSV / Housing / Maternal Health.

API docs: https://projects.propublica.org/nonprofits/api
"""

from __future__ import annotations

import json
from typing import Iterable

from ..models import Organization, Topic
from ..protocols import HttpClient
from .base import BaseDiscoverySource


SEARCH_ENDPOINT = "https://projects.propublica.org/nonprofits/api/v2/search.json"

# NTEE code prefixes that map to our topics.
# References:
#   I71 = Crime, Legal-Related / Spouse Abuse Prevention
#   L*  = Housing & Shelter
#   E40 = Reproductive Health Care
#   E42 = Family Planning Centers
#   P40 = Family Services (often includes maternal support)
#   P47 = Pregnancy Centers
#   P81 = Senior Centers (kept out)
NTEE_PREFIXES: dict[str, set[Topic]] = {
    "I71": {Topic.DSV},
    "I72": {Topic.DSV},
    "I73": {Topic.DSV},
    "L": {Topic.HOUSING},
    "E40": {Topic.MATERNAL_HEALTH},
    "E42": {Topic.MATERNAL_HEALTH},
    "P47": {Topic.MATERNAL_HEALTH},
    "P40": {Topic.MATERNAL_HEALTH},
}

# NTEE major group integers passed to the search API (1-10).
DEFAULT_NTEE_MAJOR_GROUPS = (4, 5, 7)


class ProPublicaDiscovery(BaseDiscoverySource):
    """Search ProPublica for Oregon NGOs and topic-tag the results."""

    name = "propublica"

    def __init__(
        self,
        http: HttpClient,
        *,
        ntee_major_groups: tuple[int, ...] = DEFAULT_NTEE_MAJOR_GROUPS,
        max_pages_per_group: int = 10,
        state: str = "OR",
    ) -> None:
        super().__init__(http)
        self._major_groups = ntee_major_groups
        self._max_pages = max_pages_per_group
        self._state = state

    def discover(self) -> Iterable[Organization]:
        seen_eins: set[str] = set()
        for group in self._major_groups:
            yield from self._search_group(group, seen_eins)

    def _search_group(self, group: int, seen: set[str]) -> Iterable[Organization]:
        for page in range(self._max_pages):
            url = (
                f"{SEARCH_ENDPOINT}"
                f"?state%5Bid%5D={self._state}"
                f"&ntee%5Bid%5D={group}"
                f"&page={page}"
            )
            resp = self._http.get(url)
            if resp.status_code >= 400:
                return
            try:
                payload = json.loads(resp.text)
            except ValueError:
                return
            orgs = payload.get("organizations") or []
            if not orgs:
                return
            for raw in orgs:
                org = _to_org(raw, source_url=url)
                if org is None:
                    continue
                if org.ein and org.ein in seen:
                    continue
                if org.ein:
                    seen.add(org.ein)
                yield org
            # Stop early if we hit the last page.
            num_pages = payload.get("num_pages", 1)
            if page + 1 >= num_pages:
                return


def _to_org(raw: dict, *, source_url: str) -> Organization | None:
    name = (raw.get("name") or "").strip()
    if not name:
        return None
    ntee = (raw.get("ntee_code") or "").strip().upper()
    topics = _topics_for_ntee(ntee)
    if not topics:
        return None
    ein = raw.get("ein")
    ein_str = str(ein) if ein is not None else None
    return Organization(
        name=name,
        ein=ein_str,
        city=(raw.get("city") or "").strip() or None,
        state=(raw.get("state") or "OR").strip() or "OR",
        topics=topics,
        discovered_via=["propublica"],
        source_urls=[source_url],
    )


def _topics_for_ntee(ntee_code: str) -> set[Topic]:
    """Match a per-org NTEE code to one or more of our topics."""
    if not ntee_code:
        return set()
    matched: set[Topic] = set()
    for prefix, topics in NTEE_PREFIXES.items():
        if ntee_code.startswith(prefix):
            matched |= topics
    return matched
