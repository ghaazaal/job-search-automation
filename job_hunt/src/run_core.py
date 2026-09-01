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
    ("LinkedIn",      "linkedin_actor",      "valig~linkedin-jobs-scraper"),
    ("Remote boards", "remote_boards_actor",
     "flash_scraper~remote-job-aggregator"),
)

# search.sources (config.yaml) switches a source on/off by a snake_case
# key: the source's own config-key stem, e.g. "remote_boards_actor" ->
# "remote_boards" — the shape a user editing that same file will guess,
# and the only spelling that works for a multi-word source. The legacy
# single-word spelling (the display name lowercased, e.g. "indeed") is
# also accepted so a config written before this stem existed keeps
# working. A key absent from search.sources defaults to enabled — see
# `_gate_key` and its use in `execute`.
def _gate_key(config_key: str) -> str:
    suffix = "_actor"
    return config_key[:-len(suffix)] if config_key.endswith(suffix) else config_key


# Sources with no meaningful local lane. A borderless board has no
# "near Yerevan" to search: `remote_boards.scrape` ignores location,
# country and work_modes entirely, so a local lane would send the
# identical payload and get back the same rows again — a second billed
# run for no new data, not merely noise.
_WORLDWIDE_ONLY = ("Remote boards",)

# Sources with no plain worldwide lane.
#
# This was Indeed, which is gone. It is now LinkedIn, for a different
# reason: its plain worldwide lane asks the same question the mode lanes
# ask, and asks it worse. Measured lane precision was remote 5/5 and
# hybrid 3/4 against an unfiltered lane that returns whatever LinkedIn's
# relevance matcher likes; run 6 spent 4 of 24 steps on it and the roles
# it added were indistinguishable from the mode lanes' own.
#
# The LOCAL lane stays, and is not affected by this constant. It found 63
# roles in the user's own country in run 6, and for a user in a small
# country a hybrid role in their own city is a role they can actually
# work — which is the whole question this product asks.
_LOCAL_ONLY = ("LinkedIn",)

# Modes that require the person to be physically there. A hybrid or
# on-site role is workable only where its office is, which is why
# `local_ok` and not the user's mode selection decides whether it can be
# taken. Remote is absent on purpose: being elsewhere is the point.
_PRESENCE_MODES = ("hybrid", "onsite")

# The only modes a keyword lane can express. On-site has no lane:
# measured 1/3 precision, because postings advertise "remote" and
# "hybrid" as selling points but rarely state on-site at all. It is
# inferred by elimination and served by the local lane.
LANE_MODES = ("remote", "hybrid")

# A mode lane asks a worldwide question - "remote data analyst", not
# "remote data analyst in Yerevan".
_LANE_WORLDWIDE = "Worldwide"


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


