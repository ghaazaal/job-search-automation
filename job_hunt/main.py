"""
main.py — Job Hunt Automation
==============================
Usage:
  python main.py                        # scrape + score + company intel + shortlist
  python main.py --tailor --jd job.txt  # tailor one job from a saved JD file

Setup:
  PowerShell:  $env:APIFY_TOKEN = "apify_api_..."
               $env:ANTHROPIC_API_KEY = "sk-ant-..."
  pip install -r requirements.txt
"""
import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────
_BASE = Path(__file__).resolve().parent
CONFIG_PATH   = _BASE / "config.yaml"
KEYWORDS_PATH = _BASE / "keywords.yaml"

# Load .env from the job_hunt/ directory (where this file lives).
# os.environ values already set take precedence — dotenv never overwrites them.
load_dotenv(_BASE / ".env")


def _load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Imports ───────────────────────────────────────────────────────────────────
# Deferred so missing deps give a clear message at startup, not mid-run
def _check_deps() -> None:
    missing = []
    for pkg in ("anthropic", "apify_client", "openpyxl", "yaml", "requests", "dotenv"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg.replace("_", "-"))
    if missing:
        print(f"ERROR: Missing packages: {', '.join(missing)}")
        print(f"Run: pip install -r {_BASE / 'requirements.txt'}")
        sys.exit(1)


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("main")


