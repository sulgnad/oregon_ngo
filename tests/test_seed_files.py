"""Checks on the committed seed files themselves.

The seed loader drops an unknown ``agency_level`` with a warning so one typo
can't discard a whole county. That leniency means a typo would otherwise
pass silently and quietly revert the row to its default level; this test is
where it gets caught.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from oregon_ngo_scraper.models import AGENCY_LEVELS


SEED_FILES = sorted((Path(__file__).resolve().parents[1] / "data" / "seeds").rglob("*.yml"))
ALLOWED = {level.lower() for level in AGENCY_LEVELS}


@pytest.mark.parametrize("path", SEED_FILES, ids=lambda p: p.name)
def test_agency_levels_are_valid(path: Path) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for org in data.get("organizations") or []:
        level = org.get("agency_level")
        if level is not None:
            assert str(level).strip().lower() in ALLOWED, (org.get("name"), level)


def test_seed_files_were_found() -> None:
    """Guard against the glob silently matching nothing."""
    assert any(p.parent.name == "counties" for p in SEED_FILES)
