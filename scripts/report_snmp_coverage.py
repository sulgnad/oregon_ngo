"""Summarize the county SNMP export: fill rates and address sanity.

Usage:
    python scripts/report_snmp_coverage.py [csv_path]

Flags any ``Primary_Location_Address`` that does not name a community in one
of the target counties, which is the failure mode that matters most here:
a regional agency's headquarters being recorded as its county office.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from oregon_ngo_scraper import geo  # noqa: E402


DEFAULT_CSV = (
    Path(__file__).resolve().parents[1] / "data" / "output" / "baker_snmp.csv"
)

REPORTED_COLUMNS = (
    "Primary_Location_Address",
    "Phone",
    "Email",
    "URL",
    "Services_Summary",
    "County",
    "Org_Agency_Type",
    "Org_Agency_Level",
    "Primary_Resources_Services",
)


def in_county_cities() -> set[str]:
    return {city for cities in geo.COUNTY_CITIES.values() for city in cities}


def names_target_city(address: str, cities: set[str]) -> bool:
    lowered = address.lower()
    return any(
        re.search(rf"(?<!\w){re.escape(city)}(?!\w)", lowered) for city in cities
    )


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_CSV
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    if not rows:
        print(f"{path}: no rows")
        return 1
    cities = in_county_cities()

    print(f"{path.name}: {len(rows)} rows, {len(rows[0])} columns\n")
    header = f"{'Org_Agency_Name':<42} {'ok':<3} {'Address':<44} {'Phone':<15} Email"
    print(header)
    print("-" * len(header))

    suspect: list[tuple[str, str]] = []
    for row in sorted(rows, key=lambda r: (r["County"], r["Org_Agency_Name"])):
        address = row["Primary_Location_Address"]
        flag = ""
        if address:
            if names_target_city(address, cities):
                flag = "OK"
            else:
                flag = "??"
                suspect.append((row["Org_Agency_Name"], address))
        print(
            f"{row['Org_Agency_Name'][:41]:<42} {flag:<3} "
            f"{(address or '-')[:43]:<44} {(row['Phone'] or '-'):<15} "
            f"{(row['Email'] or '-')[:28]}"
        )

    print("\nfill rates:")
    for column in REPORTED_COLUMNS:
        filled = sum(1 for r in rows if r[column].strip())
        print(f"  {column:<28} {filled:2d}/{len(rows)}  {100 * filled // len(rows):3d}%")

    print(f"\naddresses not naming a target-county community: {len(suspect)}")
    for name, address in suspect:
        print(f"  {name} -> {address}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
