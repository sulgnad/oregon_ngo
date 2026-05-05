"""Base helpers shared by discovery sources."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Iterable
from urllib.parse import urlparse

from ..models import Organization
from ..protocols import HttpClient


class BaseDiscoverySource(ABC):
    """Common behaviour for every discovery source."""

    name: str = "base"

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    @abstractmethod
    def discover(self) -> Iterable[Organization]: ...


_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")
_SUFFIXES = (
    "inc",
    "incorporated",
    "ltd",
    "llc",
    "corp",
    "corporation",
    "the",
    "of oregon",
    "oregon",
)


def normalize_name(name: str) -> str:
    """Return a canonical form of an org name for dedup keys."""
    s = name.lower().strip()
    s = _NORMALIZE_RE.sub(" ", s)
    parts = [p for p in s.split() if p and p not in _SUFFIXES]
    return " ".join(parts)


def apex_host(url: str | None) -> str:
    """Return ``example.org`` for any URL, stripping ``www.`` and scheme.

    Used as the canonical website-based dedup key so
    ``https://www.bradleyangle.org`` and ``https://bradleyangle.org/about``
    collapse to the same group.
    """
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else f"http://{url}")
    host = (parsed.netloc or parsed.path).lower().strip().split("/", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def dedup_key(org: Organization) -> str:
    """Stable key used to merge records that refer to the same organization."""
    if org.ein:
        return f"ein:{org.ein}"
    if org.website:
        host = apex_host(org.website)
        if host:
            return f"site:{host}"
    return f"name:{normalize_name(org.name)}"


def coalesce_duplicates(orgs: list[Organization]) -> list[Organization]:
    """Second-pass merge across orgs that share an EIN or apex host.

    The first-pass ``dedup_key`` only sees one identifier per org. After
    enrichment, an EIN-only record can gain a website that happens to match
    an existing site-keyed record. This pass uses a simple union-find to
    fold those together.
    """
    if not orgs:
        return []

    parent: dict[int, int] = {i: i for i in range(len(orgs))}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    by_ein: dict[str, int] = {}
    by_host: dict[str, int] = {}
    by_name: dict[str, int] = {}
    for i, org in enumerate(orgs):
        if org.ein:
            if org.ein in by_ein:
                union(by_ein[org.ein], i)
            else:
                by_ein[org.ein] = i
        host = apex_host(org.website)
        if host:
            if host in by_host:
                union(by_host[host], i)
            else:
                by_host[host] = i
        # Conservative name-based grouping: only used as a tiebreaker if
        # neither EIN nor host matches anything seen so far.
        nkey = normalize_name(org.name)
        if nkey and not org.ein and not host:
            if nkey in by_name:
                union(by_name[nkey], i)
            else:
                by_name[nkey] = i

    groups: dict[int, Organization] = {}
    for i, org in enumerate(orgs):
        root = find(i)
        if root in groups:
            groups[root] = groups[root].merge(org)
        else:
            groups[root] = org
    return list(groups.values())
