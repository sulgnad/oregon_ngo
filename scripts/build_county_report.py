"""Package selected counties into one deliverable, with a validation report.

Usage:
    python scripts/build_county_report.py [--county NAME ...] [--name STEM]
                                          [--output-dir DIR] [--check-urls]

Defaults to Benton, Columbia and Coos, written with the stem ``focus_counties``.

Reads each county's ``<slug>_snmp*.csv`` / ``<slug>_snmp.jsonl`` files (as
written by ``collect-counties``) and its seed file, and writes:

    <stem>_snmp.csv                 flat Map Database rows for all the counties
    <stem>_snmp_organizations.csv   Organization table rows
    <stem>_snmp_locations.csv       Location table rows
    <stem>_validation.csv           one row per organization: sources, gaps, flags
    <stem>_report.md                human-readable summary

Nothing is re-collected. Every row is regenerated from its JSONL payload with
the current export code, so the report also states whether the files on disk
match what the code would produce today.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

from oregon_ngo_scraper import geo, relational, snmp  # noqa: E402
from oregon_ngo_scraper.county_storage import county_paths, county_slug  # noqa: E402
from oregon_ngo_scraper.models import Organization, OrgType, Topic  # noqa: E402


DEFAULT_COUNTIES = ("Benton", "Columbia", "Coos")
DEFAULT_STEM = "focus_counties"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "output"
SEEDS_DIR = ROOT / "data" / "seeds"
WORKBOOK = Path.home() / "Downloads" / "SNMP_Main.xlsx"

#: The five fields a row needs to be useful to someone looking for help.
CORE_FIELDS: dict[str, str] = {
    "Primary_Location_Address": "street address",
    "Phone": "phone",
    "Email": "email",
    "URL": "website",
    "Services_Summary": "summary",
}

FREEMAIL = frozenset({"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com", "icloud.com"})

VALIDATION_COLUMNS: tuple[str, ...] = (
    "County",
    "Org_Agency_Name",
    "Organization_ID",
    "Location_ID",
    "Verification",
    "Agency_Type_Level",
    "Location_Type",
    "Address_Source",
    "Phone_Source",
    "Email_Source",
    "Summary_Source",
    "Website_Check",
    "Complete",
    "Missing",
    "Flags",
)

#: A research note in a seed file starts with an all-caps marker, e.g.
#: ``# STATUS: ...``, ``# SERVICE CHANGE: ...``, ``# CAUTION, not reflected ...``.
_MARKER_RE = re.compile(r"^\s*#\s+([A-Z][A-Z ]{3,}?)\s*[:,]\s*(.*)$")
_NAME_RE = re.compile(r"""^\s*-\s+name:\s*["']?(.*?)["']?\s*$""")
#: A comment line that ends a sentence (closing quotes or brackets allowed).
_SENTENCE_END_RE = re.compile(r"[.!?][\"')\]]*$")
#: Tokens whose trailing period does not end a sentence.
_ABBREVIATIONS = frozenset({"st", "ste", "ave", "dr", "rd", "blvd", "inc", "no", "vs", "e.g", "i.e", "u.s", "mt", "ft"})
#: Longest research note quoted in the report, in characters.
_NOTE_LIMIT = 700
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)


@dataclass
class Record:
    county: str
    flat: dict[str, str]
    org: dict[str, str]
    loc: dict[str, str]
    payload: dict
    seed: dict
    notes: list[tuple[str, str]] = field(default_factory=list)
    reproduces: bool = False
    website_ok: bool | None = None
    website_detail: str = ""

    @property
    def name(self) -> str:
        return self.flat["Org_Agency_Name"]


# --- loading ----------------------------------------------------------------


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _org_from_payload(payload: dict) -> Organization:
    data = dict(payload)
    data.pop("organization_id", None)
    data.pop("location_id", None)
    data["topics"] = {Topic.from_str(t) for t in data.get("topics") or []}
    data["org_type"] = OrgType.from_str(data.get("org_type") or "unknown")
    stamp = data.get("scraped_at")
    data["scraped_at"] = datetime.fromisoformat(stamp) if stamp else None
    return Organization(**data)


