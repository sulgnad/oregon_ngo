"""Shared keyword -> :class:`Topic` classification.

Used by the resource-directory discovery sources, which get their signal from
a category heading (``"Domestic Violence"``, ``"Housing / Shelter"``) or from
an organization's name and blurb, rather than from a structured field like an
NTEE code.

Matching is **word-boundary based**, not plain substring: a bare ``in`` check
would tag "Birthday Club" as maternal health and "Sheltered Workshop" as
housing. ``discovery/oregon_sos.py`` keeps its own narrower substring map so
existing behaviour on the statewide dataset is untouched.
"""

from __future__ import annotations

import re
from typing import Iterable

from .models import Topic


# Phrases are matched with word boundaries. Order is irrelevant — every
# pattern is tested and the union of matches is returned.
_TOPIC_PATTERNS: tuple[tuple[str, Topic], ...] = (
    # --- Domestic & sexual violence ---
    (r"domestic violence", Topic.DSV),
    (r"domestic abuse", Topic.DSV),
    (r"dating violence", Topic.DSV),
    (r"sexual violence", Topic.DSV),
    (r"sexual assault", Topic.DSV),
    (r"sexual abuse", Topic.DSV),
    (r"intimate partner", Topic.DSV),
    (r"gender[- ]based violence", Topic.DSV),
    (r"relationship safety", Topic.DSV),
    (r"rape crisis", Topic.DSV),
    (r"crime victim", Topic.DSV),
    (r"victims? of crime", Topic.DSV),
    (r"victim assistance", Topic.DSV),
    (r"victim advocacy", Topic.DSV),
    (r"human trafficking", Topic.DSV),
    (r"sex trafficking", Topic.DSV),
    (r"stalking", Topic.DSV),
    (r"strangulation", Topic.DSV),
    (r"restraining order", Topic.DSV),
    (r"protective order", Topic.DSV),
    (r"order of protection", Topic.DSV),
    (r"women's (?:resource )?(?:center|shelter)", Topic.DSV),
    (r"womens (?:resource )?(?:center|shelter)", Topic.DSV),
    (r"\bdv\b", Topic.DSV),
    (r"\bdv/sv\b", Topic.DSV),
    # --- Housing & homelessness ---
    (r"housing", Topic.HOUSING),
    (r"homeless(?:ness)?", Topic.HOUSING),
    (r"\bshelter\b", Topic.HOUSING),
    (r"warming (?:shelter|center)", Topic.HOUSING),
    (r"cooling (?:shelter|center)", Topic.HOUSING),
    (r"emergency shelter", Topic.HOUSING),
    (r"transitional housing", Topic.HOUSING),
    (r"permanent supportive housing", Topic.HOUSING),
    (r"supportive housing", Topic.HOUSING),
    (r"affordable housing", Topic.HOUSING),
    (r"rapid re[- ]?housing", Topic.HOUSING),
    (r"rental assistance", Topic.HOUSING),
    (r"rent assistance", Topic.HOUSING),
    (r"coordinated entry", Topic.HOUSING),
    (r"continuum of care", Topic.HOUSING),
    (r"habitat for humanity", Topic.HOUSING),
    (r"housing authority", Topic.HOUSING),
    (r"eviction", Topic.HOUSING),
    (r"\bre-?entry\b", Topic.HOUSING),
    (r"rescue mission", Topic.HOUSING),
    (r"gospel mission", Topic.HOUSING),
    # --- Maternal health ---
    (r"maternal", Topic.MATERNAL_HEALTH),
    (r"maternity", Topic.MATERNAL_HEALTH),
    (r"prenatal", Topic.MATERNAL_HEALTH),
    (r"perinatal", Topic.MATERNAL_HEALTH),
    (r"postpartum", Topic.MATERNAL_HEALTH),
    (r"pregnan(?:cy|t)", Topic.MATERNAL_HEALTH),
    (r"\bdoula\b", Topic.MATERNAL_HEALTH),
    (r"midwif(?:e|ery|ves)", Topic.MATERNAL_HEALTH),
    (r"birthing", Topic.MATERNAL_HEALTH),
    (r"birth center", Topic.MATERNAL_HEALTH),
    (r"childbirth", Topic.MATERNAL_HEALTH),
    (r"breastfeeding", Topic.MATERNAL_HEALTH),
    (r"lactation", Topic.MATERNAL_HEALTH),
    (r"\bwic\b", Topic.MATERNAL_HEALTH),
    (r"women,? infants,? and children", Topic.MATERNAL_HEALTH),
    (r"healthy families", Topic.MATERNAL_HEALTH),
    (r"healthy start", Topic.MATERNAL_HEALTH),
    (r"babies first", Topic.MATERNAL_HEALTH),
    (r"motherscare", Topic.MATERNAL_HEALTH),
    (r"mothers care", Topic.MATERNAL_HEALTH),
    (r"relief nursery", Topic.MATERNAL_HEALTH),
    (r"home visiting", Topic.MATERNAL_HEALTH),
    (r"reproductive health", Topic.MATERNAL_HEALTH),
    (r"family planning", Topic.MATERNAL_HEALTH),
    (r"early head start", Topic.MATERNAL_HEALTH),
)


_COMPILED: tuple[tuple[re.Pattern[str], Topic], ...] = tuple(
    (re.compile(rf"(?<!\w){pattern}(?!\w)", re.IGNORECASE), topic)
    for pattern, topic in _TOPIC_PATTERNS
)


def topics_for_text(*values: str | None) -> set[Topic]:
    """Return every topic implied by the supplied strings.

    Accepts several fragments (category heading, org name, blurb) so callers
    can classify on all available context in one pass.
    """
    blob = " ".join(v for v in values if v)
    if not blob.strip():
        return set()
    return {topic for pattern, topic in _COMPILED if pattern.search(blob)}


def topics_for_any(values: Iterable[str | None]) -> set[Topic]:
    """Iterable-friendly variant of :func:`topics_for_text`."""
    return topics_for_text(*values)


def is_relevant(*values: str | None) -> bool:
    """True when the text implies at least one of the project's topics."""
    return bool(topics_for_text(*values))