# ── Pipeline ──────────────────────────────────────────────────────────────────
def run_pipeline(config: dict) -> None:
    from src.scrapers import indeed as indeed_scraper
    from src.scrapers import linkedin as li_scraper
    from src.scoring.scorer import Scorer
    from src.agents.company_agent import lookup as company_lookup
    from src.filters.company_filter import CompanyFilter
    from src.agents.resume_agent import parse_resume, generate_role_variant
    from src.agents.tailoring_agent import shortlist_decision
    from src.tracker.cache import CompanyCache
    from src.tracker import excel

    output_dir = _BASE / config.get("output_dir", "output/")
    output_dir.mkdir(exist_ok=True)

    tracker_path = Path(config.get("tracker_path", "../job_tracker_ghazal.xlsx"))
    if not tracker_path.is_absolute():
        tracker_path = (_BASE / tracker_path).resolve()

    apify_cfg     = config.get("apify", {})
    search_cfg    = config.get("search", {})
    categories    = search_cfg.get("categories", [])
    days_posted   = search_cfg.get("days_posted", 7)
    jobs_per_cat  = search_cfg.get("jobs_per_category", 50)
    run_timeout   = search_cfg.get("run_timeout", 120)
    shortlist_min = config.get("tailoring", {}).get("shortlist_score", 7)

    print("=" * 62)
    print("  Job Hunt Automation — Ghazal Izadi")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 62)

    # ── 1. Parse resume ────────────────────────────────────────────────────
    print("\n[1/8] Parsing resume...")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  ERROR: ANTHROPIC_API_KEY not set. Abort.")
        sys.exit(1)
    try:
        parsed_resume = parse_resume(config, output_dir)
        print(f"  Skills: {', '.join(parsed_resume.get('skills', [])[:8])}")
    except Exception as e:
        print(f"  ERROR: Resume parse failed: {e}")
        sys.exit(1)

    # ── 2. Read existing tracker ───────────────────────────────────────────
    print("\n[2/8] Reading existing tracker...")
    existing = excel.read_existing(tracker_path)
    existing_urls = set(existing.keys())
    print(f"  Loaded {len(existing)} existing jobs.")

    # ── 3. Scrape ──────────────────────────────────────────────────────────
    if not os.environ.get("APIFY_TOKEN"):
        print("\n  ERROR: APIFY_TOKEN not set.")
        print("  PowerShell:  $env:APIFY_TOKEN = 'apify_api_xxx'")
        sys.exit(1)

    print(f"\n[3/8] Scraping Indeed + LinkedIn (last {days_posted} days)...")
    all_scraped: list[dict] = []
    for cat in categories:
        category, title = cat["category"], cat["title"]
        print(f"\n  Indeed / {category}...")
        jobs = indeed_scraper.scrape(
            category, title, apify_cfg.get("indeed_actor", "valig~indeed-jobs-scraper"),
            days_posted, jobs_per_cat, run_timeout)
        print(f"    -> {len(jobs)} fetched")
        all_scraped.extend(jobs)
        time.sleep(1)

        print(f"  LinkedIn / {category}...")
        jobs = li_scraper.scrape(
            category, title, apify_cfg.get("linkedin_actor", "valig~linkedin-jobs-scraper"),
            days_posted, jobs_per_cat, run_timeout)
        print(f"    -> {len(jobs)} fetched")
        all_scraped.extend(jobs)
        time.sleep(1)

    print(f"\n  Total scraped: {len(all_scraped)}")

    # ── 4. Deduplicate ─────────────────────────────────────────────────────
    print("\n[4/8] Deduplicating...")
    seen: set[str] = set()
    new_jobs: list[dict] = []
    for job in all_scraped:
        url = job["url"]
        if url in seen or url in existing_urls:
            continue
        seen.add(url)
        new_jobs.append(job)
    print(f"  {len(new_jobs)} new jobs")

    # ── 5. Company intel (concurrent) ─────────────────────────────────────
    unique_companies = list({j["company"] for j in new_jobs if j["company"]})
    print(f"\n[5/8] Fetching company intel ({len(unique_companies)} unique companies)...")
    cache = CompanyCache(ttl_days=config.get("company_filter", {}).get("cache_ttl_days", 7))
    company_intel: dict[str, dict] = {}

    def _fetch_intel(company: str) -> tuple[str, dict]:
        return company, company_lookup(company, config, cache)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_fetch_intel, c): c for c in unique_companies}
        for done_idx, fut in enumerate(as_completed(futures), start=1):
            c, intel = fut.result()
            company_intel[c] = intel
            if done_idx % 10 == 0:
                print(f"  {done_idx}/{len(unique_companies)} companies resolved")
    print(f"  Done — {len(company_intel)} companies resolved")

    # ── 6. Filter ──────────────────────────────────────────────────────────
    print("\n[6/8] Filtering...")
    filt = CompanyFilter(config)
    filtered_in: list[dict] = []
    filtered_out_count = 0
    for job in new_jobs:
        intel = company_intel.get(job["company"], {"stage": "unknown", "growth_score": 5})
        result = filt.evaluate(job["company"], intel)
        job["_intel"]  = intel
        job["_filter"] = result
        if result["verdict"] == "REJECT":
            filtered_out_count += 1
        else:
            filtered_in.append(job)
    print(f"  {len(filtered_in)} pass | {filtered_out_count} filtered out")

    # ── 7. Score ───────────────────────────────────────────────────────────
    print(f"\n[7/8] Scoring {len(new_jobs)} jobs...")
    scorer = Scorer(config, KEYWORDS_PATH)
    cat_order = {"Analytics Engineer": 0, "Data Engineer": 1,
                 "Data Analyst": 2, "Product Analyst": 3}
    rows: list[dict] = []

    for job in new_jobs:
        intel  = job["_intel"]
        filt_r = job["_filter"]
        is_filtered = filt_r["verdict"] == "REJECT"
        s = scorer.score_job(job["title"], job["cat"], job["salary"], job["url"])

        row: dict = {
            "Search Category":    job["cat"],
            "Job Title":          job["title"],
            "Company":            job["company"],
            "Location":           job["location"],
            "Platform":           job["platform"],
            "Posting Date":       job["date"],
            "Apply Link":         job["url"],
            "Match Score":        s["match_score"],
            "Interview Chance":   s["interview_chance"],
            "Tailoring Needed":   s["tailoring"],
            "Application Status": "Filtered Out" if is_filtered else "New",
            "Company Size":       intel.get("headcount_range", ""),
            "Company Stage":      intel.get("stage", ""),
            "Growth Score":       intel.get("growth_score", ""),
            "Intel Source":       intel.get("source", ""),
            "Apply_Now":          "",
            "LLM_Reason":         filt_r.get("reason", "") if is_filtered else "",
            "Risk_Flags":         "",
            "Date Applied":       "",
            "Follow-up Date":     "",
            "Notes":              filt_r.get("warn", "") or "",
            "_score":             s["match_score"],
            "_cat_order":         cat_order.get(job["cat"], 9),
            "Low Growth Signal":  bool(filt_r.get("warn")),
        }
        rows.append(row)

    rows.sort(key=lambda r: (r["_cat_order"], -r["_score"]))

    # ── 8. LLM shortlist decisions ─────────────────────────────────────────
    print(f"\n[8/8] LLM shortlist decisions (score >= {shortlist_min})...")
    shortlist = [r for r in rows
                 if r["_score"] >= shortlist_min
                 and r["Application Status"] != "Filtered Out"]
    print(f"  {len(shortlist)} jobs in shortlist")

    for row in shortlist:
        # Use cached role variant text if available
        safe_role = row["Search Category"].replace(" ", "_")
        variant_file = output_dir / f"resume_{safe_role}.txt"
        if variant_file.exists():
            resume_text = variant_file.read_text(encoding="utf-8")
        else:
            resume_text = parsed_resume.get("extracted_text", "")

        decision = shortlist_decision(
            job_description=f"{row['Job Title']} at {row['Company']}",
            resume_text=resume_text,
            role_title=row["Job Title"],
            company_name=row["Company"],
            match_score=row["_score"],
            config=config,
        )
        row["Apply_Now"]   = decision.get("apply_now", "")
        row["LLM_Reason"]  = decision.get("reason", "")
        row["Risk_Flags"]  = decision.get("risk_flags", "")

    # Pre-generate role variants for apply_now jobs
    apply_now_jobs = [r for r in rows if r.get("Apply_Now") == "yes"]
    if apply_now_jobs:
        print(f"\n  Generating resume variants for {len(apply_now_jobs)} apply-now jobs...")
        roles_needed = {r["Search Category"] for r in apply_now_jobs}
        for role in roles_needed:
            try:
                generate_role_variant(role, parsed_resume, config, output_dir)
            except Exception as e:
                logger.warning("Role variant failed for %s: %s", role, e)

    # ── Save ───────────────────────────────────────────────────────────────
    print(f"\n  Saving tracker...")
    if tracker_path.exists() and tracker_path.stat().st_size == 0:
        tracker_path.unlink()
    try:
        excel.save(tracker_path, rows)
    except PermissionError:
        print(f"\n  ERROR: Close {tracker_path.name} in Excel and retry.")
        sys.exit(1)

    # ── Summary ────────────────────────────────────────────────────────────
    high = [r for r in rows if r["_score"] >= 8
            and r["Application Status"] != "Filtered Out"]
    apply_now = [r for r in rows if r.get("Apply_Now") == "yes"]
    by_cat: dict[str, int] = {}
    by_platform = {"Indeed": 0, "LinkedIn": 0}
    for r in rows:
        by_cat[r["Search Category"]] = by_cat.get(r["Search Category"], 0) + 1
        by_platform[r["Platform"]] = by_platform.get(r["Platform"], 0) + 1

    print("\n" + "=" * 62)
    print(f"  Done!  {len(rows)} new jobs added.")
    print(f"  Filtered out: {filtered_out_count}  |  Shortlisted: {len(shortlist)}")
    print(f"  Apply_Now: {len(apply_now)}")
    if by_cat:
        print(f"\n  By platform: Indeed={by_platform['Indeed']} LinkedIn={by_platform['LinkedIn']}")
        print(f"  By category:")
        for cat, n in sorted(by_cat.items(), key=lambda x: cat_order.get(x[0], 9)):
            print(f"    {cat:28s}: {n}")
    if high:
        print(f"\n  * {len(high)} high-scoring jobs (>=8):")
        for r in high[:5]:
            flag = " → APPLY NOW" if r.get("Apply_Now") == "yes" else ""
            print(f"    [{r['_score']}/10] {r['Job Title']} @ {r['Company']}{flag}")
    print(f"\n  Tracker: {tracker_path}")
    print("=" * 62)