def _seed_files(county: str) -> list[Path]:
    slug = county_slug(county)
    files = [SEEDS_DIR / "counties" / f"{slug}.yml"]
    files += sorted((SEEDS_DIR / "counties").glob(f"{slug}.*.yml"))
    if slug in {"jefferson", "tillamook"}:
        files.append(SEEDS_DIR / "jefferson_tillamook.yml")
    return [f for f in files if f.exists()]


def _load_seeds(county: str) -> tuple[dict[str, dict], dict[str, list[tuple[str, str]]]]:
    """Seed entries by name, plus the research notes in each entry's comments."""
    entries: dict[str, dict] = {}
    notes: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for path in _seed_files(county):
        text = path.read_text(encoding="utf-8")
        for raw in (yaml.safe_load(text) or {}).get("organizations") or []:
            entries.setdefault(str(raw.get("name") or "").strip(), raw)
        pending: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                pending.append(line)
                continue
            match = _NAME_RE.match(line)
            if match:
                notes[match.group(1).strip()].extend(_marker_notes(pending))
            if stripped:
                pending = []
    return entries, notes


def _marker_notes(comment_lines: list[str]) -> list[tuple[str, str]]:
    """Extract ``(MARKER, paragraph)`` pairs from a comment block.

    A note runs from its marker to the end of its paragraph. The seed files
    wrap prose at a fixed width and start each new topic on a fresh line, so a
    line that follows a sentence-ending line opens a new paragraph. Quoting
    only the first sentence is not enough: "shelters were suspended in 2025"
    is misleading without the next sentence saying one reopened.
    """
    texts = [line.strip().lstrip("#").strip() for line in comment_lines]
    found: list[tuple[str, str]] = []
    for i, line in enumerate(comment_lines):
        match = _MARKER_RE.match(line)
        if not match:
            continue
        parts = [match.group(2)]
        for follow, text in zip(comment_lines[i + 1:], texts[i + 1:]):
            if _MARKER_RE.match(follow) or not text or _SENTENCE_END_RE.search(parts[-1]):
                break
            parts.append(text)
        found.append((match.group(1).title(), _clip(" ".join(parts))))
    return found


