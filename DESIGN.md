# Oregon NGO Scraper — Design (1 page)
## Goal
Collect the **mission and values statements** of Oregon NGO/non-profit/grassroots
organizations working on (a) Domestic & Sexual Violence, (b) Housing
insecurity/stability, and (c) Maternal Health. Output is a flat CSV plus
one plain-text file per mission for downstream qualitative analysis.
## Two-stage pipeline
```
sources ──┐                                                  ┌── orgs.csv
seed/xlsx │  Discovery   Resolver    Crawler    Extractor    │  orgs.jsonl
HTTP APIs ├─►  (dedup) ─►(homepage)─►(/about,──►(mission &  ─┤
HTML dirs │              if missing  /mission, etc.) values) │  missions/
          └─►                          ↓                      └── <slug>.txt
                                  PageCrawler ↔ Browser fallback
```
1. **Discovery** — every source yields partial `Organization` records that get
   merged on the dedup key (`EIN > website-host > normalized name`). Sources:
   - `XlsxStarterListDiscovery` — the 94-row Voices Project starter spreadsheet (canonical, runs first).
   - `OcadsvDiscovery` — OCADSV Coalition Members page → DSV-tagged orgs.
   - `ProPublicaDiscovery` — paginates the free Nonprofit Explorer API filtered to OR + relevant NTEE codes.
   - `LinkListDiscovery` (Housing Alliance, Maternal Health), `OregonSosDiscovery`, `SeedDiscovery` (YAML).
2. **Extraction** (per org)
   - If no website, `HomepageResolver` queries the injected `SearchEngine` (DuckDuckGo HTML; no key) and picks a plausible `.org` matching the name, filtering social/aggregator hosts.
   - `PageCrawler` walks `/`, `/about`, `/about-us`, `/mission`, `/our-mission`, `/who-we-are`, `/what-we-do`, `/values`, plus any nav links matching `(?i)mission|about|values|what we do`.
   - `MissionExtractor` (pure, no I/O) finds an `<h1..h4>` matching `^our? mission( statement)?$` and concatenates the following sibling `<p>`/`<li>` content; same for values; falls back to a `Our mission is …` phrase match.
   - `FilesystemMissionStore` writes `data/output/missions/<slug>[-<ein>].txt` with a header (name, URL, source URL, scrape time) and the raw text; the relative path is recorded in `mission_file`.
   - `CsvStorage` upserts on the same dedup key, merging facts, and atomically rewrites `orgs.csv` + `orgs.jsonl` after every org so an interrupted run keeps everything completed so far.
## Architecture rules
- **Constructor-based DI everywhere.** Every collaborator that performs I/O is declared as a `typing.Protocol` in `protocols.py` (`HttpClient`, `Browser`, `SearchEngine`, `Clock`, `Storage`, `MissionStore`, `RobotsChecker`, `DiscoverySource`). Production adapters are wired *only* in `cli.py`; the rest of the code never imports `requests`, `playwright`, etc.
- **Pure where possible.** `MissionExtractor` operates on pre-fetched HTML strings and emits a `MissionResult` dataclass — no network, trivially unit-testable.
- **Polite + resilient HTTP.** `RequestsHttpClient` enforces 1 req/sec per host, a 5/10 s connect/read timeout, and `connect=0` retries so a NXDOMAIN host fails in <15 s instead of stalling the run for minutes.
- **Idempotent.** Re-running converges; the dedup key is stable across sources, and mission `.txt` files are overwritten in place.
## Output
- `data/output/orgs.csv` — one row per org. Mission text is intentionally **not** in the CSV; the `mission_file` column points to the `.txt`.
- `data/output/orgs.jsonl` — full JSON sidecar (includes mission text for machine consumers).
- `data/output/missions/<slug>.txt` — one mission per file, header + body.
## Testing & extension
- `pytest` with 44 tests, 100 % offline, coverage ≥ 80 % on the core modules. Fakes (`FakeHttpClient`, `FakeSearchEngine`, `FakeBrowser`, `FixedClock`, `InMemoryStorage`) live in `tests/conftest.py`; captured HTML/JSON in `tests/fixtures/`.
- Adding a new discovery source = one class implementing `DiscoverySource` + a tiny test that feeds it a fixture HTML/JSON via a `FakeHttpClient`. No core changes required.
