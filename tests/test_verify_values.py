"""Verify that 'values' text in orgs.csv exists on the corresponding website.

This module is *not* a regular unit test — it hits live websites and takes
several minutes to complete.  It is gated behind the ``live`` pytest marker
so it never runs during normal ``pytest`` invocations.

Run on demand:
    pytest tests/test_verify_values.py -m live -v

Or as a standalone script:
    python -m tests.test_verify_values                     # default CSV path
    python -m tests.test_verify_values path/to/orgs.csv    # custom CSV path
"""

from __future__ import annotations

import csv
import html
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CSV = _PROJECT_ROOT / "data" / "output" / "orgs.csv"

_TIMEOUT = 15
_INTER_REQUEST_DELAY = 0.5
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}
_FALLBACK_PATHS = ("/about", "/about-us", "/about/", "/about-us/", "/mission", "/our-values")

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class VerifyResult:
    """Outcome of verifying one CSV row."""

    row: int
    name: str
    website: str
    link_ok: bool
    values_found: bool
    found_on: str | None = None
    error: str | None = None


@dataclass
class VerifySummary:
    """Aggregate stats from a full verification run."""

    total: int = 0
    link_ok: int = 0
    link_fail: int = 0
    values_found: int = 0
    values_missing: int = 0
    results: list[VerifyResult] = field(default_factory=list)

    @property
    def failures(self) -> list[VerifyResult]:
        return [r for r in self.results if not r.values_found]


# ---------------------------------------------------------------------------
# Fetching / comparison helpers
# ---------------------------------------------------------------------------


def fetch_page(url: str) -> tuple[str | None, str | None]:
    """Return (page_text, error).  *page_text* is raw HTML on success."""
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_SSL_CTX) as resp:
            data = resp.read()
            try:
                return data.decode("utf-8"), None
            except UnicodeDecodeError:
                return data.decode("latin-1"), None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _strip_html(raw: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(text)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def page_contains_values(page_html: str, values_text: str) -> bool:
    """Check whether the full *values_text* appears in the visible text of *page_html*."""
    return _normalize(values_text) in _normalize(_strip_html(page_html))


# ---------------------------------------------------------------------------
# Core verification logic
# ---------------------------------------------------------------------------


def _check_url_for_values(url: str, values: str) -> tuple[bool, str | None]:
    """Fetch *url* and return (found, error)."""
    page, err = fetch_page(url)
    if err:
        return False, err
    assert page is not None
    return page_contains_values(page, values), None


def verify_row(
    row_num: int,
    name: str,
    website: str,
    values: str,
    mission_url: str | None,
) -> VerifyResult:
    """Verify a single CSV row.  Tries the main website, the mission URL,
    and a handful of common sub-paths."""

    # 1. Main website
    page_html, err = fetch_page(website)
    if err:
        return VerifyResult(row_num, name, website, link_ok=False, values_found=False, error=err)

    assert page_html is not None
    if page_contains_values(page_html, values):
        return VerifyResult(row_num, name, website, link_ok=True, values_found=True, found_on=website)

    # 2. mission_source_url (if different from website)
    if mission_url and mission_url != website:
        found, _ = _check_url_for_values(mission_url, values)
        if found:
            return VerifyResult(row_num, name, website, link_ok=True, values_found=True, found_on=mission_url)
        time.sleep(_INTER_REQUEST_DELAY)

    # 3. Common sub-paths
    base = website.rstrip("/")
    for suffix in _FALLBACK_PATHS:
        candidate = base + suffix
        if candidate == mission_url:
            continue
        found, _ = _check_url_for_values(candidate, values)
        if found:
            return VerifyResult(row_num, name, website, link_ok=True, values_found=True, found_on=candidate)
        time.sleep(0.3)

    return VerifyResult(row_num, name, website, link_ok=True, values_found=False)


def load_rows(csv_path: Path) -> list[dict[str, str]]:
    """Read *csv_path* and return rows that have both ``website`` and ``values``."""
    with csv_path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return [
            row
            for row in reader
            if (row.get("website") or "").strip() and (row.get("values") or "").strip()
        ]


def run_verification(csv_path: Path) -> VerifySummary:
    """Run the full verification pass and return a summary."""
    rows = load_rows(csv_path)
    summary = VerifySummary(total=len(rows))

    for idx, row in enumerate(rows):
        result = verify_row(
            row_num=idx + 2,  # +2: 1-indexed header + data offset
            name=row["name"],
            website=row["website"].strip(),
            values=row["values"].strip(),
            mission_url=(row.get("mission_source_url") or "").strip() or None,
        )
        summary.results.append(result)
        if result.link_ok:
            summary.link_ok += 1
        else:
            summary.link_fail += 1
        if result.values_found:
            summary.values_found += 1
        else:
            summary.values_missing += 1

        time.sleep(_INTER_REQUEST_DELAY)

    return summary


# ---------------------------------------------------------------------------
# Pytest integration  (gated behind ``live`` marker)
# ---------------------------------------------------------------------------


def _rows() -> list[dict[str, str]]:
    if not _DEFAULT_CSV.exists():
        pytest.skip(f"CSV not found: {_DEFAULT_CSV}")
    return load_rows(_DEFAULT_CSV)


@pytest.mark.live
@pytest.mark.parametrize(
    "row",
    _rows() if _DEFAULT_CSV.exists() else [],
    ids=lambda r: r.get("name", "?"),
)
def test_website_link_loads(row: dict[str, str]) -> None:
    """Each website URL should return a non-error HTTP response."""
    _, err = fetch_page(row["website"].strip())
    assert err is None, f"{row['name']}: {err}"


@pytest.mark.live
@pytest.mark.parametrize(
    "row",
    _rows() if _DEFAULT_CSV.exists() else [],
    ids=lambda r: r.get("name", "?"),
)
def test_values_text_exists_on_site(row: dict[str, str]) -> None:
    """The full values text for each org must appear somewhere on its site."""
    result = verify_row(
        row_num=0,
        name=row["name"],
        website=row["website"].strip(),
        values=row["values"].strip(),
        mission_url=(row.get("mission_source_url") or "").strip() or None,
    )
    assert result.values_found, (
        f"{row['name']}: values text not found on {row['website']} "
        f"or common sub-pages"
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _cli(argv: Sequence[str] | None = None) -> None:
    args = list(argv) if argv is not None else sys.argv[1:]
    csv_path = Path(args[0]) if args else _DEFAULT_CSV

    if not csv_path.exists():
        print(f"Error: {csv_path} not found", file=sys.stderr)
        sys.exit(1)

    rows = load_rows(csv_path)
    print(f"Rows with website + values: {len(rows)}")
    print("=" * 90)

    summary = run_verification(csv_path)

    for r in summary.results:
        link = "OK" if r.link_ok else f"FAIL ({r.error})"
        if r.values_found:
            vals = f"FOUND on {r.found_on}"
        else:
            vals = "NOT_FOUND"
        print(f"  Row {r.row}: {r.name}")
        print(f"    Link: {link}  |  Values: {vals}")

    print(f"\n{'=' * 90}")
    print(f"Total:          {summary.total}")
    print(f"Links OK:       {summary.link_ok}")
    print(f"Links FAILED:   {summary.link_fail}")
    print(f"Values found:   {summary.values_found}")
    print(f"Values missing: {summary.values_missing}")

    if summary.failures:
        print(f"\nFailed verifications ({len(summary.failures)}):")
        for r in summary.failures:
            print(f"  Row {r.row}: {r.name} ({r.website})")

    sys.exit(1 if summary.failures else 0)


if __name__ == "__main__":
    _cli()
