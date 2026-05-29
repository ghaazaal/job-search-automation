"""Dashboard generator.

Injects real pipeline rows into the finalized.html template and writes
a self-contained HTML file the user can open in any browser.

Template location (from CLAUDE.md):
  ~/.gstack/projects/JobSearchautomation/designs/
      job-review-dashboard-20260528/finalized.html

Output: <project_root>/job-review-dashboard.html
"""
import json
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Keywords used to derive match chips from job titles
_MATCH_KWS   = ["dbt", "snowflake", "bigquery", "airflow", "python", "sql",
                 "power bi", "clickhouse", "spark", "kafka", "databricks",
                 "looker", "tableau", "streamlit", "plotly", "analytics engineer",
                 "data engineer", "analytics"]
_PARTIAL_KWS = ["bi", "etl", "elt", "pipeline", "warehouse", "cloud",
                 "aws", "gcp", "azure", "mlops", "llm", "ml engineer"]


def _safe_pct(val) -> int:
    """Parse a percentage value that may be an int, float, or string like '45%'."""
    try:
        return max(0, min(100, int(str(val).replace("%", "").strip())))
    except (ValueError, TypeError):
        return 5


def _days_ago(posting_date) -> int:
    try:
        if isinstance(posting_date, (date, datetime)):
            d = posting_date.date() if isinstance(posting_date, datetime) else posting_date
        else:
            d = datetime.strptime(str(posting_date)[:10], "%Y-%m-%d").date()
        return max(0, (date.today() - d).days)
    except (ValueError, TypeError):
        return 0


def _chips(title: str) -> list[dict]:
    t = title.lower()
    seen: set[str] = set()
    chips: list[dict] = []
    for kw in _MATCH_KWS:
        if kw in t and kw not in seen:
            chips.append({"label": kw, "type": "match"})
            seen.add(kw)
    for kw in _PARTIAL_KWS:
        if kw in t and kw not in seen:
            chips.append({"label": kw, "type": "partial"})
            seen.add(kw)
    return chips[:6]


def _rows_to_jobs(rows: list[dict]) -> list[dict]:
    """Convert pipeline row dicts to the JOBS array format the dashboard expects."""
    jobs: list[dict] = []
    for i, row in enumerate(rows, start=1):
        if row.get("Application Status") == "Filtered Out":
            continue
        raw_score   = row.get("Match Score") or row.get("_score") or 0
        # Guard: old rows may have a string like "45%" here due to schema migration
        try:
            score_1_10 = int(str(raw_score).replace("%", "").strip())
        except (ValueError, TypeError):
            score_1_10 = 0
        # Clamp: old "Interview Chance" values (e.g. 45) landed in Match Score
        # column due to schema shift — treat anything > 10 as a stale row.
        if score_1_10 > 10:
            score_1_10 = 0
        score_pct   = min(100, score_1_10 * 10)   # scale 1–10 → 10–100 for score bar %

        apply_now   = str(row.get("Apply_Now") or "").lower() == "yes"
        description = row.get("Apply Link") or ""
        if description:
            platform = row.get("Platform", "job board")
            description = f'View full description on {platform}: <a href="{description}" target="_blank" style="color:var(--cyan)">Open listing →</a>'

        jobs.append({
            "id":           i,
            "company":      row.get("Company") or "",
            "title":        row.get("Job Title") or "",
            "location":     row.get("Location") or "",
            "salary":       row.get("Salary") or "",
            "score":        score_pct,
            "scoreDirect":  score_1_10,   # raw 1–10 score for display
            "postedDaysAgo": _days_ago(row.get("Posting Date")),
            "status":       row.get("Application Status") or "New",
            "url":          row.get("Apply Link") or "",
            "platform":     row.get("Platform") or "",
            "applyNow":     apply_now,
            "llmReason":    row.get("LLM_Reason") or "",
            "riskFlags":    row.get("Risk_Flags") or "",
            "chips":        _chips(row.get("Job Title") or ""),
            "description":  description,
            "requirements": [],
            "breakdown": [
                {"label": "Keyword Match",  "pct": min(100, score_pct),        "delta": f"+{score_1_10}", "neg": False},
                {"label": "Interview Est.", "pct": _safe_pct(row.get("Interview Chance")),
                 "delta": str(row.get("Interview Chance") or ""), "neg": False},
            ],
        })
    return jobs


def generate(rows: list[dict], template_path: Path, output_path: Path,
             run_ts: str = "") -> Path:
    """Inject real job data into the HTML template and write to output_path.

    Args:
        rows:          Pipeline row dicts (from main.py).
        template_path: Path to finalized.html (the design template).
        output_path:   Where to write the live dashboard HTML.
        run_ts:        Pipeline run timestamp string for the nav badge.

    Returns:
        output_path (for chaining / logging).
    """
    if not template_path.exists():
        raise FileNotFoundError(
            f"Dashboard template not found: {template_path}\n"
            "Expected at: ~/.gstack/projects/JobSearchautomation/designs/"
            "job-review-dashboard-20260528/finalized.html"
        )

    template = template_path.read_text(encoding="utf-8")

    # Sort by score descending, take top 200 for dashboard
    def _score_key(r) -> int:
        val = r.get("Match Score") or r.get("_score") or 0
        try:
            n = int(str(val).replace("%", "").strip())
            return n if 1 <= n <= 10 else 0   # discard stale/misaligned values
        except (ValueError, TypeError):
            return 0

    sorted_rows = sorted(
        (r for r in rows
         if r.get("Application Status") != "Filtered Out"
         and _score_key(r) > 0),           # skip rows with no valid score
        key=_score_key,
        reverse=True,
    )[:200]

    jobs = _rows_to_jobs(sorted_rows)
    total     = len(jobs)
    high_count = sum(1 for j in jobs if j["scoreDirect"] >= 7)
    badge_text = f"{total} today" if not run_ts else f"{total} · {run_ts}"

    jobs_json = json.dumps(jobs, ensure_ascii=False, indent=2)

    # Inject JOBS array
    updated = re.sub(
        r'const JOBS\s*=\s*\[.*?\];',
        f'const JOBS = {jobs_json};',
        template,
        flags=re.DOTALL,
    )

    # Update the "N today" badge in the nav
    updated = re.sub(
        r'(<span[^>]+id=["\']todayBadge["\'][^>]*>)[^<]*(</span>)',
        rf'\g<1>{badge_text}\g<2>',
        updated,
    )

    # Update total count in the nav (Reviewed: 0/N)
    updated = re.sub(
        r'(<span[^>]+id=["\']totalCount["\'][^>]*>)\d+(</span>)',
        rf'\g<1>{total}\g<2>',
        updated,
    )
    updated = re.sub(
        r'(<span[^>]+id=["\']remainingCount["\'][^>]*>)\d+(</span>)',
        rf'\g<1>{total}\g<2>',
        updated,
    )

    output_path.write_text(updated, encoding="utf-8")
    logger.info("Dashboard written: %s (%d jobs, %d high-scoring)",
                output_path, total, high_count)
    return output_path


def open_browser(path: Path) -> None:
    """Open the dashboard in the system's default browser."""
    try:
        os.startfile(str(path))          # Windows
    except AttributeError:
        import subprocess
        subprocess.Popen(["open", str(path)])   # macOS fallback
    except Exception as e:
        logger.warning("Could not open browser automatically: %s", e)
        print(f"  Open manually: {path}")
