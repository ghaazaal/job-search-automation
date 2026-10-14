"""One analysis, start to finish: read postings, count, compare, rank, plan.

Writes one `learning_path` row. Every step reports progress so the page can
say what is happening; any exception fails the row with its message.
"""
import logging
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import yaml

from ..store import learning as store
from ..store.db import connect
from ..store.profile import list_resumes
from . import compare, extract, market, path, rank

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent

ALL = "all"
# A kind of role needs this many postings in the window to get its own
# path; below it, it still counts toward "All roles".
MIN_FAMILY_POSTINGS = 10
# Skills the resume comparison asks Claude about, across every view.
COMPARE_LIMIT = 60


def load_settings() -> tuple[dict, dict]:
    """(learning_path config, vocabulary)."""
    with open(_ROOT / "config.yaml", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    with open(_ROOT / "vocabulary.yaml", encoding="utf-8") as handle:
        vocabulary = yaml.safe_load(handle) or {}
    return config.get("learning_path") or {}, vocabulary


def merged_resume(resumes: list[dict]) -> dict:
    """Every active resume read as one person: their skills are the union.

    The ask is one path for the user, not one per resume, and a skill on
    any of their resumes is a skill they have.
    """
    skills, seen = [], set()
    for resume in resumes:
        for skill in resume.get("skills") or []:
            key = str(skill.get("name", "")).lower()
            if key and key not in seen:
                seen.add(key)
                skills.append(skill)
    roles, seen_roles = [], set()
    for resume in resumes:
        for role in resume.get("target_roles") or []:
            key = str(role.get("title", "")).lower()
            if key and key not in seen_roles:
                seen_roles.add(key)
                roles.append(role)
    bands = ["junior", "mid", "senior", "exec"]
    seniority = max((r.get("seniority") for r in resumes
                     if r.get("seniority") in bands),
                    key=bands.index, default=None)
    return {
        "labels": [r.get("label", "") for r in resumes],
        "skills": skills,
        "target_roles": roles,
        "seniority": seniority,
        "extracted_text": "\n\n".join(r.get("extracted_text") or ""
                                      for r in resumes),
    }


def analyse(conn, user_id: int, model, settings: dict, vocabulary: dict,
            on_progress=None, limit: int | None = None,
            reader=None) -> tuple[dict, dict]:
    """Returns (analysis, paths) — one path for all roles and one per kind
    of role with enough postings, keyed like the analysis's views. Raises
    when there is nothing to work from.

    `reader` does the bulk work — reading every posting and grouping
    names — and `model` the two judgement calls (the resume comparison and
    the path). Reading is about 95% of the tokens, and its output is
    checked quote by quote, so a cheaper reader costs little accuracy.
    """
    reader = reader or model
    def report(stage: str, **detail):
        if on_progress:
            on_progress({"stage": stage, **detail})

    resumes = list_resumes(conn, user_id, active_only=True)
    if not resumes:
        raise ValueError("Upload a resume first — the path is built from it.")
    resume = merged_resume(resumes)

    reference = list(vocabulary.get("skill_names") or [])
    reference += [s.get("name", "") for s in resume["skills"]
                  if s.get("name") and s.get("name") not in reference]

    # Only postings from the last `days` days (0 or unset: everything
    # stored). Older postings are neither read nor counted.
    days = int(settings.get("days") or 0)
    since = ((date.today() - timedelta(days=days)).isoformat()
             if days > 0 else None)
    unread = len(extract.pending_roles(conn, user_id, limit, since))

    report("reading postings", done=0, total=unread)
    read = extract.extract_pending(
        conn, user_id, reader, reference, limit=limit,
        workers=int(settings.get("workers", 4)), on_progress=on_progress,
        # A handful of postings is not worth waiting on a batch for.
        use_batch=bool(settings.get("batch", True))
        and unread >= int(settings.get("batch_min_postings", 50)),
        since=since)

    # Every call this time failed: say why, rather than build a path from
    # an older, partial reading as if nothing went wrong.
    if read.get("aborted") or (read["failed_batches"] and not read["read"]):
        raise RuntimeError("Claude could not read the postings: "
                           + read.get("error", "unknown error"))

    postings = extract.read_postings(conn, user_id, since)
    if not postings:
        raise ValueError("No posting has been read yet. Run a search first, "
                         "or check the API key if reading failed.")
    rows = extract.evidence_rows(conn, user_id, since)

    report("grouping skill names")
    spelling = market.spelling_groups(rows)
    per_name: dict[str, set] = {}
    for row in rows:
        per_name.setdefault(spelling[row["name"]], set()).add(row["role_id"])
    counts = Counter({n: len(ids) for n, ids in per_name.items()})
    synonyms = market.merge_synonyms(reader, counts)
    names = {raw: synonyms.get(display, display)
             for raw, display in spelling.items()}

    report("counting demand")
    families = vocabulary.get("role_families") or []
    overall = market.build(rows, postings, families, names,
                           window_days=days or None)
    views = [(ALL, "All roles", overall)]
    # One view per kind of role with enough postings to count on. Smaller
    # kinds still count toward "All roles"; a path built from a handful
    # of postings would read as more certain than it is.
    minimum = int(settings.get("min_family_postings", MIN_FAMILY_POSTINGS))
    family_of = {p["id"]: market.family_of(p["title"], families)
                 for p in postings}
    for family in overall["families"]:
        if family["postings"] < minimum:
            continue
        ids = {r for r, f in family_of.items() if f == family["name"]}
        views.append((slug(family["name"]), family["name"], market.build(
            [r for r in rows if r["role_id"] in ids],
            [p for p in postings if p["id"] in ids],
            families, names, window_days=days or None)))

    report("comparing with your resume")
    # One comparison covers every view: each skill once, ordered by the
    # highest share it reaches in any view, so a skill that matters to one
    # kind of role is reviewed even when it is rare overall.
    best: dict[str, dict] = {}
    for _, _, view in views:
        for skill in view["skills"]:
            if (skill["name"] not in best
                    or skill["share"] > best[skill["name"]]["share"]):
                best[skill["name"]] = skill
    demand = sorted(best.values(), key=lambda s: (-s["share"], s["name"]))
    statuses = compare.compare(demand, resume, model,
                               review_limit=COMPARE_LIMIT)

    top = int(settings.get("top_gaps", rank.TOP_GAPS))
    ranked = {key: rank.rank(view, statuses, top) for key, _, view in views}

    report("writing your learning paths", done=0, total=len(views))

    def plan_for(item):
        key, name, view = item
        strengths = [s["name"] for s in view["skills"]
                     if statuses.get(s["name"], {}).get("status") == compare.HAVE
                     and s["category"] != "soft"][:10]
        return key, path.build_path(model, ranked[key]["gaps"], resume,
                                    strengths,
                                    focus=None if key == ALL else name)

    plans = {}
    with ThreadPoolExecutor(max_workers=max(1, min(len(views), 4))) as pool:
        for key, plan in pool.map(plan_for, views):
            plans[key] = plan

    analysis = {
        "postings": overall["postings"],
        "date_from": overall["date_from"],
        "date_to": overall["date_to"],
        "resume_labels": resume["labels"],
        "families": overall["families"],
        "views": [_view_snapshot(key, name, view, ranked[key], statuses)
                  for key, name, view in views],
        "window_days": days or None,
        "unverified": extract.unverified_total(conn, user_id, since),
        "unread": len(extract.pending_roles(conn, user_id, since=since)),
        "this_run": read,
    }
    return analysis, plans


def slug(name: str) -> str:
    return "-".join("".join(c if c.isalnum() else " " for c in
                            name.lower()).split())


def _view_snapshot(key: str, name: str, view: dict, ranked: dict,
                   statuses: dict) -> dict:
    """What the page needs from one view, not every posting id."""
    skills = []
    for skill in view["skills"][:60]:
        status = statuses.get(skill["name"], {})
        skills.append({k: skill[k] for k in
                       ("name", "category", "postings", "required", "share",
                        "samples")}
                      | {"status": status.get("status"),
                         "how": status.get("how", ""),
                         "related_to": status.get("related_to", ""),
                         "resume_evidence": status.get("evidence", "")})
    return {"key": key, "name": name, "postings": view["postings"],
            "skills": skills, "trends": view["trends"],
            "gaps": ranked["gaps"], "coverage": ranked["coverage"],
            "after": ranked["after"]}


def build_models(settings: dict):
    """(planner, reader). The reader defaults to the planner's model."""
    from .claude import DEFAULT_MODEL, ClaudeJson
    planner = ClaudeJson(settings.get("model") or DEFAULT_MODEL)
    read_model = settings.get("read_model")
    if not read_model or read_model == planner.model:
        return planner, planner
    return planner, ClaudeJson(read_model)


def work(db_path, user_id: int, path_id: int, model=None,
         limit: int | None = None) -> None:
    """Run one analysis on the calling thread; the row always ends terminal."""
    conn = connect(db_path)
    try:
        settings, vocabulary = load_settings()
        if model is None:
            model, reader = build_models(settings)
        else:
            reader = model

        def on_progress(event: dict) -> None:
            store.set_progress(conn, path_id, event.get("stage", ""), event)

        analysis, plan = analyse(conn, user_id, model, settings, vocabulary,
                                 on_progress=on_progress, limit=limit,
                                 reader=reader)
        names = getattr(model, "model", "")
        if reader is not model:
            names += f" (postings read by {getattr(reader, 'model', '')})"
        store.finish(conn, path_id, names, analysis, plan)
    except Exception as exc:
        logger.exception("Learning path %s failed", path_id)
        try:
            store.fail(conn, path_id, str(exc))
        except Exception:
            logger.exception("Could not record the failure of %s", path_id)
    finally:
        conn.close()


def run_in_background(db_path, user_id: int, path_id: int,
                      model=None) -> threading.Thread:
    thread = threading.Thread(target=work, args=(db_path, user_id, path_id,
                                                 model),
                              name=f"learning-path-{path_id}", daemon=True)
    thread.start()
    return thread
