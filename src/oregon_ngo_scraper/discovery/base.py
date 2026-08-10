"""Base helpers shared by discovery sources."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Iterable
from urllib.parse import urlparse

from ..models import SHARED_HOST_ORG_TYPES, Organization
from ..protocols import HttpClient


class BaseDiscoverySource(ABC):
    """Common behaviour for every discovery source."""

    name: str = "base"

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    @abstractmethod
    def discover(self) -> Iterable[Organization]: ...


_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")
_PAREN_RE = re.compile(r"\([^)]*\)")
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
# Aggressive filler set used by ``canonical_name`` for cross-source dedup.
# Includes ``normalize_name``'s suffixes plus connective words and the
# common "foundation"/"formerly" tokens that orgs vary in.
_CANONICAL_FILLERS = set(_SUFFIXES) | {
    "a",
    "an",
    "and",
    "or",
    "of",
    "for",
    "to",
    "co",
    "company",
    "foundation",
    "formerly",
}


def normalize_name(name: str) -> str:
    """Return a canonical form of an org name for dedup keys.

    Conservative: lowercases, strips punctuation, drops corporate suffixes
    and Oregon-specific tokens. Preserves distinguishing tokens like
    ordinals ("V", "II") and place names so genuinely different orgs keep
    distinct keys.
    """
    s = name.lower().strip()
    s = _NORMALIZE_RE.sub(" ", s)
    parts = [p for p in s.split() if p and p not in _SUFFIXES]
    return " ".join(parts)


def canonical_name(name: str) -> str:
    """Aggressive normalization for cross-source duplicate detection.

    Beyond ``normalize_name``: strips parenthesized text (acronyms like
    ``(CHS)``), drops connective words (``and``, ``for``, ``of``), and
    drops common framing tokens (``foundation``, ``formerly``). Used
    only inside :func:`coalesce_duplicates` so two records that refer
    to the same org but stylize the name differently still merge.
    """
    s = name.lower().strip()
    s = _PAREN_RE.sub(" ", s)
    s = _NORMALIZE_RE.sub(" ", s)
    parts = [p for p in s.split() if p and p not in _CANONICAL_FILLERS]
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


def shares_host_with_siblings(org: Organization) -> bool:
    """True when ``org``'s website host is not a unique identifier for it.

    A county or tribal government runs many distinct programs off a single
    domain: ``warmsprings-nsn.gov`` hosts Victims of Crime Services, the
    Housing Authority and Community Counseling, and ``tillamookcounty.gov``
    hosts the Housing Commission and the DA's Victims Assistance Program.
    Keying those on the apex host would silently collapse them into one row,
    so they fall back to a name-based key instead.
    """
    return org.org_type in SHARED_HOST_ORG_TYPES


def dedup_key(org: Organization) -> str:
    """Stable key used to merge records that refer to the same organization."""
    if org.ein:
        return f"ein:{org.ein}"
    if org.website and not shares_host_with_siblings(org):
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
        # Government/tribal programs deliberately skip host indexing so that
        # sibling programs on a shared domain stay distinct rows.
        host = "" if shares_host_with_siblings(org) else apex_host(org.website)
        if host:
            if host in by_host:
                union(by_host[host], i)
            else:
                by_host[host] = i
        # Always index by canonical_name (aggressive: strips parenthesized
        # acronyms, drops connectives like "and"/"for") so an OCADSV record
        # with no website merges with the xlsx_starter record that has one.
        # canonical_name still preserves distinguishing tokens like ordinals
        # so genuinely different orgs (e.g. "Foundation For Affordable Housing
        # Inc" vs "… V Inc") keep distinct keys.
        nkey = canonical_name(org.name)
        if nkey:
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
