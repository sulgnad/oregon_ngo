"""Enrich orgs with websites by hitting ProPublica's detail endpoint.

The ProPublica search endpoint we use during discovery returns only basic
identity fields (name, EIN, city, NTEE major group). The per-organization
detail endpoint at ``/organizations/<EIN>.json`` returns a richer payload
including verified IRS address, ZIP, NTEE classification, and (occasionally)
URL-shaped fields buried in the response.

This enricher does two things for every org with an EIN but no website:

1. **Detail fetch** \u2014 calls the detail endpoint and merges the verified
   address/zip/NTEE classification onto the ``Organization``. This data is
   useful in its own right and improves downstream URL resolution accuracy
   regardless of whether a website is found here.
2. **Website lookup** \u2014 first scans the detail payload for any URL-shaped
   string in plausible fields (``website``, ``url``, ``home_page``, etc.);
   if none is present (the common case for ProPublica today), falls back
   to the injected :class:`HomepageResolver`, now seeded with the verified
   city for a much more targeted homepage search.

Every collaborator (HTTP, resolver, logger) is constructor-injected so the
enricher is fully exercisable with fakes.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Iterable

from ..models import Organization
from ..protocols import HttpClient
from ..resolver import HomepageResolver


logger = logging.getLogger(__name__)


DETAIL_ENDPOINT_TEMPLATE = (
    "https://projects.propublica.org/nonprofits/api/v2/organizations/{ein}.json"
)


# Field names in the detail payload where a homepage URL has historically
# appeared. ProPublica adds/removes fields over time so we tolerate misses.
_URL_KEYS: tuple[str, ...] = (
    "website",
    "website_url",
    "url",
    "home_page",
    "homepage",
)


_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


class ProPublicaDetailFetcher:
    """Thin client for the ProPublica organization detail endpoint.

    Returns the parsed ``organization`` dict (or ``None`` for 404 / parse
    failure). Kept as a separate class so enrichment logic can be tested in
    isolation from the HTTP plumbing.
    """

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def fetch(self, ein: str) -> dict | None:
        url = DETAIL_ENDPOINT_TEMPLATE.format(ein=ein)
        try:
            resp = self._http.get(url)
        except Exception:
            logger.exception("ProPublica detail fetch failed for %s", ein)
            return None
        if resp.status_code >= 400 or not resp.text:
            return None
        try:
            payload = json.loads(resp.text)
        except ValueError:
            return None
        return payload  # full response (organization, filings_with_data, ...)


class ProPublicaWebsiteEnricher:
    """Use ProPublica detail + homepage search to fill in missing websites."""

    name = "propublica_website"

    def __init__(
        self,
        detail_fetcher: ProPublicaDetailFetcher,
        resolver: HomepageResolver | None = None,
    ) -> None:
        self._detail = detail_fetcher
        self._resolver = resolver

    def enrich(self, orgs: list[Organization]) -> list[Organization]:
        out: list[Organization] = []
        for org in orgs:
            try:
                self._enrich_one(org)
            except Exception:  # pragma: no cover - defensive
                logger.exception("enrich failed for %s", org.name)
            out.append(org)
        return out

    def _enrich_one(self, org: Organization) -> None:
        # Any org with an EIN is worth a detail fetch: the IRS address is the
        # highest-confidence address source we have, and it is useful even
        # when the org already has a website. Only the *website lookup* below
        # is skipped for orgs that already have one.
        if not org.ein:
            return
        payload = self._detail.fetch(org.ein)
        if not payload:
            return
        detail = payload.get("organization") or {}

        # 1. Merge enriched metadata onto the org.
        if not org.city:
            city = (detail.get("city") or "").strip()
            if city:
                org.city = city
        if not org.address:
            address = _format_irs_address(detail)
            if address:
                org.address = address
                if "propublica_detail" not in org.discovered_via:
                    org.discovered_via = [*org.discovered_via, "propublica_detail"]
        if detail.get("ntee_classification"):
            org.discovered_via = list(
                {*org.discovered_via, "propublica_detail"}
            )
            # Append the NTEE classification phrase to keywords if absent.
            label = str(detail["ntee_classification"]).strip()
            if label and label not in org.keywords:
                org.keywords = [*org.keywords, label]

        if org.website:
            return

        # 2. Try to extract a URL from the detail payload.
        url = _extract_url_from_payload(detail) or _extract_url_from_payload(payload)
        if url:
            org.website = url
            if "propublica_detail" not in org.discovered_via:
                org.discovered_via = [*org.discovered_via, "propublica_detail"]
            return

        # 3. Fall back to a city-scoped homepage search via the resolver.
        if self._resolver is not None:
            try:
                resolved = self._resolver.resolve(org.name, city=org.city)
            except Exception:  # pragma: no cover - defensive
                logger.exception("resolver failed for %s", org.name)
                resolved = None
            if resolved:
                org.website = resolved
                if "propublica_detail" not in org.discovered_via:
                    org.discovered_via = [*org.discovered_via, "propublica_detail"]


def _format_irs_address(detail: dict) -> str | None:
    """Build ``"123 Main St, Madras, OR 97741"`` from the detail payload.

    ProPublica exposes the IRS business master file address as separate
    ``address`` / ``city`` / ``state`` / ``zipcode`` keys. Returns ``None``
    unless there is at least a street line and a city, since a bare city is
    already captured by ``org.city``.
    """
    street = str(detail.get("address") or "").strip()
    city = str(detail.get("city") or "").strip()
    state = str(detail.get("state") or "").strip()
    zipcode = str(detail.get("zipcode") or "").strip()
    if not street or not city:
        return None
    tail = " ".join(p for p in (state, zipcode) if p)
    return ", ".join(p for p in (street, city, tail) if p)


def _extract_url_from_payload(obj: object) -> str | None:
    """Search ``obj`` (dict or nested structure) for a plausible homepage URL.

    Prefers values stored under known URL-bearing keys (``website``, ``url``,
    \u2026); falls back to any URL-shaped string anywhere in the payload that
    isn't an obvious aggregator/social link.
    """
    if isinstance(obj, dict):
        for key in _URL_KEYS:
            value = obj.get(key)
            if isinstance(value, str) and _looks_like_homepage(value):
                return _normalize(value)
    # Generic walk: find any URL-shaped string and pick the first non-noise one.
    for candidate in _iter_url_strings(obj):
        if _looks_like_homepage(candidate):
            return _normalize(candidate)
    return None


def _iter_url_strings(obj: object) -> Iterable[str]:
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_url_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_url_strings(v)
    elif isinstance(obj, str):
        for match in _URL_RE.finditer(obj):
            yield match.group(0)


_NOISE_HOSTS = (
    "propublica.org",
    "irs.gov",
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com",
    "amazonaws.com",
    "guidestar.org",
    "candid.org",
)


def _looks_like_homepage(value: str) -> bool:
    v = value.strip()
    if not v:
        return False
    if not v.lower().startswith(("http://", "https://", "www.")):
        # bare domains are common in IRS data; require at least a dot + tld
        if "." not in v or " " in v:
            return False
    lower = v.lower()
    return not any(noise in lower for noise in _NOISE_HOSTS)


def _normalize(value: str) -> str:
    v = value.strip().rstrip(".,;)\"'")
    if v.lower().startswith("www."):
        v = "https://" + v
    elif not v.lower().startswith(("http://", "https://")):
        v = "https://" + v
    return v
