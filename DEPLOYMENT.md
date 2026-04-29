# Deployment & Operations

This document describes how to set up, run, troubleshoot, and re-deploy the
Oregon NGO mission/values scraper.

## 1. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | The code uses `dict[str, ...]` PEP-604 unions and Protocol typing. |
| pip / venv | bundled with Python 3 | |
| Working internet + DNS | required at runtime | Discovery and extraction make HTTPS requests to public sites. The unit tests are 100% offline. |
| Disk space | ~500 MB | Mostly Playwright's bundled Chromium if you install it. |
| (Optional) Playwright Chromium | matching `playwright` pin | Only needed for JS-heavy pages. |

## 2. First-time setup

```bash
git clone <your-fork-or-repo-url> oregon_ngo_scraper
cd oregon_ngo_scraper

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements-dev.txt   # runtime + test deps
pip install -e .                       # installs the `oregon_ngo_scraper` package

# Optional, only needed if you plan to enable the Playwright fallback:
python -m playwright install chromium
```

Verify the install:

```bash
python -m pytest                       # expect: 44 passed
python -m oregon_ngo_scraper.cli --help
```

## 3. Provisioning data inputs

The scraper expects two files under `data/seeds/`:

- `oregon_starter_list.xlsx` — **required**. The Voices Project starter list.
  Already committed to the repository. To replace it, drop a new copy at the
  same path; the workbook must have an `Organizations` sheet with the columns
  `Organization Name | URL | City | County | Issue Area(s) | Keywords | Notes | Verification Status`.
- `seed_orgs.yml` — optional. Hand-curated YAML supplement; safe to leave empty.
- `oregon_sos.csv` — optional. A CSV exported from the Oregon SOS active
  nonprofit registry. If absent, that source contributes nothing; no errors.

## 4. Running the pipeline

```bash
# Discovery only (fast; no scraping). Prints the deduped org count.
python -m oregon_ngo_scraper.cli discover

# Extraction over discovered orgs. Writes:
#   data/output/orgs.csv
#   data/output/orgs.jsonl
#   data/output/missions/<slug>.txt   (one file per mission)
python -m oregon_ngo_scraper.cli run-all

# Scope to a single topic
python -m oregon_ngo_scraper.cli run-all --topic dsv
python -m oregon_ngo_scraper.cli run-all --topic housing
python -m oregon_ngo_scraper.cli run-all --topic maternal_health

# Crawl only the first N orgs (useful for smoke tests)
python -m oregon_ngo_scraper.cli extract --limit 5
```

Logs land in `logs/scraper.log` (rolling, append-only).

## 5. Output layout

```
data/output/
├── orgs.csv                  # one row per organization, with mission_file pointer
├── orgs.jsonl                # JSONL sidecar with the same data
└── missions/
    ├── bradley-angle.txt
    ├── raphael-house-of-portland.txt
    └── …                     # one .txt per org with a successfully scraped mission
```

Each `.txt` file has a short header (org name, website, source URL,
ISO-8601 scrape time) followed by the raw mission text.

## 6. Validating a deployment

After installing or upgrading on a new machine, run:

```bash
python -m pytest                                   # 44 passed (offline)
python -m oregon_ngo_scraper.cli discover          # should print "Discovered N unique organizations" with N ~ 90+
python -m oregon_ngo_scraper.cli extract --limit 3 # exercises the network path on a tiny slice
ls data/output/missions/                           # expect 1–3 .txt files
```

## 7. Operational settings worth knowing

- **HTTP politeness** — `RequestsHttpClient` defaults to `1 req/sec` per host
  with retry/backoff on `429/5xx`. Rate is configurable in `cli.py`.
- **User-Agent** — set in `src/oregon_ngo_scraper/http.py`
  (`OregonNGOResearch/0.1 (academic; contact: opal@oregonstate.edu)`). Update
  the email before first deployment if appropriate.
- **Idempotent re-runs** — discovery sources cache responses in
  `data/discovery/`, and `CsvStorage` merges by EIN/website/name on each
  upsert, so re-runs converge instead of duplicating rows. Mission `.txt`
  files are overwritten in place, keeping the directory tidy.

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'oregon_ngo_scraper'` when running the CLI | Editable install missing | `pip install -e .` from the repo root |
| `ModuleNotFoundError: openpyxl` | Stale virtualenv | `pip install -r requirements.txt` |
| `run-all` hangs on a single host with `Errno 8 nodename nor servname provided` | DNS resolution failure on the local machine | Check Wi-Fi, VPN, and `/etc/resolv.conf`. Test with `ping google.com` and `nslookup bradleyangle.org`. The scraper retries 3× before giving up; if DNS is broken every host will stall in turn. |
| Pipeline stalls on one slow site | Per-host retry/backoff plus polite throttle | Cancel with `Ctrl+C`; lower `retries` in `RequestsHttpClient` or pass `--limit` to skip. Consider running per-topic to bisect. |
| Extraction returns empty mission for many orgs | Site uses heavy JS rendering or non-standard headings | Install Playwright Chromium and switch the CLI's `browser = None` to `PlaywrightBrowser()` in `cli.py`; widen heuristics in `extractors/mission.py`. |
| Tests fail with import errors | `src/`-layout package not on path | Ensure `pip install -e .` was run, or set `PYTHONPATH=src`. |

## 9. Re-deploying after a code change

```bash
cd oregon_ngo_scraper
git pull
source .venv/bin/activate
pip install -r requirements-dev.txt   # in case dependencies changed
pip install -e .                       # picks up moved/added entry points
python -m pytest                       # gate the deploy
python -m oregon_ngo_scraper.cli run-all
```

## 10. Version control hygiene

`.gitignore` excludes the `.venv`, build artefacts, logs, and the generated
`data/output/` and `data/discovery/` payloads. The committed inputs are:

- `data/seeds/oregon_starter_list.xlsx`
- `data/seeds/seed_orgs.yml`
- everything under `src/`, `tests/`, and the project metadata files.

Generated mission `.txt` files and the CSV/JSONL outputs are intentionally
**not** committed — they are reproducible from the seeds plus a network run.
If you need to archive a particular run's results, copy `data/output/` to a
dated directory outside the repo (e.g. `~/runs/oregon_ngo_2026-04-29/`).