def plan_steps(titles: list[str], sources=SOURCES, local: bool = False,
               mode_lanes: tuple = (), wants_remote: bool = True) -> list[dict]:
    """The whole scrape, listed before any of it runs.

    Grouped by role, worldwide lane before local, which is the order they
    actually run in. The local lane searches the profile's actual place
    with every work mode — it exists so target-country on-site/hybrid
    jobs arrive at all instead of by accident.

    Mode lanes are the LinkedIn-only mechanism for recovering workplace
    type, which LinkedIn hides from logged-out clients and whose actor
    ignores every filter parameter we tried, and the two broken
    mechanisms failed differently. The `remote` argument left 9 of 23
    job IDs in BOTH the hybrid-filtered and onsite-filtered result sets,
    where a working filter yields zero overlap — a job has exactly one
    workplace type. The `f_WT` URL parameter was worse: four different
    values collapsed to two identical result lists, item for item
    (`f_WT=3` ≡ `f_WT=2`, `f_WT=1` ≡ `f_WT=1,3`). Only the search
    *words* reach LinkedIn's relevance matcher — searching "remote
    <title>" versus "hybrid <title>" shared 0 of 23 job IDs. So a mode
    lane is an extra LinkedIn search per (title, mode) with the mode
    word prefixed onto the query — one step per title for each mode in
    `mode_lanes` that is also in `LANE_MODES`. There is no on-site lane:
    measured 1/3 precision, because postings advertise "remote" and
    "hybrid" as selling points but rarely state on-site at all, so
    on-site is inferred by elimination and served by the local lane
    instead. A lane is relevance, not a filter — a posting that merely
    mentions the word can land in the lane — so lane membership only
    ever fills silence in `_apply_gates`, never overrides a mode stated
    in the posting's own text.
    """
    # The remote boards carry nothing but remote work — `remote_boards.
    # scrape` stamps every row "remote" because that is what those boards
    # are. A user who did not tick remote would have every row dropped or
    # flagged by the work-mode policy, after paying for the slowest source
    # in the run (a 420-second floor against LinkedIn's 20 seconds).
    if not wants_remote:
        sources = tuple(s for s in sources if s[0] not in _WORLDWIDE_ONLY)

    lanes = ("worldwide",) + (("local",) if local else ())
    steps = [{"source": name, "role": title, "lane": lane,
             "state": "pending", "found": 0}
            for title in titles
            for lane in lanes
            for name, _, _ in sources
            if not (lane == "local" and name in _WORLDWIDE_ONLY)
            and not (lane == "worldwide" and name in _LOCAL_ONLY)]
    if any(name == "LinkedIn" for name, _, _ in sources):
        steps += [{"source": "LinkedIn", "role": title,
                   "lane": f"mode {mode}", "state": "pending", "found": 0}
                  for title in titles
                  for mode in mode_lanes
                  if mode in LANE_MODES]
    return steps


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


def _default_watched_fetch(conn, user_id, lane, config, profile=None):
    from .scrapers.watched import fetch
    return fetch(conn, user_id, lane, config, profile=profile)


def _default_scrapers() -> dict:
    from .scrapers import linkedin, remote_boards
    return {"LinkedIn": linkedin.scrape,
            "Remote boards": remote_boards.scrape}


def _apply_gates(new_jobs: list[dict], vocab: dict, profile: dict,
                 work_modes) -> tuple[list[dict], int, int]:
    """Everything that decides whether a scraped job is worth scoring.

    Two independent gates, in order of cheapness. The relevance gate
    asks whether this is the job at all, and rejects ~41% of what the
    actors return. The work-mode/geo policy then asks whether this user
    could take it, which needs the vocabulary and the profile country.

    Returns (kept, offtopic_count, dropped_count). Both counts are
    reported and persisted — nothing here disappears silently.
    """
    from .scoring.geo import location_relation
    from .scoring.matching import has_term, work_mode
    from .scoring.relevance import is_target_role

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

    dropped_total = 0
    kept_jobs = []
    for job in new_jobs:
        # A publisher-stated field outranks everything and overrides
        # outright. Below that there is no second-strongest: text and
        # lane corroborate each other when they agree, nullify each
        # other when they conflict (see the branch below), and either
        # one alone fills the other's silence. Popping `_lane_mode`
        # happens unconditionally either way - it is transient
        # regardless of whether it ends up used.
        stated_mode = job.get("work_mode")
        lane_mode = job.pop("_lane_mode", None)
        if stated_mode:
            # The employer said so, in a structured field, on the job
            # board itself (kaix's workArrangement.locationType). That
            # beats both a phrase the scorer inferred from prose and a
            # LinkedIn lane, which is relevance rather than a filter -
            # neither gets a vote once the posting has already answered.
            mode = stated_mode
        else:
            text_mode = work_mode(f"{job.get('title') or ''}\n"
                                  f"{job.get('description') or ''}", mode_cfg)
            if text_mode and lane_mode and text_mode != lane_mode:
                # A lane is LinkedIn matching words, not a filter - a
                # posting that merely mentions "remote" lands in the
                # remote lane. Disagreement claims nothing, as every
                # other conflict does.
                mode = None
            elif lane_mode and not text_mode:
                mode = lane_mode
            else:
                mode = text_mode
        if mode:
            job["work_mode"] = mode

        raw_location = (job.get("location") or "").strip().lower()
        # Membership, not resolution: "is this place the user's?" The
        # dataset behind it never has to decide WHICH Dublin a posting
        # means, because every Dublin is equally not-Armenia.
        relation = location_relation(job.get("location"), user_country,
                                     loc_cfg)
        local_ok = bool(
            (profile_city and has_term(profile_city, raw_location))
            or relation == "local")
        if local_ok:
            # Positive evidence the job is in the user's own place —
            # popped before scoring, handed to the scorer explicitly.
            job["_local_ok"] = True

        # A mode the user did not ask for, OR a mode that requires being
        # somewhere they are not.
        #
        # Ticking "hybrid" means hybrid NEAR ME. It never meant hybrid
        # anywhere, and reading it that way put 211 of 594 listed roles on
        # the live map that the user cannot physically attend — hybrid and
        # on-site posts in London, Bengaluru, Sydney. The old test asked
        # only whether the mode was one the user ticked, so a hybrid role
        # abroad sailed through for a user who had ticked hybrid.
        #
        # Remote is deliberately not in this set: being elsewhere is the
        # entire point of it, and its eligibility is decided by reach
        # evidence rather than by geography.
        unwanted = bool(mode and user_modes and mode not in user_modes)
        cannot_attend = mode in _PRESENCE_MODES and not local_ok
        if unwanted or cannot_attend:
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
            if relation == "foreign":
                dropped_total += 1
                continue
            if relation is None:
                job["_mode_mismatch"] = mode
        kept_jobs.append(job)
    new_jobs = kept_jobs

    return new_jobs, offtopic_total, dropped_total


