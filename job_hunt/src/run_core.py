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


def plan_steps(titles: list[str], sources=SOURCES,
               local: bool = False) -> list[dict]:
    """The whole scrape, listed before any of it runs.

    Grouped by role, worldwide lane before local, which is the order they
    actually run in. The local lane searches the profile's actual place
    with every work mode — it exists so target-country on-site/hybrid
    jobs arrive at all instead of by accident.
    """
    lanes = ("worldwide",) + (("local",) if local else ())
    return [{"source": name, "role": title, "lane": lane,
             "state": "pending", "found": 0}
            for title in titles
            for lane in lanes
            for name, _, _ in sources]


VOCABULARY_PATH = Path(__file__).resolve().parent.parent / "vocabulary.yaml"


@dataclass
class RunResult:
    """What a run produced, for whatever the caller does next."""
    scraped: int = 0
    kept: int = 0
    dropped: int = 0
    offtopic: int = 0
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
        enrich:      optional hook handed the jobs that survived the
                     work-mode/geo policy ladder, before scoring, returning
                     the jobs to score. The terminal path uses it for
                     company enrichment; the browser run passes nothing.

    Raises:
        ValueError: when there is no active resume, or none of them name a
            target role. There is nothing to search for, and failing here is
            clearer than a run that scrapes nothing and looks broken.
    """
    import yaml

    from .pipeline_store import persist_run
    from .scoring.matching import has_term, location_country, work_mode
    from .scoring.relevance import is_target_role
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

    # A source can be switched off in config.yaml (search.sources).
    # Missing key means enabled, so existing configs keep working.
    gates = (config.get("search", {}) or {}).get("sources") or {}
    sources = tuple(entry for entry in SOURCES
                    if gates.get(entry[0].lower(), True))

    steps = plan_steps(titles, sources=sources,
                      local=bool((profile.get("location") or "").strip()))
    scraped_total = 0
    dropped_total = 0
    offtopic_total = 0

    def report(stage: str) -> None:
        emit({"stage": stage, "steps": [dict(s) for s in steps],
             "scraped": scraped_total, "dropped": dropped_total,
             "offtopic": offtopic_total})

    # Announce the whole plan before doing any of it.
    report("scraping")

    all_scraped: list[dict] = []
    for step in steps:
        step["state"] = "running"
        report("scraping")

        name = step["source"]
        actor_key, actor_default = next(
            (key, default) for source, key, default in sources
            if source == name)

        if step["lane"] == "local":
            lane_location = (profile.get("location") or "").strip()
            lane_modes = ("remote", "hybrid", "onsite")
            # allow_fallback=False: a Yerevan search that comes back empty
            # must not silently fall back to Worldwide/remote-us — that
            # re-fetches the worldwide lane's own results under the local
            # lane, double-counting `scraped` and defeating the point of
            # having a local lane at all.
            lane_kwargs = {"allow_fallback": False}
        else:
            lane_location = location
            lane_modes = work_modes
            lane_kwargs = {}
        try:
            jobs = scrapers[name](
                step["role"], step["role"],
                apify_cfg.get(actor_key, actor_default),
                days_posted, jobs_per_cat, run_timeout,
                location=lane_location, country=country,
                work_modes=lane_modes, **lane_kwargs)
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

    with open(VOCABULARY_PATH, encoding="utf-8") as handle:
        vocab = yaml.safe_load(handle)

    # Relevance gate. 41% of what these actors return is not a data role
    # at all — Nurse Practitioner, Travel Advisor, Fleet Parking
    # Specialist. The scorer rates them 1-4 and they were stored anyway.
    # Rejecting here means an off-target role costs no enrichment lookup
    # and no scoring pass. Counted, never silent.
    role_cfg = vocab.get("roles") or {}
    on_topic = [job for job in new_jobs
               if is_target_role(job.get("title"), role_cfg)]
    offtopic_total = len(new_jobs) - len(on_topic)
    new_jobs = on_topic

    # Work-mode policy. The one user-approved exception to flag-never-
    # hide: a posting that states a mode the user did not search for,
    # located in a country that is not theirs, is dropped — bounded by
    # requiring BOTH the explicit phrase AND a confidently-parsed
    # country. Local ones are workable in person and kept clean;
    # unplaceable ones are flagged, because a silent drop cannot be
    # justified without knowing where the job is. Runs before `enrich`
    # so a dropped job never costs a company-enrichment lookup.
    mode_cfg = vocab.get("work_mode") or {}
    loc_cfg = vocab.get("eligibility") or {}
    # Same fallback the scrape itself uses (see `work_modes` above) — an
    # empty profile silently disabling the policy would also leave the
    # scorer's own "remote" fallback dead code.
    user_modes = tuple(str(m).strip().lower()
                       for m in work_modes if str(m).strip())
    user_country = (profile.get("country") or "").strip().lower()
    profile_city = (profile.get("location") or "").split(",")[0].strip().lower()

    kept_jobs = []
    for job in new_jobs:
        mode = work_mode(f"{job.get('title') or ''}\n"
                         f"{job.get('description') or ''}", mode_cfg)
        if mode:
            job["work_mode"] = mode

        raw_location = (job.get("location") or "").strip().lower()
        place = location_country(job.get("location") or "", loc_cfg)
        local_ok = bool(
            (profile_city and has_term(profile_city, raw_location))
            or (place and user_country and place == user_country))
        if local_ok:
            # Positive evidence the job is in the user's own place —
            # popped before scoring, handed to the scorer explicitly.
            job["_local_ok"] = True

        if mode and user_modes and mode not in user_modes:
            if has_term("remote", raw_location):
                # The location field carrying "remote" anywhere is the
                # actor's own tag on where the job is — it beats a stray
                # prose phrase, whatever the actor appended after it
                # ("Remote, US" is Indeed's own placeholder, "Remote -
                # Canada", "Toronto, ON (Remote)"). Conflicting evidence
                # claims nothing: no drop, no flag, no stored mode.
                job.pop("work_mode", None)
                kept_jobs.append(job)
                continue
            if local_ok:
                # The user's own city named in the job's location, or a
                # parsed country matching the user's, is local — workable
                # in person whatever the country parser thinks otherwise
                # ("Toronto, ON" has no country to parse, but it IS
                # Toronto).
                kept_jobs.append(job)
                continue
            if place and user_country and place != user_country:
                dropped_total += 1
                continue
            if not (place and user_country):
                job["_mode_mismatch"] = mode
        kept_jobs.append(job)
    new_jobs = kept_jobs

    if enrich is not None:
        new_jobs = enrich(new_jobs)

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
        local_ok = job.pop("_local_ok", False)
        scored_jobs.append(
            {**job, **scorer.best_match(job["title"],
                                        job.get("description", ""),
                                        resumes,
                                        scraped_under=scraped_under,
                                        mode_mismatch=mode_mismatch,
                                        local_evidence=local_ok)})

    report("storing")
    persist_run(conn, user_id, run_id, scored_jobs, scraped_total,
               dropped=dropped_total)

    return RunResult(scraped=scraped_total, kept=len(scored_jobs),
                     dropped=dropped_total, offtopic=offtopic_total,
                     scored_jobs=scored_jobs, steps=steps, titles=titles)
