# career-ops JobSpy Pipeline

Scrapes jobs from LinkedIn, Indeed, ZipRecruiter, and Google Jobs using [JobSpy](https://github.com/GeorgioJobSpy), deduplicates against the career-ops processed-urls database, and writes fresh results to the inbox for review.

---

## File Structure

```
career-ops/
├── jobspy_pull.py              # Main scraper script
├── config/
│   └── search-profile.json    # Search terms, locations, sites, limits
├── data/
│   ├── pipeline.md            # Pending jobs table (clean format)
│   ├── processed-urls.tsv     # Append-only log of scraped URLs
│   └── scan-history.tsv       # Historical scan log (dedupe source)
├── artifacts/
│   └── inbox/                 # Timestamped CSV output from each run
└── README.md
```

---

## How to Run

```bash
cd /root/career-ops
source .venv/bin/activate
python3 jobspy_pull.py
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `--terms "a,b"` | Override search terms | from `search-profile.json` |
| `--location "City"` | Override single location | from `search-profile.json` |
| `--sites "a,b"` | Override sites | from `search-profile.json` |
| `--results N` | Results per search | from `search-profile.json` |
| `--hours N` | Max job age in hours | from `search-profile.json` |
| `--dry-run` | Preview without writing files | false |
| `--no-dedupe` | Skip deduplication | false |

---

## What the Pipeline Does

1. **Scrape** — Runs JobSpy for each term × location × site combo.
2. **Deduplicate** — Removes jobs already in `processed-urls.tsv`, `scan-history.tsv`, and the current `pipeline.md` LINKS section (case-insensitive on URL).
3. **Write CSV** — Saves fresh jobs to `artifacts/inbox/jobspy_YYYYMMDD_HHMM.csv`.
4. **Update pipeline.md** — Writes a clean table of the most recent 50 new jobs with a raw LINKS section.
5. **Append processed URLs** — Adds new job URLs to `data/processed-urls.tsv`.

---

## LinkedIn Safety

LinkedIn is capped at `linkedin_max_per_run` results per run (default: 20) to avoid rate-limiting. The daily total is tracked via `linkedin_max_per_day` in the config (informational).

---

## Output Format

### pipeline.md

```
## Pending Applications

| # | Company | Role | Location | Posted | URL |
|---|---------|------|----------|--------|-----|
| 1 | Acme Corp | Python Developer | Remote | 2h ago | [Link](https://...) |

<!-- LINKS -->
https://job-url-1.com
https://job-url-2.com
```

### processed-urls.tsv (append-only)

```
url	date_processed	timestamp
https://job-url-1.com	2026-04-23	2026-04-23 20:46:00
```

---

## Notes

- No external APIs required — JobSpy scrapes job boards directly.
- `search-profile.json` is the single source of truth for search config.
- All paths are relative to the script location — no hardcoded paths.
- Errors are reported silently (no tracebacks) to keep cron output clean.
