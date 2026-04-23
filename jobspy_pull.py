#!/usr/bin/env python3
"""
jobspy_pull.py — JobSpy pipeline for OpenClaw career-ops

Scrapes jobs from multiple boards, deduplicates against the career-ops
processed-urls database and pipeline.md, writes results to the inbox, and
updates pipeline.md with only the new pending jobs.

Usage:
  python3 jobspy_pull.py
  python3 jobspy_pull.py --dry-run
  python3 jobspy_pull.py --terms "python developer" --location "Remote"
"""

import argparse
import json
import os
import re
import sys
import csv
from datetime import datetime
from pathlib import Path

# Use the career-ops venv
VENV_PATH = Path(__file__).parent / ".venv"
VENV_SITE = VENV_PATH / "lib" / "python3.12" / "site-packages"
sys.path.insert(0, str(VENV_SITE))

from jobspy import scrape_jobs
import pandas as pd

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config" / "search-profile.json"
PROCESSED_FILE = BASE_DIR / "data" / "processed-urls.tsv"
SCAN_HISTORY = BASE_DIR / "data" / "scan-history.tsv"
PIPELINE_FILE = BASE_DIR / "data" / "pipeline.md"
INBOX_DIR = BASE_DIR / "artifacts" / "inbox"

# ── Helpers ────────────────────────────────────────────────────────────────────

