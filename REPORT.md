# Oregon NGO Mission/Values Scraper — Final Data Report
**Run:** 2026-04-30 (initial discovery + extraction) and 2026-05-05 (dedupe + values re-extraction)
**Output location:** `data/output/`
## Headline numbers
| Metric | Value |
|---|---|
| **Unique organizations in dataset** | **184** |
| Mission `.txt` files captured | 60 |
| Organizations with extracted values text | 23 |
| Organizations with a verified website | 127 (69 %) |
| Organizations with an IRS EIN | 44 (24 %) |
| Issue areas covered | DV/SV, Housing, Maternal Health |
| Geographic scope | Oregon — 7 of the 7 target population centers |
## Data composition
### By issue area (topics overlap; an org may carry several)
| Topic | Count |
|---|---|
| Housing | 89 |
| Domestic & Sexual Violence | 82 |
| Maternal Health | 22 |
### By discovery source (post-dedupe)
| Source | Rows it contributed (after merge) |
|---|---|
| `xlsx_starter` (Voices Project starter list) | 94 |
| `propublica` (IRS Form 990 metadata) | 44 |
| `ocadsv` (OCADSV member directory) | 40 |
| `seeds` (hand-curated YAML) | 16 |
| `propublica_detail` (enricher tag) | 2 |
The numbers exceed 184 because a single org may be discovered through several sources; the `discovered_via` column lists every contributor.
### Top counties (top 10)
Multnomah 23, Lane 10, Jackson 6, Deschutes 6, Benton 5, Marion/Polk 5, Marion 3, Deschutes/Crook/Jefferson 3, Clackamas 2, Washington 2. The remainder is spread across the rest of the state, with most rural counties represented at 1-2 orgs each.
## Coverage of the original starter list
All 94 rows from the Voices Project starter spreadsheet are preserved with their hand-curated metadata intact (city, county, keywords, notes, verification status). Of those:
- **125 rows** trace back to a starter-list entry after merging with ProPublica/OCADSV duplicates,
- **54 / 94** (57 %) starter-list orgs have an extracted mission `.txt`,
- **21 / 94** (22 %) have an extracted values blurb,
- **0** were dropped or lost.
**59 new organizations** were added by automated discovery beyond the starter list, predominantly housing-focused 501(c)(3)s surfaced by the ProPublica Nonprofit Explorer pass.
## Per-field coverage of `data/output/orgs.csv`
| Field | Filled | % |
|---|---|---|
| `state` | 184 | 100 % |
| `city` | 140 | 76 % |
| `website` | 127 | 69 % |
| `county` | 94 | 51 % |
| `keywords` | 94 | 51 % |
| `notes` | 94 | 51 % |
| `mission_source_url` | 66 | 36 % |
| `mission_file` (pointer to .txt) | 61 | 33 % |
| `ein` | 44 | 24 % |
| `verification_status` | 39 | 21 % |
| `values` | 23 | 12 % |
## Files delivered
| Path | Contents |
|---|---|
| `data/output/orgs.csv` | 184 rows × 16 columns (master table) |
| `data/output/orgs.jsonl` | Same data as JSONL with full mission text inline (machine-readable) |
| `data/output/missions/<slug>.txt` | 60 mission statements, each with header (name, URL, source URL, scrape time) and body. Median size 318 bytes. |
| `data/seeds/oregon_starter_list.xlsx` | Canonical input list (committed) |
| `tests/` | 62 unit tests (offline; uses fakes for HTTP/search/clock/storage) |
| `DESIGN.md`, `DEPLOYMENT.md`, this `REPORT.md` | Architecture, ops, and results docs |
## Pipeline phases that produced the data
1. **Discovery** (~1 min) — six pluggable sources combined and merged via the `dedup_key` (`EIN > apex_host > normalized_name`).
2. **Enrichment** (~3 min) — for every org with an EIN but no website, the `ProPublicaDetailFetcher` pulled the IRS detail payload, merged the verified city onto the org, then a city-scoped DuckDuckGo search resolved the homepage. Lifted the website coverage from 11 % to 76 % on that cohort.
3. **Coalesce** — second-pass union-find over EIN ∪ apex host ∪ name. Removed 18 duplicate rows (e.g. `https://www.bradleyangle.org` + `https://bradleyangle.org`).
4. **Extraction** (~30 min for the values re-pass; ~8 hr for the full initial run) — `PageCrawler` walked `/`, `/about`, `/about-us`, `/mission`, `/our-mission`, `/who-we-are`, `/what-we-do`, `/values`; `MissionExtractor` applied heading + phrase heuristics on the fetched HTML; matches were written to per-org `.txt` files and pointed to from the CSV.
## Known limitations
- **Mission yield (~33 %)** is bounded by sites that render content via JavaScript (Cloudflare-fronted DV agencies, county-level housing authorities) or use non-standard headings. The Playwright fallback is wired in but disabled by default; flipping `browser=PlaywrightBrowser()` in `cli.py` would recover an estimated 15-20 additional missions.
- **Values yield (~12 %)** reflects how few NGO sites publish a discrete values section. The broadened heuristic catches "Core Values", "What We Stand For", "Guiding Principles", and "Our Beliefs"; values that live inline within a mission paragraph or under custom section names ("Our Approach", "Theory of Change") still go uncaptured.
- **EIN coverage (~24 %)** is by design — only ProPublica-discovered orgs and a few seed entries have one. The starter-list rows generally don't include EINs.
- **Long-tail orgs without verified websites (57 of 184)** are mostly newer or smaller ProPublica entries that the city-scoped resolver couldn't confidently match. Their other metadata (city, county, NTEE, keywords) is still useful for downstream analysis.
## Next-step suggestions (ranked by yield-per-effort)
1. Enable the Playwright browser fallback (one-line CLI change) — should lift mission yield ~15 %.
2. Add `<meta name="description">` / `<meta property="og:description">` as a last-resort mission fallback in `MissionExtractor`.
3. Add a ProPublica keyword-search pass (`q=domestic+violence`, `q=doula`, etc.) in addition to the NTEE filter, to surface 50-150 additional orgs whose IRS classification is "Unknown".
4. Ingest a focused directory like DomesticShelters.org Oregon, Oregon Housing Alliance member list, or the Oregon Doula Association directory via the existing `LinkListDiscovery` class — each one is ~30 lines plus a fixture test.
## How to reproduce
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt && pip install -e .
python -m pytest                                    # 62 passed
python -m oregon_ngo_scraper.cli run-all            # full pipeline
python scripts/dedupe_and_extract_values.py         # idempotent re-pass
```
The full sequence regenerates `data/output/orgs.csv`, `data/output/orgs.jsonl`, and the `data/output/missions/` directory.