def _clip(text: str, limit: int = _NOTE_LIMIT) -> str:
    """Collapse whitespace and cut an over-long note at a sentence boundary."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = None
    for match in re.finditer(r"\.(?=\s|$)", text):
        if match.end() > limit:
            break
        before = text[: match.start()].rsplit(" ", 1)[-1].lower().lstrip("(\"'")
        if before in _ABBREVIATIONS or (len(before) == 1 and before.isalpha()):
            continue
        cut = match.end()
    return (text[:cut] if cut else text[: limit - 1].rstrip()) + " …"


def load_county(county: str, output_dir: Path) -> tuple[list[Record], dict[str, object]]:
    paths = county_paths(output_dir, county)
    flat_header, flat_rows = _read_csv(paths["flat"])
    org_header, org_rows = _read_csv(paths["organizations"])
    loc_header, loc_rows = _read_csv(paths["locations"])
    payloads = {p["name"]: p for p in _read_jsonl(paths["jsonl"])}
    seeds, notes = _load_seeds(county)
    orgs_by_id = {r["organization_id"]: r for r in org_rows}
    locs_by_id = {r["location_id"]: r for r in loc_rows}

    records: list[Record] = []
    for row in flat_rows:
        name = row["Org_Agency_Name"]
        payload = payloads.get(name, {})
        org_row = orgs_by_id.get(row["Organization_ID"], {})
        loc_row = locs_by_id.get(row["Location_ID"], {})
        reproduces = False
        if payload:
            model = _org_from_payload(payload)
            reproduces = (
                snmp.to_row(model) == row
                and relational.to_organization_row(model) == org_row
                and relational.to_location_row(model) == loc_row
            )
        records.append(
            Record(county, row, org_row, loc_row, payload, seeds.get(name, {}), notes.get(name, []), reproduces)
        )

    meta = {
        "headers_ok": (
            flat_header == list(snmp.SNMP_OUTPUT_COLUMNS)
            and org_header == list(relational.ORGANIZATION_COLUMNS)
            and loc_header == list(relational.LOCATION_COLUMNS)
        ),
        "counts_ok": len({len(flat_rows), len(org_rows), len(loc_rows), len(payloads)}) == 1,
        "seeded": sum(1 for r in records if r.seed),
        "orphans": sum(1 for r in loc_rows if r["organization_id"] not in orgs_by_id),
        "flat_header": flat_header,
        "org_header": org_header,
        "loc_header": loc_header,
    }
    return records, meta


# --- checks -----------------------------------------------------------------


def _check_website(url: str) -> tuple[bool, str]:
    import requests

    try:
        response = requests.get(url, headers={"User-Agent": _BROWSER_UA}, timeout=25, allow_redirects=True)
        return 200 <= response.status_code < 400, f"HTTP {response.status_code}"
    except requests.exceptions.SSLError:
        # Some servers refuse the TLS library this Python is linked against
        # (old LibreSSL on stock macOS Python). curl uses the system TLS stack,
        # so a refusal here says nothing about whether the site works.
        if shutil.which("curl"):
            result = subprocess.run(
                ["curl", "-sS", "-o", "/dev/null", "-L", "--max-time", "25", "-A", _BROWSER_UA, "-w", "%{http_code}", url],
                capture_output=True,
                text=True,
            )
            code = result.stdout.strip()
            if code.isdigit() and code != "000":
                return 200 <= int(code) < 400, f"HTTP {code} via curl"
        return False, "TLS error"
    except requests.RequestException as exc:
        return False, type(exc).__name__


def _workbook_headers_match() -> str:
    if not WORKBOOK.exists():
        return "not checked (workbook not found)"
    try:
        import openpyxl
    except ImportError:
        return "not checked (openpyxl not installed)"
    book = openpyxl.load_workbook(WORKBOOK, read_only=True, data_only=True)

    def header(sheet: str) -> tuple[str, ...]:
        first = next(book[sheet].iter_rows(values_only=True))
        return tuple(str(c) for c in first if c is not None)

    ok = (
        header("Map Database") == snmp.SNMP_COLUMNS
        and header("Organization Table") == relational.ORGANIZATION_COLUMNS
        and header("(Main) Location Table") == relational.LOCATION_COLUMNS
    )
    return "yes" if ok else "NO"


# --- per-record derivations -------------------------------------------------


def _source(record: Record, key: str) -> str:
    if not record.payload.get(key):
        return "none"
    return "seed" if record.seed.get(key) else "pipeline"


def _summary_source(record: Record) -> str:
    if record.payload.get("mission"):
        return "scraped mission" if record.payload.get("mission_source_url") else "seeded mission"
    return "written description" if record.payload.get("notes") else "none"


def _verified(record: Record) -> bool:
    status = record.seed.get("verification_status") or record.payload.get("verification_status")
    return status == "web_verified"


def _missing(record: Record) -> list[str]:
    return [label for column, label in CORE_FIELDS.items() if not record.flat[column].strip()]


def _flags(record: Record) -> list[str]:
    flags: list[str] = []
    if not _verified(record):
        flags.append("unverified")
    if record.loc.get("location_type") == relational.POSTAL_LOCATION_TYPE:
        flags.append("PO Box only (Postal location)")
    email = record.flat["Email"]
    if email and _source(record, "email") == "pipeline":
        freemail = email.rsplit("@", 1)[-1].lower() in FREEMAIL
        flags.append("email not hand-verified" + (" (free-mail)" if freemail else ""))
    address = record.flat["Primary_Location_Address"]
    if address and not geo.find_city(address, record.county):
        flags.append("address names no in-county community")
    if record.website_ok is False:
        flags.append(f"website did not load ({record.website_detail})")
    if not record.reproduces:
        flags.append("differs from current export code")
    return flags


def _categories(record: Record) -> list[str]:
    return [c.strip() for c in record.flat["Primary_Resources_Services"].split(",") if c.strip()]


# --- output -----------------------------------------------------------------


def _write_csv(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def _validation_row(record: Record) -> dict[str, str]:
    missing = _missing(record)
    return {
        "County": f"{record.county} County",
        "Org_Agency_Name": record.name,
        "Organization_ID": record.flat["Organization_ID"],
        "Location_ID": record.flat["Location_ID"],
        "Verification": "web_verified" if _verified(record) else "unverified",
        "Agency_Type_Level": f"{record.flat['Org_Agency_Type'] or '-'}/{record.flat['Org_Agency_Level'] or '-'}",
        "Location_Type": record.loc.get("location_type", ""),
        "Address_Source": _source(record, "address"),
        "Phone_Source": _source(record, "phone"),
        "Email_Source": _source(record, "email"),
        "Summary_Source": _summary_source(record),
        "Website_Check": (
            "" if record.website_ok is None else ("ok" if record.website_ok else "failed") + f" ({record.website_detail})"
        ),
        "Complete": "yes" if not missing else "no",
        "Missing": "; ".join(missing),
        "Flags": "; ".join(_flags(record)),
    }


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({round(100 * n / d)}%)" if d else "0/0"


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def render_report(
    counties: list[str],
    records: list[Record],
    checks: list[tuple[str, bool | None, str]],
    stem: str,
    checked_websites: bool,
) -> str:
    by_county = {c: [r for r in records if r.county == c] for c in counties}
    collected = sorted({r.payload.get("scraped_at", "")[:10] for r in records if r.payload.get("scraped_at")})
    out: list[str] = []
    add = out.append

    add(f"# {_join(counties)} counties — final data report")
    add(f"**Generated:** {date.today().isoformat()}")
    add(f"**Data collected:** {', '.join(collected) or 'unknown'}; hand-verified seed values as of generation")
    add("**Scope:** domestic and sexual violence, housing and maternal health resources with a physical "
        "office in the county. Nonprofit, government and tribal programs; for-profit providers are excluded.")
    add("")
    add("## Deliverables")
    add("| File | Contents |")
    add("|---|---|")
    add(f"| `{stem}_snmp.csv` | {len(records)} rows in the Map Database layout: the 28 sheet columns plus Organization_ID and Location_ID |")
    add(f"| `{stem}_snmp_organizations.csv` | Organization table, workbook layout |")
    add(f"| `{stem}_snmp_locations.csv` | Location table, workbook layout |")
    add(f"| `{stem}_validation.csv` | One row per organization: where each value came from, gaps and flags |")
    add("")
    add("All files are in `data/output/`, next to this report.")
    add("")

    add("## Headline numbers")
    add("| County | Orgs | Street address | PO Box only | Phone | Email | Website | Summary | All five fields | Verified |")
    add("|---|---|---|---|---|---|---|---|---|---|")
    groups = [(f"{c} County", by_county[c]) for c in counties] + [("**Total**", records)]
    for label, rows in groups:
        n = len(rows)
        filled = {col: sum(1 for r in rows if r.flat[col].strip()) for col in CORE_FIELDS}
        postal = sum(1 for r in rows if r.loc.get("location_type") == relational.POSTAL_LOCATION_TYPE)
        complete = sum(1 for r in rows if not _missing(r))
        verified = sum(1 for r in rows if _verified(r))
        add(
            f"| {label} | {n} | {_pct(filled['Primary_Location_Address'], n)} | {postal} | "
            f"{_pct(filled['Phone'], n)} | {_pct(filled['Email'], n)} | {_pct(filled['URL'], n)} | "
            f"{_pct(filled['Services_Summary'], n)} | {_pct(complete, n)} | {_pct(verified, n)} |"
        )
    add("")
    add("\"All five fields\" means street address, phone, email, website and summary are all filled. "
        "\"Verified\" means the name, website and contact details were confirmed in at least two "
        "independent public sources.")
    add("")

    for title, key in (("By category", _categories), ("By agency type and level", None)):
        add(f"## {title}")
        add("| " + ("Category" if key else "Type / Level") + " | " + " | ".join(counties) + " | Total |")
        add("|---" * (len(counties) + 2) + "|")
        tallies: dict[str, Counter] = defaultdict(Counter)
        for r in records:
            values = key(r) if key else [f"{r.flat['Org_Agency_Type'] or '-'} / {r.flat['Org_Agency_Level'] or '-'}"]
            for v in values:
                tallies[v][r.county] += 1
        for value in sorted(tallies, key=lambda v: -sum(tallies[v].values())):
            counts = [str(tallies[value][c]) for c in counties]
            add(f"| {value} | " + " | ".join(counts) + f" | {sum(tallies[value].values())} |")
        add("")
        if key:
            add("An organization can appear in more than one category.")
            add("")

    add("## Integrity checks")
    add("| Check | Result |")
    add("|---|---|")
    for description, passed, detail in checks:
        result = "pass" if passed else ("FAIL" if passed is False else detail)
        if passed is not None and detail:
            result += f" ({detail})"
        add(f"| {description} | {result} |")
    add("")

    add("## Where the values come from")
    add("| Field | Hand-verified seed | Pipeline (website or IRS record) | Missing |")
    add("|---|---|---|---|")
    for label, key in (("Address", "address"), ("Phone", "phone"), ("Email", "email")):
        tally = Counter(_source(r, key) for r in records)
        add(f"| {label} | {tally['seed']} | {tally['pipeline']} | {tally['none']} |")
    summary = Counter(_summary_source(r) for r in records)
    add("")
    add(f"Summaries: {summary['seeded mission']} are the organization's own mission statement copied in by hand, "
        f"{summary['scraped mission']} were extracted from the organization's own website, and "
        f"{summary['written description']} are written descriptions.")
    add("")

    add("## Open issues")
    flagged: dict[str, list[str]] = defaultdict(list)
    for r in records:
        for flag in _flags(r):
            flagged[flag].append(f"{r.name} ({r.county})")
    if not flagged:
        add("None.")
    for flag in sorted(flagged, key=lambda f: (-len(flagged[f]), f)):
        add(f"- **{flag[0].upper() + flag[1:]}** ({len(flagged[flag])}): {'; '.join(flagged[flag])}")
    add("")
    missing = Counter(label for r in records for label in _missing(r))
    if missing:
        add("Missing fields: " + ", ".join(f"{label} {count}" for label, count in missing.most_common()) + ".")
        add("")

    notes = [(r.county, r.name, marker, text) for r in records for marker, text in r.notes]
    if notes:
        add("## Research notes from the seed files")
        add("These are recorded as comments in the seed files and are not visible in the export.")
        add("")
        add("| County | Organization | Note |")
        add("|---|---|---|")
        for county, name, marker, text in notes:
            add(f"| {county} | {name} | **{marker}:** {text.replace('|', '/')} |")
        add("")

    add("## Organizations")
    for county in counties:
        rows = by_county[county]
        add(f"### {county} County ({len(rows)})")
        add("| Organization | Category | Type / Level | Verified | Gaps and flags |")
        add("|---|---|---|---|---|")
        for r in rows:
            gaps = [f"no {m}" for m in _missing(r)] + _flags(r)
            gaps = [g for g in gaps if g != "unverified"]
            add(
                f"| {r.name} | {', '.join(_categories(r))} | "
                f"{r.flat['Org_Agency_Type'] or '-'} / {r.flat['Org_Agency_Level'] or '-'} | "
                f"{'yes' if _verified(r) else 'no'} | {'; '.join(gaps) or '—'} |"
            )
        add("")

    add("## Notes and limitations")
    add("- `Operations_Status` is always \"Normal operations\", so the service changes above are not reflected in the export.")
    add(f"- The {len(snmp.MANUAL_COLUMNS)} Map Database columns this tool can't fill from public sources "
        "(hours, eligibility, parent organization and so on) are left blank for manual entry.")
    add("- An address that is only a PO Box is exported as a Postal location: the Location table keeps the box, "
        "and the Map Database's `Primary_Location_Address` is blank because a box can't be mapped.")
    add("- `Org_Agency_Level` defaults to City for nonprofits, County for government and Tribal for tribal "
        "programs, unless a seed sets `agency_level`.")
    add("- Emails for government and tribal programs come only from the seed files; the pipeline does not "
        "scrape them from shared government websites.")
    if checked_websites:
        add(f"- Websites were checked live on {date.today().isoformat()}. Servers that refuse this machine's "
            "Python TLS library were re-checked with curl.")
    else:
        add("- Websites were not checked live for this report (run with `--check-urls`).")
    add("")
    return "\n".join(out)


def build(counties: list[str], output_dir: Path, stem: str, check_urls: bool) -> dict[str, Path]:
    records: list[Record] = []
    metas: dict[str, dict] = {}
    for county in counties:
        county_records, meta = load_county(county, output_dir)
        records.extend(county_records)
        metas[county] = meta

    if check_urls:
        targets = [r for r in records if r.flat["URL"]]
        with ThreadPoolExecutor(max_workers=12) as pool:
            for record, (ok, detail) in zip(targets, pool.map(lambda r: _check_website(r.flat["URL"]), targets)):
                record.website_ok, record.website_detail = ok, detail

    loc_ids = [r.flat["Location_ID"] for r in records]
    org_ids = [r.flat["Organization_ID"] for r in records]
    shared_orgs = sum(1 for count in Counter(org_ids).values() if count > 1)
    checks: list[tuple[str, bool | None, str]] = [
        ("Column headers match the export layout", all(m["headers_ok"] for m in metas.values()), ""),
        ("Headers match SNMP_Main.xlsx", None, _workbook_headers_match()),
        ("Row counts agree across the flat, Organization, Location and JSONL files",
         all(m["counts_ok"] for m in metas.values()), ""),
        ("Every organization has a seed entry", sum(m["seeded"] for m in metas.values()) == len(records),
         f"{sum(m['seeded'] for m in metas.values())}/{len(records)}"),
        ("Location_IDs are unique", len(set(loc_ids)) == len(loc_ids), ""),
        ("All IDs are deterministic UUIDv5",
         all(uuid.UUID(i).version == 5 for i in loc_ids + org_ids), ""),
        ("Every location points to an existing organization", all(m["orphans"] == 0 for m in metas.values()), ""),
        ("Every row reproduces exactly with the current export code",
         all(r.reproduces for r in records), f"{sum(r.reproduces for r in records)}/{len(records)}"),
        ("Organizations listed in more than one county", None, str(shared_orgs)),
    ]
    if check_urls:
        ok = sum(1 for r in records if r.website_ok)
        tried = sum(1 for r in records if r.website_ok is not None)
        checks.append(("Websites load", ok == tried, f"{ok}/{tried}"))

    order = {c: i for i, c in enumerate(counties)}
    records.sort(key=lambda r: (order[r.county], r.name.lower()))
    first = metas[counties[0]]
    paths = {
        "flat": output_dir / f"{stem}_snmp.csv",
        "organizations": output_dir / f"{stem}_snmp_organizations.csv",
        "locations": output_dir / f"{stem}_snmp_locations.csv",
        "validation": output_dir / f"{stem}_validation.csv",
        "report": output_dir / f"{stem}_report.md",
    }
    _write_csv(paths["flat"], first["flat_header"], [r.flat for r in records])
    # An organization with offices in two counties has one Organization row.
    seen: set[str] = set()
    org_rows = []
    for r in records:
        if r.org and r.org["organization_id"] not in seen:
            seen.add(r.org["organization_id"])
            org_rows.append(r.org)
    _write_csv(paths["organizations"], first["org_header"], org_rows)
    _write_csv(paths["locations"], first["loc_header"], [r.loc for r in records])
    _write_csv(paths["validation"], list(VALIDATION_COLUMNS), [_validation_row(r) for r in records])
    paths["report"].write_text(render_report(counties, records, checks, stem, check_urls), encoding="utf-8")
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--county", action="append", default=[], help="County to include; repeatable.")
    parser.add_argument("--name", default=DEFAULT_STEM, help=f"Output file stem (default {DEFAULT_STEM}).")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--check-urls", action="store_true", help="Check every website live.")
    args = parser.parse_args(argv)
    counties = args.county or list(DEFAULT_COUNTIES)
    paths = build(counties, args.output_dir, args.name, args.check_urls)
    for path in paths.values():
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
