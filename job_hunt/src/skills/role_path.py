"""A learning path toward ONE posting the user picked.

The market paths answer "what does this kind of role ask for?". This one
answers "what stands between me and THIS job?" — so the evidence is the
posting's own quoted requirements, not counts across the market. The market
still appears, as context: how many recent postings also ask for a gap,
which says whether closing it helps beyond this one application.

Same grounding rules as the market path: every skill quotes the posting,
every "you have it" quotes the resume, and the planner may only use the
gaps handed to it.
"""
import logging
import threading
from datetime import date, timedelta

from ..store import learning as store
from ..store.db import connect
from ..store.profile import list_resumes
from . import compare, extract, market, path
from .pipeline import build_models, load_settings, merged_resume

logger = logging.getLogger(__name__)

TECHNICAL = ("language", "tool", "platform", "concept", "practice")


def _role(conn, user_id: int, role_id: int) -> dict | None:
    row = conn.execute(
        """SELECT r.id, r.title, r.description, r.url,
                  r.description_captured, c.name AS company
             FROM role r JOIN company c ON c.id = r.company_id
            WHERE r.id = ? AND r.user_id = ?""", (role_id, user_id)).fetchone()
    return dict(row) if row else None


def market_counts(conn, user_id: int, days: int) -> tuple[dict, int]:
    """skill (spelling-folded) -> recent postings naming it, and how many
    recent postings were read. Spelling-folded only: no synonym call for
    one job, so "AWS" and "Amazon Web Services" count apart here."""
    since = ((date.today() - timedelta(days=days)).isoformat()
             if days > 0 else None)
    roles: dict[str, set] = {}
    for row in extract.evidence_rows(conn, user_id, since):
        roles.setdefault(extract.squash(row["name"]), set()).add(row["role_id"])
    total = len(extract.read_postings(conn, user_id, since))
    return {k: len(v) for k, v in roles.items()}, total


def analyse(conn, user_id: int, role_id: int, model, settings: dict,
            vocabulary: dict, reader=None, on_progress=None) -> tuple[dict, dict]:
    reader = reader or model

    def report(stage: str):
        if on_progress:
            on_progress({"stage": stage})

    role = _role(conn, user_id, role_id)
    if role is None:
        raise ValueError("That posting is not in your store.")
    if not role["description_captured"]:
        raise ValueError("This posting was stored without its description, "
                         "so there are no requirements to read.")
    resumes = list_resumes(conn, user_id, active_only=True)
    if not resumes:
        raise ValueError("Upload a resume first — the path is built from it.")
    resume = merged_resume(resumes)

    if not extract.is_read(conn, role_id):
        report("reading the posting")
        reference = list(vocabulary.get("skill_names") or [])
        reference += [s.get("name", "") for s in resume["skills"]
                      if s.get("name") and s.get("name") not in reference]
        extract.read_one(conn, role, reader, reference)

    rows = extract.role_skills(conn, role_id)
    spelling = market.spelling_groups(rows)
    skills: dict[str, dict] = {}
    for row in rows:
        name = spelling[row["name"]]
        skill = skills.setdefault(name, {
            "name": name, "category": row["category"], "variants": set(),
            "requirement": row["requirement"], "evidence": row["evidence"],
            "share": 0})
        skill["variants"].add(row["name"])
        if row["requirement"] == "required":
            skill["requirement"] = "required"
    demand = [dict(s, variants=sorted(s["variants"])) for s in skills.values()]

    report("comparing with your resume")
    statuses = compare.compare(demand, resume, model)

    days = int(settings.get("days") or 0)
    counts, total = market_counts(conn, user_id, days)

    have, gaps, soft = [], [], []
    for skill in demand:
        status = statuses.get(skill["name"], {})
        if skill["category"] not in TECHNICAL:
            soft.append({"name": skill["name"], "evidence": skill["evidence"],
                         "requirement": skill["requirement"]})
            continue
        entry = {"name": skill["name"], "category": skill["category"],
                 "requirement": skill["requirement"],
                 "posting_evidence": skill["evidence"],
                 "status": status.get("status"), "how": status.get("how", ""),
                 "related_to": status.get("related_to", ""),
                 "resume_evidence": status.get("evidence", ""),
                 "market": counts.get(extract.squash(skill["name"]), 0)}
        (have if entry["status"] == compare.HAVE else gaps).append(entry)

    # Requirements before nice-to-haves; then what the wider market asks
    # for most, since that gap pays off beyond this one application; then
    # what builds on the resume, since it closes faster.
    gaps.sort(key=lambda g: (g["requirement"] != "required", -g["market"],
                             g["status"] != compare.ADJACENT, g["name"]))
    window = f"the past {days} days" if days else "your store"
    for gap in gaps:
        label = ("A requirement" if gap["requirement"] == "required"
                 else "A nice-to-have")
        reasons = [f"{label} in this posting: “{gap['posting_evidence']}”."]
        if total:
            reasons.append(f"Also named in {gap['market']} of {total} postings"
                           f" from {window}.")
        if gap["status"] == compare.ADJACENT:
            related = gap["related_to"] or "a related skill"
            reasons.append(f"Builds on {related} from your resume.")
        gap["reasons"] = reasons
        gap["samples"] = [{"quote": gap["posting_evidence"],
                           "title": role["title"], "company": role["company"],
                           "url": role["url"]}]

    required = [s for s in have + gaps if s["requirement"] == "required"]
    analysis = {
        "role_id": role_id, "title": role["title"],
        "company": role["company"], "url": role["url"],
        "resume_labels": resume["labels"],
        "required": len(required),
        "have_required": sum(1 for s in required
                             if s["status"] == compare.HAVE),
        "have": have, "gaps": gaps, "soft": soft,
        "market_postings": total, "window_days": days or None,
    }

    if not gaps:
        return analysis, {"summary": "", "stages": [], "left_out": []}

    report("writing the path")
    intro = (f"This path is for ONE job: {role['title']} at "
             f"{role['company']}. The goal is to become a strong candidate "
             f"for this posting. Each skill below is quoted from it. Use only "
             f"as many stages as these skills need; one or two is fine.")
    plan = path.build_path(model, gaps, resume,
                           [s["name"] for s in have][:10], intro=intro)
    return analysis, plan


def work(db_path, user_id: int, row_id: int, role_id: int,
         model=None) -> None:
    """Build one job's path on the calling thread; the row always ends terminal."""
    conn = connect(db_path)
    try:
        settings, vocabulary = load_settings()
        if model is None:
            model, reader = build_models(settings)
        else:
            reader = model

        def on_progress(event: dict) -> None:
            store.role_progress(conn, row_id, event.get("stage", ""), event)

        analysis, plan = analyse(conn, user_id, role_id, model, settings,
                                 vocabulary, reader=reader,
                                 on_progress=on_progress)
        store.role_finish(conn, row_id, getattr(model, "model", ""),
                          analysis, plan)
    except Exception as exc:
        logger.exception("Learning path for role %s failed", role_id)
        try:
            store.role_fail(conn, row_id, str(exc))
        except Exception:
            logger.exception("Could not record the failure of %s", row_id)
    finally:
        conn.close()


def run_in_background(db_path, user_id: int, row_id: int, role_id: int,
                      model=None) -> threading.Thread:
    thread = threading.Thread(target=work,
                              args=(db_path, user_id, row_id, role_id, model),
                              name=f"role-path-{role_id}", daemon=True)
    thread.start()
    return thread