def load_config():
    """Load search profile from config/search-profile.json."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    # Sensible defaults if config is missing
    return {
        "search_terms": ["python developer", "AI engineer", "software developer"],
        "locations": ["Tallahassee, FL", "Remote"],
        "sites": ["linkedin", "indeed", "zip_recruiter", "google"],
        "results_wanted": 20,
        "hours_old": 48,
        "linkedin_max_per_run": 20,
        "linkedin_max_per_day": 200,
        "country": "USA",
    }


def load_processed_urls():
    """Load all URLs already processed from TSV files and pipeline.md LINKS section."""
    processed = set()

    # processed-urls.tsv  (url \t date \t timestamp)
    if PROCESSED_FILE.exists():
        with open(PROCESSED_FILE) as f:
            for line in f:
                parts = line.strip().split("\t")
                if parts and parts[0].startswith("http"):
                    processed.add(parts[0].lower())

    # scan-history.tsv
    if SCAN_HISTORY.exists():
        with open(SCAN_HISTORY) as f:
            for line in f:
                parts = line.strip().split("\t")
                if parts and parts[0].startswith("http"):
                    processed.add(parts[0].lower())

    # pipeline.md LINKS section
    if PIPELINE_FILE.exists():
        in_links = False
        with open(PIPELINE_FILE) as f:
            for line in f:
                if "<!-- LINKS -->" in line:
                    in_links = True
                    continue
                if in_links:
                    if line.startswith("#") or line.startswith("|") or line.startswith("!"):
                        break
                    urls = re.findall(r"https?://\S+", line)
                    for url in urls:
                        processed.add(url.lower().rstrip(")").rstrip(","))

    return processed


def parse_relative_time(relative_str):
    """
    Convert a JobSpy relative date string (e.g. '2h ago', '3d ago')
    to a human-readable string. Returns the original if parsing fails.
    """
    if not isinstance(relative_str, str):
        return relative_str or "unknown"
    return relative_str  # passthrough — pipeline.md stores as-is


def build_pipeline_table(jobs_df, max_rows=50):
    """
    Build a markdown table from a DataFrame of new jobs.
    Only includes the first max_rows rows.
    """
    lines = []
    lines.append("## Pending Applications\n")
    lines.append("| # | Company | Role | Location | Posted | URL |")
    lines.append("|---|---------|------|----------|--------|-----|")

    rows = jobs_df.head(max_rows).reset_index(drop=True)
    for i, row in rows.iterrows():
        num = i + 1
        company = (row.get("company") or "Unknown").replace("|", "\\|")
        title = (row.get("title") or "Unknown").replace("|", "\\|")
        location = (row.get("location") or "Unknown").replace("|", "\\|")
        posted = parse_relative_time(row.get("date_posted") or row.get("posted_at") or "")
        url = row.get("job_url_direct") or row.get("job_url") or ""
        lines.append(f"| {num} | {company} | {title} | {location} | {posted} | [Link]({url}) |")

    return "\n".join(lines)


def build_links_section(jobs_df, max_rows=50):
    """Build the raw URL list for the LINKS section."""
    rows = jobs_df.head(max_rows)
    urls = []
    for _, row in rows.iterrows():
        url = row.get("job_url_direct") or row.get("job_url") or ""
        if url:
            urls.append(url)
    return "\n".join(urls)


def write_pipeline(jobs_df):
    """
    Write pipeline.md with the clean table + LINKS section.
    Only the most recent max_rows jobs go into the table; older ones
    are still marked as processed in processed-urls.tsv.
    """
    PIPELINE_FILE.parent.mkdir(parents=True, exist_ok=True)

    table_md = build_pipeline_table(jobs_df)
    links = build_links_section(jobs_df)

    content = table_md + "\n\n<!-- LINKS -->\n" + links + "\n"
    PIPELINE_FILE.write_text(content)


def append_processed_urls(jobs_df):
    """Append new job URLs to processed-urls.tsv (append-only TSV)."""
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    urls_written = 0
    with open(PROCESSED_FILE, "a") as f:
        for _, row in jobs_df.iterrows():
            url = row.get("job_url_direct") or row.get("job_url") or ""
            if not url:
                continue
            f.write(f"{url}\t{today}\t{timestamp}\n")
            urls_written += 1

    return urls_written


def write_csv(jobs_df, timestamp):
    """Write a timestamped CSV to artifacts/inbox/."""
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"jobspy_{timestamp}.csv"
    filepath = INBOX_DIR / filename

    if jobs_df.empty:
        return None

    output_cols = [
        "title", "company", "location", "job_url", "job_url_direct",
        "site", "date_posted", "job_type", "min_amount", "max_amount",
        "currency", "is_remote", "description", "emails", "skills",
    ]
    available = [c for c in output_cols if c in jobs_df.columns]
    jobs_df[available].to_csv(filepath, index=False)
    return filepath


def run_search(sites, term, location, results_wanted, hours_old, country, linkedin_max_per_run):
    """
    Run JobSpy for one term × location combo.
    Applies LinkedIn per-run cap and skips glassdoor (permanently blocked).
    """
    actual_results = results_wanted
    if "linkedin" in sites:
        actual_results = min(results_wanted, linkedin_max_per_run)

    working_sites = [s for s in sites if s != "glassdoor"]
    if len(working_sites) < len(sites):
        print(f"  [glassdoor excluded — site blocked]")

    try:
        jobs = scrape_jobs(
            site_name=working_sites,
            search_term=term,
            location=location,
            results_wanted=actual_results,
            hours_old=hours_old,
            country_indeed=country,
            linkedin_fetch_description=True,
        )
        return jobs
    except Exception as e:
        # No traceback to stdout — just report the error message
        print(f"  Error ({term} @ {location}): {e}")
        return pd.DataFrame()


def main():
    parser = argparse.ArgumentParser(description="JobSpy pipeline for OpenClaw career-ops")
    parser.add_argument("--terms", help="Comma-separated search terms (overrides config)")
    parser.add_argument("--location", help="Single location (overrides config)")
    parser.add_argument("--sites", help="Comma-separated sites (overrides config)")
    parser.add_argument("--results", type=int, help="Results per search (overrides config)")
    parser.add_argument("--hours", type=int, help="Max job age in hours (overrides config)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be written, don't modify files")
    parser.add_argument("--no-dedupe", action="store_true", help="Skip deduplication")
    args = parser.parse_args()

    config = load_config()

    terms = [t.strip() for t in args.terms.split(",")] if args.terms else config["search_terms"]
    locations = [args.location] if args.location else config["locations"]
    sites = [s.strip() for s in args.sites.split(",")] if args.sites else config["sites"]
    results_wanted = args.results if args.results else config["results_wanted"]
    hours_old = args.hours if args.hours else config["hours_old"]
    linkedin_max_per_run = config.get("linkedin_max_per_run", 20)
    country = config.get("country", "USA")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"JobSpy Pull — {now_str}")
    print(f"Terms:      {terms}")
    print(f"Locations:  {locations}")
    print(f"Sites:      {sites}")
    print(f"Results:    {results_wanted} per search (LinkedIn cap: {linkedin_max_per_run})")
    print(f"Max age:    {hours_old}h")
    print("=" * 50)

    # ── Scrape ────────────────────────────────────────────────────────────────
    all_jobs = []
    for term in terms:
        for location in locations:
            print(f"\nSearching: '{term}' @ '{location}' ...")
            jobs = run_search(sites, term, location, results_wanted, hours_old, country, linkedin_max_per_run)
            if not jobs.empty:
                jobs["search_term"] = term
                jobs["search_location"] = location
                all_jobs.append(jobs)
                print(f"  → {len(jobs)} jobs found")
            else:
                print(f"  → no results")

    if not all_jobs:
        print("\nNo jobs found.")
        print(f"Found 0 new jobs (0 total scanned)")
        return

    combined = pd.concat(all_jobs, ignore_index=True)

    # ── Deduplicate ────────────────────────────────────────────────────────────
    total_before_dedupe = len(combined)

    if not args.no_dedupe:
        processed_urls = load_processed_urls()
        url_col = "job_url_direct" if "job_url_direct" in combined.columns else "job_url"
        combined["_url_lower"] = combined[url_col].str.lower()
        combined = combined[~combined["_url_lower"].isin(processed_urls)]
        combined = combined.drop(columns=["_url_lower"])

    total_new = len(combined)

    # ── Dry run ───────────────────────────────────────────────────────────────
    if args.dry_run:
        print(f"\nDRY RUN — {total_new} new jobs would be written:")
        for _, row in combined.head(10).iterrows():
            print(f"  [{row.get('site','?')}] {row.get('title','?')} @ {row.get('company','?')}")
        print(f"\nFound {total_new} new jobs ({total_before_dedupe} total scanned)")
        return

    # ── Write outputs ─────────────────────────────────────────────────────────
    csv_path = write_csv(combined, timestamp)
    append_processed_urls(combined)
    write_pipeline(combined)

    # ── Summary ────────────────────────────────────────────────────────────────
    site_counts = combined["site"].value_counts().to_dict() if "site" in combined.columns else {}
    site_str = ", ".join(f"{k}:{v}" for k, v in site_counts.items())

    print(f"\nFound {total_new} new jobs ({total_before_dedupe} total scanned)")
    if site_str:
        print(f"By site: {site_str}")
    if csv_path:
        print(f"CSV: {csv_path}")