def _apply_scope(jobs: list[dict], vocab: dict, profile: dict) -> None:
    """Judge each remote-board row's published reach, in place.

    Remote boards state who they will hire as a FIELD, because being
    borderless is their product. Run 6 measured what that is worth: across
    384 roles, mining prose for eligibility found nothing and manufactured
    three claims, while reading this field found two and manufactured
    none. It is the only mechanism in this product that has ever proved a
    role open to a user outside the big markets.

    Board rows only. A LinkedIn `location` is a place, not a reach
    statement — feeding it to a reach parser would manufacture exactly the
    fake evidence rule 6a exists to stop. Rows without a `source_board`
    are left untouched, and an untouched row stores NULL, which the map
    reads as unverified rather than as closed.

    Lives here rather than in `store/ingest.py`, which the spec suggested:
    ingest is a pure writer with neither the vocabulary nor the user's
    profile, and giving it both so it can fill one column would be a worse
    trade than this. `run_core` holds both already and annotates jobs in
    exactly this way (`_local_ok`, `_mode_mismatch`).
    """
    from .scoring.geo import location_relation
    from .scoring.location_scope import scope_verdict
    from .scoring.matching import geo_verdict

    country = (profile.get("country") or "").strip().lower()
    scope_cfg = vocab.get("location_scope") or {}
    geo_cfg = vocab.get("eligibility") or {}
    for job in jobs:
        # The reach FIELD is board-specific — only a remote board publishes
        # one. The employer's own words are not: every source carries a
        # description, and a posting that says where it hires says it
        # whoever we read it from.
        scope = None
        if job.get("source_board"):
            scope = scope_verdict(
                job.get("location") or "", country, scope_cfg, geo_cfg)

        # The employer's own words outrank the board's tag.
        #
        # These are not two opinions of equal standing, so this is not the
        # usual conflict-claims-nothing rule. The reach field is the
        # BOARD's categorisation of a posting; the description is what the
        # employer wrote. We Work Remotely tagged a Doximity role
        # "Anywhere in the World" whose own text read "headquarters: san
        # francisco, ca or remote (u.s.)", and a Faire role the same way
        # while it enumerated the eleven US states it would hire in. Both
        # reached the map claiming to be open to an Armenian user.
        #
        # Only a restriction overrides. A body that says nothing leaves
        # the field standing, because most postings say nothing and the
        # field is then the only evidence there is.
        # Prose may CLOSE a row from any source. "Remote in the
        # Philippines" is remote WITHIN a country, not remote to anywhere,
        # and 34 of 383 listed roles said something of that shape while
        # nothing read them — this check used to run on board rows only.
        #
        # Prose may NOT open a row that has no reach field. Measured over
        # 384 live roles, mining prose for positive eligibility found 0
        # real matches and manufactured 3; it is trustworthy for
        # restrictions, which are stated deliberately, and not for
        # permissions, which are inferred from absence. So promotion stays
        # where a board field already made a claim to corroborate.
        verdict, _ = geo_verdict((job.get("description") or "").lower(),
                                 country, geo_cfg)
        if verdict in ("restricted", "excluded"):
            scope = "closed"
        elif verdict == "eligible" and scope == "unknown":
            scope = "open"

        # A posting anchored to a foreign country is not this user's,
        # whatever mode it claims.
        #
        # "Remote" on a posting whose location says Canada means remote
        # FROM Canada — the Celestir row read "location: canada / remote"
        # in its own description. 246 of 349 listed roles were anchored
        # to a country that was not the user's and shown anyway, because
        # nothing but a stated restriction could close a row.
        #
        # This is the weakest kind of evidence in the ladder, so it only
        # applies where nothing stronger spoke: a reach field or a
        # description saying the employer hires beyond its own address
        # still wins. And an unreadable location claims nothing at all,
        # which is why `location_country` refuses to guess.
        if scope != "open" and country:
            if location_relation(job.get("location"), country,
                                 geo_cfg) == "foreign":
                scope = "closed"

        if scope is not None:
            job["location_scope"] = scope


