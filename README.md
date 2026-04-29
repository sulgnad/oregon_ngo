# Oregon NGO Mission/Values Scraper

A two-stage Python tool for collecting **mission and values statements** from
Oregon-based NGO/non-profit/grassroots organizations working on:

1. **Domestic & Sexual Violence** (DSV)
2. **Housing insecurity / stability**
3. **Maternal Health**

Designed and built for OPAL (Oregon Policy Analysis Laboratory) research.

## How it works

The tool runs in two stages:

1. **Discovery** — pluggable sources combine to produce a deduplicated list of
   candidate organizations:
   - **Voices Project starter spreadsheet**
     (`data/seeds/oregon_starter_list.xlsx`) — the canonical hand-curated
     input (~94 orgs across Eugene, Corvallis, Salem, Bend, La Grande,
     Medford, Portland and surrounding counties)
   - OCADSV member programs and Find Help directory (DSV)
   - ProPublica Nonprofit Explorer API filtered to Oregon (all topics)
   - Oregon Secretary of State active-nonprofit registry (cross-check)
   - Oregon Housing Alliance member list (housing)
   - Maternal-health coalition pages (maternal health)
   - A hand-curated YAML seed file (`data/seeds/seed_orgs.yml`)
2. **Extraction** — for every org we resolve a homepage URL (using DuckDuckGo
   HTML search if the source didn't provide one), crawl `/about`, `/about-us`,
   `/mission`, `/our-mission`, `/who-we-are`, `/what-we-do`, `/values`, etc.,
   and extract mission + values text via heading-based heuristics. Whenever
   a mission statement is found, its full text is also written to a per-org
   `.txt` file under `data/output/missions/` and the relative path is recorded
   in the `mission_file` column of the CSV.

Final output:
- `data/output/orgs.csv` — one row per organization
- `data/output/orgs.jsonl` — JSONL sidecar with the same data
- `data/output/missions/<slug>.txt` — one mission statement per file

## Architecture

The project is built around small, single-purpose classes wired together via
**constructor-based dependency injection**. Every collaborator that performs
I/O (HTTP, browser, clock, search, file system) is declared as a
`typing.Protocol` interface in `src/oregon_ngo_scraper/protocols.py` and
swapped for a fake in tests.

```
src/oregon_ngo_scraper/
├── models.py        # Organization, Topic, FetchedPage, MissionResult
├── protocols.py     # HttpClient, Browser, SearchEngine, Clock, Storage
├── http.py          # RequestsHttpClient (retry, throttle, UA)
├── browser.py       # PlaywrightBrowser (lazy, optional)
├── clock.py         # SystemClock
├── discovery/       # one module per source
├── search/          # DuckDuckGoSearch
├── resolver.py      # HomepageResolver(SearchEngine)
├── extractors/
│   ├── crawler.py   # PageCrawler(HttpClient, Browser)
│   └── mission.py   # MissionExtractor (pure, no I/O)
├── pipeline.py      # Orchestrator
├── storage.py       # CsvStorage
└── cli.py           # argparse entry point
```

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .
# optional, only needed for JS-rendered pages:
python -m playwright install chromium
```

## Run

```bash
# Discovery only (writes data/discovery/<source>.jsonl)
python -m oregon_ngo_scraper.cli discover

# Extraction over already-discovered orgs (writes data/output/orgs.csv)
python -m oregon_ngo_scraper.cli extract

# End-to-end
python -m oregon_ngo_scraper.cli run-all

# Limit to a single topic
python -m oregon_ngo_scraper.cli run-all --topic dsv
```

## Tests

```bash
python -m pytest             # all unit tests, no network
python -m pytest --cov       # with coverage report
```

All unit tests use injected fakes — there is no real network traffic. HTML and
JSON fixtures captured from real pages live under `tests/fixtures/`.

## Output schema (`data/output/orgs.csv`)

| column | description |
|---|---|
| `name` | Organization name |
| `website` | Homepage URL |
| `topics` | `;`-joined topic tags (`dsv`, `housing`, `maternal_health`) |
| `mission` | Extracted mission statement (single line, also written to a separate .txt file) |
| `values` | Extracted values statement |
| `mission_source_url` | Page URL the mission/values were extracted from |
| `mission_file` | Relative path to a `.txt` file containing the full mission text |
| `ein` | IRS EIN if known |
| `city` | City |
| `county` | Oregon county |
| `state` | State (always `OR` for v1) |
| `keywords` | `;`-joined preliminary keywords (carried over from the starter list) |
| `notes` | Free-form notes from the starter list (provider context, program names, etc.) |
| `verification_status` | `Verified` / `URL corrected` / `Location corrected` / `URL & location corrected` (from the starter list) |
| `discovered_via` | `;`-joined list of discovery source names |
| `scraped_at` | ISO-8601 timestamp |
