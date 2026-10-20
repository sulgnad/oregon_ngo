"""Research-note extraction in ``scripts/build_county_report.py``.

The report quotes the all-caps notes researchers left in seed-file comments
(``STATUS:``, ``SERVICE CHANGE:`` ...). Quoting too little is worse than
quoting nothing: \"shelters were suspended\" without \"one reopened\" misleads.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_county_report.py"
_spec = importlib.util.spec_from_file_location("build_county_report", SCRIPT)
report = importlib.util.module_from_spec(_spec)
# The script defines a dataclass; on Python 3.9 dataclasses look their module
# up in sys.modules, so it has to be registered before it executes.
sys.modules[_spec.name] = report
_spec.loader.exec_module(report)


def _comments(text: str) -> list[str]:
    return [f"  # {line}" for line in text.strip("\n").splitlines()]


def test_note_runs_to_the_end_of_its_paragraph() -> None:
    lines = _comments(
        """
Sources: unityshelter.org.
SERVICE HISTORY: shelters were suspended in May
2025. One reopened in December 2025, restoring
50 beds.
Programme sites: elsewhere.
"""
    )
    assert report._marker_notes(lines) == [
        (
            "Service History",
            "shelters were suspended in May 2025. One reopened in December 2025, restoring 50 beds.",
        )
    ]


def test_a_line_ending_mid_sentence_does_not_end_the_note() -> None:
    lines = _comments(
        """
STATUS: OHSU was considering a conversion; staff wrote
to leadership opposing it;
OHSU said it remains committed. No conversion was announced.
org_type is recorded as government.
"""
    )
    [(marker, text)] = report._marker_notes(lines)
    assert marker == "Status"
    assert text.endswith("No conversion was announced.")
    assert "org_type" not in text


def test_marker_followed_by_a_comma() -> None:
    lines = _comments("CAUTION, not reflected in the export: audits are behind.")
    assert report._marker_notes(lines) == [("Caution", "not reflected in the export: audits are behind.")]


def test_mixed_case_text_is_not_a_marker() -> None:
    lines = _comments("OHSU said it was considering a change.\nURL fixed 2026-10-19: moved.")
    assert report._marker_notes(lines) == []


def test_a_new_marker_ends_the_previous_note() -> None:
    lines = _comments("MOVE: the office moved\nACROSS TOWN: unrelated")
    notes = report._marker_notes(lines)
    assert [m for m, _ in notes] == ["Move", "Across Town"]
    assert notes[0][1] == "the office moved"


def test_long_note_is_clipped_at_a_sentence_boundary() -> None:
    sentence = "This sentence is fifty characters long, near enough. "
    text = report._clip(sentence * 20, limit=120)
    # Cut after the last whole sentence that fits, then marked as truncated.
    assert text.endswith("near enough. …")
    assert len(text) <= 120 + len(" …")


def test_short_note_is_returned_whole() -> None:
    assert report._clip("Paused  in\nMarch.") == "Paused in March."


@pytest.fixture
def seeds_dir(tmp_path: Path, monkeypatch) -> Path:
    (tmp_path / "counties").mkdir()
    monkeypatch.setattr(report, "SEEDS_DIR", tmp_path)
    return tmp_path


def test_notes_attach_to_the_entry_that_follows_them(seeds_dir: Path) -> None:
    (seeds_dir / "counties" / "testshire.yml").write_text(
        """# File header.
#   - EXCLUDED: a header note must not attach to the first entry.

organizations:
  # Sources: own site.
  - name: "First Org"
    city: "Corvallis"

  # STATUS: paused in March, resumed in June.
  - name: "Second Org"
""",
        encoding="utf-8",
    )
    entries, notes = report._load_seeds("Testshire")
    assert set(entries) == {"First Org", "Second Org"}
    assert notes.get("First Org", []) == []
    assert notes["Second Org"] == [("Status", "paused in March, resumed in June.")]
