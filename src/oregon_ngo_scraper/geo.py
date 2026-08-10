"""Oregon geography helpers for county-scoped collection.

The project's ``county`` field is free-form: the Voices Project starter list
uses values like ``Deschutes / Crook / Jefferson``, ``Multnomah (HQ)`` and
``Wasco (also serves Sherman/Gilliam/Wheeler)``. This module turns those into
something filterable, and maps the cities of our two target counties back to
a county name so discovery sources that only report a city still land in the
right bucket.

City coverage is deliberately **not** statewide — only Jefferson and Tillamook
are enumerated, because those are the counties we collect for. Everything else
resolves to ``None`` and is treated as "unknown location" by the pipeline.
"""

from __future__ import annotations

import re
from typing import Iterable


# --- Target-county city lists ----------------------------------------------
# Incorporated cities plus the unincorporated communities and CDPs that show
# up as mailing addresses in IRS/ProPublica data and county resource guides.

JEFFERSON_CITIES: frozenset[str] = frozenset(
    {
        "madras",
        "warm springs",
        "culver",
        "metolius",
        "camp sherman",
        "ashwood",
        "gateway",
    }
)

TILLAMOOK_CITIES: frozenset[str] = frozenset(
    {
        "tillamook",
        "nehalem",
        "manzanita",
        "rockaway beach",
        "garibaldi",
        "bay city",
        "wheeler",
        "cloverdale",
        "pacific city",
        "netarts",
        "oceanside",
        "beaver",
        "hebo",
        "neskowin",
        "idaville",
        "tierra del mar",
        "sandlake",
        "blaine",
        "nedonna beach",
    }
)


CITY_TO_COUNTY: dict[str, str] = {
    **{city: "Jefferson" for city in JEFFERSON_CITIES},
    **{city: "Tillamook" for city in TILLAMOOK_CITIES},
}


# The 36 Oregon counties. Used only to tell a real county name apart from a
# qualifier such as ``HQ`` when parsing a free-form ``county`` cell.
OREGON_COUNTIES: frozenset[str] = frozenset(
    {
        "baker",
        "benton",
        "clackamas",
        "clatsop",
        "columbia",
        "coos",
        "crook",
        "curry",
        "deschutes",
        "douglas",
        "gilliam",
        "grant",
        "harney",
        "hood river",
        "jackson",
        "jefferson",
        "josephine",
        "klamath",
        "lake",
        "lane",
        "lincoln",
        "linn",
        "malheur",
        "marion",
        "morrow",
        "multnomah",
        "polk",
        "sherman",
        "tillamook",
        "umatilla",
        "union",
        "wallowa",
        "wasco",
        "washington",
        "wheeler",
        "yamhill",
    }
)


_WS_RE = re.compile(r"\s+")
_PAREN_RE = re.compile(r"\(([^)]*)\)")
# Counties in a single cell are separated by "/", ",", "&" or the word "and".
_SPLIT_RE = re.compile(r"\s*(?:/|,|&|\band\b)\s*", re.IGNORECASE)
# Leading qualifier inside a parenthetical, e.g. "(also serves Sherman/Gilliam)".
_SERVES_PREFIX_RE = re.compile(r"^(?:also\s+)?serves\s+", re.IGNORECASE)


def normalize_place(value: str | None) -> str:
    """Lowercase, collapse whitespace and drop the trailing ``County`` word."""
    if not value:
        return ""
    s = _WS_RE.sub(" ", str(value)).strip().lower()
    if s.endswith(" county"):
        s = s[: -len(" county")]
    return s.strip()


def county_for_city(city: str | None) -> str | None:
    """Return the county name for a city in one of the target counties.

    Returns ``None`` for cities outside Jefferson/Tillamook — this module
    intentionally does not carry a statewide city table.
    """
    return CITY_TO_COUNTY.get(normalize_place(city))


def cities_for_county(county: str | None) -> frozenset[str]:
    """Return the known (lowercase) city names for a target county."""
    normalized = normalize_place(county)
    if normalized == "jefferson":
        return JEFFERSON_CITIES
    if normalized == "tillamook":
        return TILLAMOOK_CITIES
    return frozenset()


def find_city(text: str | None, county: str | None) -> str | None:
    """Find a city of ``county`` mentioned in ``text``.

    Directory entries usually carry a street address (``"164 SE D St Madras,
    OR 97741"``), which is the only city signal available on those pages.
    Longest names are tried first so ``Rockaway Beach`` wins over ``Beaver``
    style partial overlaps, and matching is word-boundary based so
    ``Tillamook`` in ``Tillamook County`` still resolves.
    """
    if not text:
        return None
    cities = cities_for_county(county)
    if not cities:
        return None
    haystack = _WS_RE.sub(" ", text).lower()
    for city in sorted(cities, key=len, reverse=True):
        if re.search(rf"(?<!\w){re.escape(city)}(?!\w)", haystack):
            return city.title()
    return None


def parse_county_field(value: str | None) -> tuple[list[str], list[str]]:
    """Split a free-form ``county`` cell into (primary, also_serves).

    ``"Deschutes / Crook / Jefferson"`` -> ``(["Deschutes", "Crook", "Jefferson"], [])``
    ``"Multnomah (HQ)"``                -> ``(["Multnomah"], [])``
    ``"Wasco (also serves Sherman/Gilliam/Wheeler)"``
        -> ``(["Wasco"], ["Sherman", "Gilliam", "Wheeler"])``

    Anything that isn't a recognised Oregon county name (``HQ``, ``—``) is
    dropped rather than guessed at.
    """
    if not value:
        return [], []
    raw = str(value)

    also: list[str] = []
    for inner in _PAREN_RE.findall(raw):
        stripped = _SERVES_PREFIX_RE.sub("", inner.strip())
        # Only treat the parenthetical as counties if it actually names some.
        also.extend(_valid_counties(stripped))
    primary = _valid_counties(_PAREN_RE.sub(" ", raw))
    return primary, _dedup(also)


def _valid_counties(chunk: str) -> list[str]:
    out: list[str] = []
    for part in _SPLIT_RE.split(chunk):
        normalized = normalize_place(part)
        if normalized in OREGON_COUNTIES:
            out.append(normalized.title() if normalized != "hood river" else "Hood River")
    return _dedup(out)


def counties_in(value: str | None, *, include_also_serves: bool = False) -> list[str]:
    """Return every county named in a free-form ``county`` cell."""
    primary, also = parse_county_field(value)
    return _dedup(primary + also) if include_also_serves else primary


def county_matches(
    value: str | None,
    targets: Iterable[str],
    *,
    include_also_serves: bool = False,
) -> bool:
    """True when ``value`` names any county in ``targets``."""
    wanted = {normalize_place(t) for t in targets if normalize_place(t)}
    if not wanted:
        return False
    found = counties_in(value, include_also_serves=include_also_serves)
    return any(normalize_place(c) in wanted for c in found)


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            out.append(item)
    return out