def execute(conn, user_id: int, run_id: int, config: dict,
            resumes: list[dict], profile: dict,
            on_progress=None, scrapers=None, enrich=None,
            watched_fetch=None) -> RunResult:
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

    # A source can be switched off in config.yaml (search.sources), keyed
    # by _gate_key's snake_case stem (or the legacy single-word spelling).
    # Missing key means enabled, so existing configs keep working.
    gates = (config.get("search", {}) or {}).get("sources") or {}
    sources = tuple(
        entry for entry in SOURCES
        if gates.get(_gate_key(entry[1]), gates.get(entry[0].lower(), True)))

    mode_lanes = tuple(m for m in
                       (str(x).strip().lower() for x in work_modes)
                       if m in LANE_MODES)
    steps = plan_steps(titles, sources=sources,
                      local=bool((profile.get("location") or "").strip()),
                      mode_lanes=mode_lanes,
                      wants_remote="remote" in {str(m).strip().lower()
                                                for m in work_modes})
    # Loaded before the scrape rather than after it: the relevance gate's
    # exclusion list is now also sent to LinkedIn as titleExclude, so it
    # has to exist before the first call rather than after the last.
    with open(VOCABULARY_PATH, encoding="utf-8") as handle:
        vocab = yaml.safe_load(handle)
    role_excludes = ((vocab.get("roles") or {}).get("exclude") or [])

    # Watched companies: two extra steps, planned only when the user
    # watches anything. Resolution runs lazily inside the ats step (never
    # in a Flask request), then one batched call per rung. Rows join the
    # stream BEFORE dedupe and pass every gate unchanged: watching a
    # company changes where we search, not what qualifies as a job for
    # the user.
    from .store.watchlist import list_watched
    _watch_rows = list_watched(conn, user_id)
    if _watch_rows:
        _watch_lanes = ["ats", "linkedin"]
        # The custom rung's step exists only when a company resolved to
        # it - a permanent zero-row step would read as noise.
        if any(r["resolution"] == "custom" for r in _watch_rows):
            _watch_lanes.append("custom")
        steps += [{"source": "Watched companies", "role": "watchlist",
                   "lane": lane, "state": "pending", "found": 0}
                  for lane in _watch_lanes]

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
        if name == "Watched companies":
            try:
                if step["lane"] == "ats":
                    # Lazy resolution: one attempt per unresolved row,
                    # before the first fetch of the run.
                    from .scrapers.watched import resolve_pending
                    resolve_pending(conn, user_id, config)
                fetch = watched_fetch or _default_watched_fetch
                jobs = fetch(conn, user_id, step["lane"], config,
                             profile=profile)
            except Exception as exc:
                # One rung failing must not throw away the other's rows,
                # or any other source's.
                logger.warning("Watched/%s failed: %s", step["lane"], exc)
                step["state"] = "failed"
                step["found"] = 0
            else:
                step["state"] = "done"
                step["found"] = len(jobs)
                all_scraped.extend(jobs)
                scraped_total += len(jobs)
            report("scraping")
            continue

        actor_key, actor_default = next(
            (key, default) for source, key, default in sources
            if source == name)

        lane_title = step["role"]
        if step["lane"].startswith("mode "):
            lane_mode = step["lane"].split(" ", 1)[1]
            lane_title = f"{lane_mode} {step['role']}"
            lane_location = _LANE_WORLDWIDE
            lane_modes = (lane_mode,)
            lane_kwargs = {"allow_fallback": False}
        elif step["lane"] == "local":
            lane_location = (profile.get("location") or "").strip()
            lane_modes = ("remote", "hybrid", "onsite")
            # allow_fallback=False: a Yerevan search that comes back empty
            # must not silently fall back to Worldwide/remote-us — that
            # re-fetches the worldwide lane's own results under the local
            # lane, double-counting `scraped` and defeating the point of
            # having a local lane at all.
            lane_kwargs = {"allow_fallback": False}
        else:
            # Worldwide means worldwide. Passing the profile's location
            # here made this lane's payload identical to the local lane's
            # — LinkedIn stopped reading work_modes when `_filters_for`
            # went, so the two differed in nothing at all.
            lane_location = _LANE_WORLDWIDE
            lane_modes = work_modes
            lane_kwargs = {}
        if name == "LinkedIn":
            # LinkedIn answers a free-text title however its relevance
            # matcher likes, so the same filter the gate applies after
            # billing is applied at the source instead. The include list
            # is the USER's roles, from their resumes: vocabulary.yaml
            # names the market's data titles, which is a different and
            # deliberately impersonal thing. The exclude list is the
            # gate's own measured traps, which are market facts.
            lane_kwargs = {**lane_kwargs,
                           "title_include": tuple(titles),
                           "title_exclude": tuple(role_excludes)}
        try:
            jobs = scrapers[name](
                step["role"], lane_title,
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
            if step["lane"].startswith("mode "):
                for job in jobs:
                    # Transient. Popped in _apply_gates, never stored.
                    job["_lane_mode"] = step["lane"].split(" ", 1)[1]
            all_scraped.extend(jobs)
            scraped_total += len(jobs)
        report("scraping")

    # The aggregator advertises ten boards and returned four in run 6.
    # Recorded per run so a board going quiet is visible; the row count is
    # not the signal, because 133 rows arrived from those four.
    boards_seen = sorted({str(job["source_board"]) for job in all_scraped
                          if job.get("source_board")})

    known_urls, known_rows = known_listings(conn, user_id)
    new_jobs = dedupe(all_scraped,
                      existing_urls=known_urls, existing_rows=known_rows)

    new_jobs, offtopic_total, dropped_total = _apply_gates(
        new_jobs, vocab, profile, work_modes)
    _apply_scope(new_jobs, vocab, profile)

    # `user_modes` is also needed below, for the Scorer.
    user_modes = tuple(str(m).strip().lower()
                       for m in work_modes if str(m).strip())

    if enrich is not None:
        new_jobs = enrich(new_jobs)

    report("scoring")
    scorer = Scorer(config, VOCABULARY_PATH,
                    user_country=profile.get("country") or "",
                    user_modes=user_modes)
    scored_jobs = []
    for job in new_jobs:
        mode_mismatch = job.pop("_mode_mismatch", None)
        local_ok = job.pop("_local_ok", False)
        scored_jobs.append(
            {**job, **scorer.best_match(job["title"],
                                        job.get("description", ""),
                                        resumes,
                                        mode_mismatch=mode_mismatch,
                                        local_evidence=local_ok)})

    report("storing")
    persist_run(conn, user_id, run_id, scored_jobs, scraped_total,
               dropped=dropped_total, offtopic=offtopic_total,
               boards=boards_seen)

    return RunResult(scraped=scraped_total, kept=len(scored_jobs),
                     dropped=dropped_total, offtopic=offtopic_total,
                     scored_jobs=scored_jobs, steps=steps, titles=titles)