# ── Tailor one job ─────────────────────────────────────────────────────────────
def run_tailor(config: dict, jd_file: str) -> None:
    from src.agents.tailoring_agent import tailor_job, save_tailoring_output
    from src.tracker import excel
    from pathlib import Path

    output_dir = _BASE / config.get("output_dir", "output/")
    output_dir.mkdir(exist_ok=True)
    tracker_path = Path(config.get("tracker_path", "../job_tracker_ghazal.xlsx"))
    if not tracker_path.is_absolute():
        tracker_path = (_BASE / tracker_path).resolve()

    jd_path = Path(jd_file)
    if not jd_path.exists():
        print(f"ERROR: JD file not found: {jd_path}")
        sys.exit(1)
    jd_text = jd_path.read_text(encoding="utf-8")

    job_url = input("Enter job URL to look up in tracker (or press Enter to skip): ").strip()
    existing = excel.read_existing(tracker_path)

    row_data: dict = {}
    if job_url and job_url in existing:
        row_data = existing[job_url]
        print(f"  Found: {row_data.get('Job Title')} @ {row_data.get('Company')}")
    else:
        if job_url:
            print("  URL not found in tracker.")
        company_name = input("Company name: ").strip()
        role_title   = input("Role title: ").strip()
        row_data = {"Company": company_name, "Job Title": role_title,
                    "Search Category": "Analytics Engineer"}

    category  = row_data.get("Search Category", "Analytics Engineer")
    safe_role = category.replace(" ", "_")
    variant_file = output_dir / f"resume_{safe_role}.txt"
    if variant_file.exists():
        resume_text = variant_file.read_text(encoding="utf-8")
    else:
        cache_file = output_dir / "resume_parsed.json"
        import json
        resume_text = (json.loads(cache_file.read_text()).get("extracted_text", "")
                       if cache_file.exists() else "")

    result = tailor_job(
        jd_text, resume_text,
        row_data.get("Job Title", ""),
        row_data.get("Company", ""),
        config,
    )
    if result is None:
        print("ERROR: Tailoring failed. Check ANTHROPIC_API_KEY.")
        sys.exit(1)

    folder = save_tailoring_output(result, row_data.get("Company", "company"), output_dir)
    print(f"\n  Ready → {folder}/")
    print(f"  cover_letter.txt + resume_highlights.txt")

    # Update tracker status
    if job_url and job_url in existing:
        try:
            from openpyxl import load_workbook
            wb = load_workbook(tracker_path)
            ws = wb.active
            url_col = None
            status_col = None
            for ci in range(1, ws.max_column + 1):
                h = ws.cell(1, ci).value
                if h == "Apply Link":
                    url_col = ci
                if h == "Application Status":
                    status_col = ci
            if url_col and status_col:
                for ri in range(2, ws.max_row + 1):
                    cell = ws.cell(ri, url_col)
                    if (cell.hyperlink and cell.hyperlink.target == job_url):
                        ws.cell(ri, status_col).value = "Tailored"
                        break
            wb.save(tracker_path)
            print("  Tracker updated → Tailored")
        except PermissionError:
            print(f"  Warning: Close {tracker_path.name} to update status.")


# ── Entry ──────────────────────────────────────────────────────────────────────
def main() -> None:
    _check_deps()
    parser = argparse.ArgumentParser(description="Job Hunt Automation")
    parser.add_argument("--tailor", action="store_true",
                        help="Tailor one job from a JD file")
    parser.add_argument("--jd", type=str, default="",
                        help="Path to job description .txt file (required with --tailor)")
    args = parser.parse_args()

    config = _load_config()

    if args.tailor:
        if not args.jd:
            print("ERROR: --jd <file.txt> is required with --tailor")
            sys.exit(1)
        run_tailor(config, args.jd)
    else:
        run_pipeline(config)


if __name__ == "__main__":
    main()
