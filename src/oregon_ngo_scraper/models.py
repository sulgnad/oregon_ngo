"""Core data models for the Oregon NGO scraper.

These are pure dataclasses / enums with no I/O dependencies, so they are
trivial to construct in tests and to serialize to JSON or CSV.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Topic(str, Enum):
    """Issue area an organization works on."""

    DSV = "dsv"  # domestic & sexual violence
    HOUSING = "housing"
    MATERNAL_HEALTH = "maternal_health"

    @classmethod
    def from_str(cls, value: str) -> "Topic":
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        for member in cls:
            if member.value == normalized:
                return member
        raise ValueError(f"Unknown topic: {value!r}")


@dataclass
class Organization:
    """A candidate organization, partially filled in by discovery and
    progressively enriched by URL resolution and extraction."""

    name: str
    aka: list[str] = field(default_factory=list)
    website: str | None = None
    ein: str | None = None
    city: str | None = None
    county: str | None = None
    state: str = "OR"
    topics: set[Topic] = field(default_factory=set)
    keywords: list[str] = field(default_factory=list)
    notes: str | None = None
    verification_status: str | None = None
    discovered_via: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    mission: str | None = None
    values: str | None = None
    mission_source_url: str | None = None
    mission_file: str | None = None
    scraped_at: datetime | None = None

    def merge(self, other: "Organization") -> "Organization":
        """Combine two organization records that refer to the same entity.

        Returns a new ``Organization`` with the union of facts from ``self``
        and ``other``. ``self`` takes precedence for scalar conflicts unless
        it is missing a value.
        """
        return Organization(
            name=self.name or other.name,
            aka=_dedup(self.aka + other.aka),
            website=self.website or other.website,
            ein=self.ein or other.ein,
            city=self.city or other.city,
            county=self.county or other.county,
            state=self.state or other.state,
            topics=self.topics | other.topics,
            keywords=_dedup(self.keywords + other.keywords),
            notes=self.notes or other.notes,
            verification_status=self.verification_status or other.verification_status,
            discovered_via=_dedup(self.discovered_via + other.discovered_via),
            source_urls=_dedup(self.source_urls + other.source_urls),
            mission=self.mission or other.mission,
            values=self.values or other.values,
            mission_source_url=self.mission_source_url or other.mission_source_url,
            mission_file=self.mission_file or other.mission_file,
            scraped_at=self.scraped_at or other.scraped_at,
        )

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "aka": list(self.aka),
            "website": self.website,
            "ein": self.ein,
            "city": self.city,
            "county": self.county,
            "state": self.state,
            "topics": sorted(t.value for t in self.topics),
            "keywords": list(self.keywords),
            "notes": self.notes,
            "verification_status": self.verification_status,
            "discovered_via": list(self.discovered_via),
            "source_urls": list(self.source_urls),
            "mission": self.mission,
            "values": self.values,
            "mission_source_url": self.mission_source_url,
            "mission_file": self.mission_file,
            "scraped_at": self.scraped_at.isoformat() if self.scraped_at else None,
        }


@dataclass
class FetchedPage:
    """A single HTTP page fetched by the crawler."""

    url: str
    html: str
    status: int = 200
    rendered_with_browser: bool = False


@dataclass
class MissionResult:
    """Outcome of running the mission/values extractor on a set of pages."""

    mission: str | None = None
    values: str | None = None
    source_url: str | None = None
    strategies: list[str] = field(default_factory=list)


def _dedup(items: list[str]) -> list[str]:
    """Return ``items`` with duplicates removed, preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
