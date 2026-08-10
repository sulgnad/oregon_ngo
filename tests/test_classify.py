from __future__ import annotations

import pytest

from oregon_ngo_scraper import classify
from oregon_ngo_scraper.models import Topic


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Domestic Violence", Topic.DSV),
        ("Sexual Assault Services", Topic.DSV),
        ("Relationship Safety", Topic.DSV),
        ("Warm Springs Victims of Crime Services", Topic.DSV),
        ("Gender-based violence", Topic.DSV),
        ("Housing / Shelter", Topic.HOUSING),
        ("Coordinated Entry", Topic.HOUSING),
        ("Madras Gospel Mission", Topic.HOUSING),
        ("Helping Hands Reentry Outreach Centers", Topic.HOUSING),
        ("Northwest Oregon Housing Authority", Topic.HOUSING),
        ("Tillamook County Habitat for Humanity", Topic.HOUSING),
        ("Healthy Families Oregon", Topic.MATERNAL_HEALTH),
        ("Pregnancy Resource Centers", Topic.MATERNAL_HEALTH),
        ("WIC", Topic.MATERNAL_HEALTH),
        ("Family Birthing Center", Topic.MATERNAL_HEALTH),
        ("MountainStar Family Relief Nursery", Topic.MATERNAL_HEALTH),
        ("Oregon MothersCare", Topic.MATERNAL_HEALTH),
    ],
)
def test_matches_expected_topic(text, expected) -> None:
    assert expected in classify.topics_for_text(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "Latimer Quilt & Textile Center",
        "Tillamook Air Museum",
        "Alcoholics Anonymous",
        "Transportation",
        "Dial a Ride",
    ],
)
def test_ignores_irrelevant_text(text) -> None:
    assert classify.topics_for_text(text) == set()


@pytest.mark.parametrize(
    ("text", "topic"),
    [
        # Word-boundary matching: these would all false-positive on a naive
        # substring check.
        ("Birthday Party Club", Topic.MATERNAL_HEALTH),
        ("Sheltered Workshop Program", Topic.HOUSING),
        ("Divers Alert Network", Topic.DSV),
    ],
)
def test_word_boundaries_prevent_false_positives(text, topic) -> None:
    assert topic not in classify.topics_for_text(text)


def test_combines_multiple_fragments() -> None:
    topics = classify.topics_for_text(
        "Housing / Shelter",
        "Safe Housing for survivors",
        "medium-term rental assistance for people fleeing domestic violence",
    )
    assert topics == {Topic.HOUSING, Topic.DSV}


def test_topics_for_any_accepts_an_iterable() -> None:
    assert classify.topics_for_any(["Doula services", None]) == {
        Topic.MATERNAL_HEALTH
    }


def test_is_relevant() -> None:
    assert classify.is_relevant("Emergency Shelter")
    assert not classify.is_relevant("Pioneer Museum")
