"""Base helpers shared by discovery sources."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Iterable

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


def dedup_key(org: Organization) -> str:
    """Stable key used to merge records that refer to the same organization."""
    if org.ein:
        return f"ein:{org.ein}"
    if org.website:
        host = org.website.lower()
        return f"site:{host}"
    return f"name:{normalize_name(org.name)}"
