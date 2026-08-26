"""Scrape, dedupe, score, store — the part of a run the map depends on.

Callers differ in how they report progress and in what they do afterwards, so
this module does neither. It emits events through `on_progress` and returns
what it produced. Printing, writing progress into the run row, and the LLM and
Excel steps all belong to the caller.

Nothing here imports Flask or threading.
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# (display name, config key for the actor id, default actor id)
SOURCES = (
    ("Indeed",   "indeed_actor",   "valig~indeed-jobs-scraper"),
    ("LinkedIn", "linkedin_actor", "valig~linkedin-jobs-scraper"),
)


def search_titles(resumes: list[dict]) -> list[str]:
    """Every distinct target role across the active resumes, in order.

    Case-insensitive on the key so 'BI Developer' and 'bi developer' are one
    search, but the first spelling seen is the one that gets searched.
    """
    titles: list[str] = []
    seen: set[str] = set()
    for resume in resumes:
        for role in resume.get("target_roles") or []:
            title = (role.get("title") or "").strip()
            key = title.lower()
            if title and key not in seen:
                seen.add(key)
                titles.append(title)
    return titles


def plan_steps(titles: list[str]) -> list[dict]:
    """The whole scrape, listed before any of it runs.

    Grouped by role rather than by source so the progress screen reads down
    one role at a time, which is the order they actually run in.
    """
    return [{"source": name, "role": title, "state": "pending", "found": 0}
            for title in titles
            for name, _, _ in SOURCES]


VOCABULARY_PATH = Path(__file__).resolve().parent.parent / "vocabulary.yaml"


@dataclass
class RunResult:
    """What a run produced, for whatever the caller does next."""
    scraped: int = 0
    kept: int = 0
    dropped: int = 0
    scored_jobs: list[dict] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)


def _default_scrapers() -> dict:
    from .scrapers import indeed, linkedin
    return {"Indeed": indeed.scrape, "LinkedIn": linkedin.scrape}


def execute(conn, user_id: int, run_id: int, config: dict,
            resumes: list[dict], profile: dict,
            on_progress=None, scrapers=None, enrich=None) -> RunResult:
    """Scrape, dedupe, score and store one run.

    Args:
        run_id:      an already-open RUNNING run. This never creates one.
        on_progress: called with the whole progress payload after each step.
        scrapers:    {source name: scrape callable}. Injected by tests.
        enrich:      optional hook handed the deduped jobs before scoring,
                     returning the jobs to score. The terminal path uses it
                     for company enrichment; the browser run passes nothing.

    Raises:
        ValueError: when there is no active resume, or none of them name a
            target role. There is nothing to search for, and failing here is
            clearer than a run that scrapes nothing and looks broken.
    """
    import yaml

    from .pipeline_store import persist_run
    from .scoring.matching import location_country, work_mode
    from .scoring.scorer import Scorer
    from .store.queries import known_listings
    from .tracker.dedup import dedupe

    if not resumes:
        raise ValueError("no active resume on file, so there is nothing to "
                         "search for")
    titles = search_titles(resumes)
    if not titles:
        raise ValueError("your resumes name no target roles between them")

    emit = on_progress or (lambda event: None)
    scrapers = scrapers or _default_scrapers()

    apify_cfg    = config.get("apify", {})
    search_cfg   = config.get("search", {})
    days_posted  = search_cfg.get("days_posted", 7)
    jobs_per_cat = search_cfg.get("jobs_per_category", 50)
    run_timeout  = search_cfg.get("run_timeout", 120)

    location   = profile.get("location") or ""
    country    = profile.get("country") or "us"
    work_modes = profile.get("work_modes") or ["remote"]

    steps = plan_steps(titles)
    scraped_total = 0
    dropped_total = 0

    def report(stage: str) -> None:
        emit({"stage": stage, "steps": [dict(s) for s in steps],
             "scraped": scraped_total, "dropped": dropped_total})

    # Announce the whole plan before doing any of it.
    report("scraping")

    all_scraped: list[dict] = []
    for step in steps:
        step["state"] = "running"
        report("scraping")

        name = step["source"]
        actor_key, actor_default = next(
            (key, default) for source, key, default in SOURCES
            if source == name)
        try:
            jobs = scrapers[name](
                step["role"], step["role"],
                apify_cfg.get(actor_key, actor_default),
                days_posted, jobs_per_cat, run_timeout,
                location=location, country=country, work_modes=work_modes)
        except Exception as exc:
            # One source failing must not throw away the other's results.
            logger.warning("%s/%s failed: %s", name, step["role"], exc)
            step["state"] = "failed"
            step["found"] = 0
        else:
            step["state"] = "done"
            step["found"] = len(jobs)
            all_scraped.extend(jobs)
            scraped_total += len(jobs)
        report("scraping")

    known_urls, known_rows = known_listings(conn, user_id)
    new_jobs = dedupe(all_scraped,
                      existing_urls=known_urls, existing_rows=known_rows)

    if enrich is not None:
        new_jobs = enrich(new_jobs)

    # Work-mode policy. The one user-approved exception to flag-never-
    # hide: a posting that states a mode the user did not search for,
    # located in a country that is not theirs, is dropped — bounded by
    # requiring BOTH the explicit phrase AND a confidently-parsed
    # country. Local ones are workable in person and kept clean;
    # unplaceable ones are flagged, because a silent drop cannot be
    # justified without knowing where the job is.
    with open(VOCABULARY_PATH, encoding="utf-8") as handle:
        vocab = yaml.safe_load(handle)
    mode_cfg = vocab.get("work_mode") or {}
    loc_cfg = vocab.get("eligibility") or {}
    user_modes = tuple(str(m).strip().lower()
                       for m in (profile.get("work_modes") or [])
                       if str(m).strip())
    user_country = (profile.get("country") or "").strip().lower()

    kept_jobs = []
    for job in new_jobs:
        mode = work_mode(f"{job.get('title') or ''}\n"
                         f"{job.get('description') or ''}", mode_cfg)
        if mode:
            job["work_mode"] = mode
        if mode and user_modes and mode not in user_modes:
            raw_location = (job.get("location") or "").strip().lower()
            if raw_location == "remote":
                # The location field says remote (actor-tagged) while the
                # prose says otherwise — conflicting evidence, so claim
                # nothing: no drop, no flag, no stored mode.
                job.pop("work_mode", None)
                kept_jobs.append(job)
                continue
            place = location_country(job.get("location") or "", loc_cfg)
            if place and user_country and place != user_country:
                dropped_total += 1
                continue
            if not (place and user_country):
                job["_mode_mismatch"] = mode
        kept_jobs.append(job)
    new_jobs = kept_jobs

    report("scoring")
    scorer = Scorer(config, VOCABULARY_PATH,
                    user_country=profile.get("country") or "",
                    user_modes=user_modes)
    scored_jobs = []
    for job in new_jobs:
        # Set by the Indeed scraper when its us-board fallback fired.
        # Popped — not read — so the transient key can never reach
        # persist_run, the store, or the terminal path's later steps.
        scraped_under = job.pop("_scraped_under", None)
        mode_mismatch = job.pop("_mode_mismatch", None)
        scored_jobs.append(
            {**job, **scorer.best_match(job["title"],
                                        job.get("description", ""),
                                        resumes,
                                        scraped_under=scraped_under,
                                        mode_mismatch=mode_mismatch)})

    report("storing")
    persist_run(conn, user_id, run_id, scored_jobs, scraped_total)

    return RunResult(scraped=scraped_total, kept=len(scored_jobs),
                     dropped=dropped_total,
                     scored_jobs=scored_jobs, steps=steps, titles=titles)
