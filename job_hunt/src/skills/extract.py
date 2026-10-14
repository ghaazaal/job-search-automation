"""Claude reads postings for skills, once each, with the posting's own words
as evidence.

The rule this module exists to enforce: a skill is stored only when the
quote Claude gives for it is actually in the posting. Claude's reading
decides WHAT a phrase means ("ETL orchestration with Airflow" is Apache
Airflow); the quote check decides whether the phrase exists. A skill whose
quote is not found is dropped and counted, never stored — the same
"silence is the default" rule the geography checks follow.
"""
import logging
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from ..store.db import transaction

logger = logging.getLogger(__name__)

CATEGORIES = ("language", "tool", "platform", "concept", "practice", "soft")
REQUIREMENTS = ("required", "preferred")

# Postings per request. Several per call keeps the fixed cost of the
# instructions low; few enough that one bad answer costs little.
BATCH_SIZE = 5

_MAX_EVIDENCE = 240

SYSTEM = """You read job postings for data roles and list the skills each one asks for.

For every posting, list each distinct skill the posting asks the candidate to have:
- name: the skill's common short name, e.g. "SQL", "Python", "dbt", "Apache Airflow", "Snowflake", "AWS", "Power BI", "Data modeling", "A/B testing", "Stakeholder communication". Use the same name for the same skill across postings. When a name from the reference list fits, use it exactly as written there.
- category: one of language (programming/query languages), tool (software products and libraries), platform (cloud and data platforms), concept (bodies of knowledge such as data modeling or statistics), practice (ways of working such as CI/CD, code review, agile), soft (communication, leadership and similar).
- requirement: "required" when the posting presents it as a requirement or a core part of the job; "preferred" when it is a nice-to-have, bonus or plus.
- evidence: a short quote copied exactly, character for character, from that posting's text, that shows the skill is asked for. Keep it short: the fewest words that show it, at most 12. Never paraphrase, translate, or join words from different places.

Only list skills the posting asks the candidate for. Skip the company's own product names, benefits, and skills mentioned only as something the company does. If a posting asks for no skills, return an empty list for it. Postings may be in any language; keep evidence in the posting's language and write the name in English."""

SCHEMA = {
    "type": "object",
    "properties": {
        "postings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "skills": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "category": {"type": "string",
                                             "enum": list(CATEGORIES)},
                                "requirement": {"type": "string",
                                                "enum": list(REQUIREMENTS)},
                                "evidence": {"type": "string"},
                            },
                            "required": ["name", "category", "requirement",
                                         "evidence"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["id", "skills"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["postings"],
    "additionalProperties": False,
}

_ALNUM = re.compile(r"[^\w]+", re.UNICODE)


def squash(text: str) -> str:
    """Letters and digits only, lowercased.

    Scraped text arrives with curly quotes, mangled apostrophes (U+FFFD),
    bullets and collapsed whitespace; Claude's copy of a phrase will not
    reproduce those byte for byte. Comparing only the letters and digits,
    in order, keeps the check strict about WORDS and blind to punctuation.
    """
    return _ALNUM.sub("", (text or "").lower()).replace("_", "")


def verified(evidence: str, posting_text: str) -> bool:
    """Whether the quote is really in the posting."""
    quote = squash(evidence)
    # A quote of a few characters proves nothing: "sql" is in "nosql".
    if len(quote) < 6:
        return False
    return quote in squash(posting_text)


def pending_roles(conn: sqlite3.Connection, user_id: int,
                  limit: int | None = None) -> list[dict]:
    """Postings on the map with a captured description, not yet read."""
    sql = """SELECT r.id, r.title, r.description
               FROM role r
               LEFT JOIN skill_extraction x ON x.role_id = r.id
              WHERE r.user_id = ? AND r.dropped_at IS NULL
                AND r.description_captured = 1 AND x.role_id IS NULL
              ORDER BY r.id DESC"""
    params: list = [user_id]
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    return [dict(row) for row in conn.execute(sql, params)]


def _prompt(batch: list[dict], reference: list[str]) -> str:
    parts = ["Reference names (use these exact spellings when they fit): "
             + ", ".join(reference), ""]
    for role in batch:
        parts.append(f'<posting id="{role["id"]}">')
        parts.append(f'Title: {role["title"]}')
        parts.append(role["description"] or "")
        parts.append("</posting>")
    parts.append("")
    parts.append(f"Return one entry for each of the {len(batch)} postings above.")
    return "\n".join(parts)


def _clean(skill: dict, posting_text: str) -> dict | None:
    name = " ".join(str(skill.get("name") or "").split())[:80]
    evidence = " ".join(str(skill.get("evidence") or "").split())
    if not name or skill.get("category") not in CATEGORIES:
        return None
    if skill.get("requirement") not in REQUIREMENTS:
        return None
    if len(evidence) > _MAX_EVIDENCE or not verified(evidence, posting_text):
        return None
    return {"name": name, "category": skill["category"],
            "requirement": skill["requirement"], "evidence": evidence}


def _store(conn: sqlite3.Connection, role: dict, skills: list,
           model_name: str) -> tuple[int, int]:
    text = f'{role["title"]}\n{role["description"] or ""}'
    kept, unverified, seen = [], 0, set()
    for raw in skills or []:
        clean = _clean(raw if isinstance(raw, dict) else {}, text)
        if clean is None:
            unverified += 1
            continue
        key = clean["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        kept.append(clean)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with transaction(conn):
        conn.execute("DELETE FROM posting_skill WHERE role_id = ?", (role["id"],))
        conn.executemany(
            "INSERT INTO posting_skill (role_id, name, category, requirement,"
            " evidence) VALUES (?, ?, ?, ?, ?)",
            [(role["id"], s["name"], s["category"], s["requirement"],
              s["evidence"]) for s in kept])
        conn.execute(
            "INSERT OR REPLACE INTO skill_extraction (role_id, extracted_at,"
            " model, kept, unverified) VALUES (?, ?, ?, ?, ?)",
            (role["id"], now, model_name, len(kept), unverified))
    return len(kept), unverified


def extract_pending(conn: sqlite3.Connection, user_id: int, model,
                    reference: list[str], limit: int | None = None,
                    workers: int = 4, on_progress=None,
                    use_batch: bool = False) -> dict:
    """Read every unread posting. Returns counts for the progress line.

    Two ways to send the requests. `use_batch` hands them all to Claude's
    Message Batches API at half price and waits (minutes, up to an hour);
    otherwise they run on a small thread pool and finish sooner. Either
    way every database write happens here, on the calling thread, because
    a SQLite connection belongs to the thread that opened it. A request
    that fails leaves its postings unread for the next analysis — a
    failure never marks a posting done.
    """
    roles = pending_roles(conn, user_id, limit)
    batches = [roles[i:i + BATCH_SIZE] for i in range(0, len(roles), BATCH_SIZE)]
    totals = {"postings": len(roles), "read": 0, "skills": 0,
              "unverified": 0, "failed_batches": 0}
    if not batches:
        return totals

    model_name = getattr(model, "model", "unknown")

    def absorb(batch, answer):
        by_id = {}
        for entry in (answer or {}).get("postings") or []:
            if isinstance(entry, dict) and isinstance(entry.get("id"), int):
                by_id[entry["id"]] = entry.get("skills") or []
        for role in batch:
            # A posting the answer skipped stays unread rather than being
            # recorded as "asks for nothing".
            if role["id"] not in by_id:
                continue
            kept, unverified = _store(conn, role, by_id[role["id"]],
                                      model_name)
            totals["read"] += 1
            totals["skills"] += kept
            totals["unverified"] += unverified

    def failed(batch, exc):
        logger.warning("Skill extraction failed for %d postings: %s",
                       len(batch), exc)
        totals["failed_batches"] += 1
        totals.setdefault("error", str(exc)[:300])

    if use_batch and hasattr(model, "batch"):
        def waiting(done, total):
            if on_progress:
                on_progress({"stage": "waiting for Claude's batch",
                             "done": done, "total": total})
        requests = [(str(i), SYSTEM, _prompt(batch, reference))
                    for i, batch in enumerate(batches)]
        try:
            answers = model.batch(requests, schema=SCHEMA, effort="low",
                                  on_wait=waiting)
        except Exception as exc:
            failed(roles, exc)
            totals["aborted"] = True
            return totals
        for i, batch in enumerate(batches):
            answer = answers.get(str(i))
            if answer is None or isinstance(answer, Exception):
                failed(batch, answer or "no result returned")
            else:
                absorb(batch, answer)
        return totals

    def call(batch):
        return model(system=SYSTEM, prompt=_prompt(batch, reference),
                     schema=SCHEMA, effort="low")

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(call, batch): batch for batch in batches}
        for future in as_completed(futures):
            batch = futures[future]
            try:
                answer = future.result()
            except Exception as exc:
                failed(batch, exc)
                # Nothing has worked yet and three calls have failed: this
                # is a key, credit or network problem, not one bad posting.
                # Stop rather than send every remaining batch to fail too.
                if totals["read"] == 0 and totals["failed_batches"] >= 3:
                    for pending in futures:
                        pending.cancel()
                    totals["aborted"] = True
                    break
                continue
            absorb(batch, answer)
            if on_progress:
                on_progress({"stage": "reading postings",
                             "done": totals["read"],
                             "total": totals["postings"]})
    return totals


def evidence_rows(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    """Every stored skill mention for the user's live postings."""
    rows = conn.execute(
        """SELECT ps.role_id, ps.name, ps.category, ps.requirement,
                  ps.evidence, r.title, r.url, r.posted_date,
                  c.name AS company, run.started_at AS first_seen
             FROM posting_skill ps
             JOIN role r ON r.id = ps.role_id
             JOIN company c ON c.id = r.company_id
             JOIN run ON run.id = r.first_seen_run_id
            WHERE r.user_id = ? AND r.dropped_at IS NULL""", (user_id,))
    return [dict(row) for row in rows]


def read_postings(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    """Every live posting that has been read, including ones naming nothing."""
    rows = conn.execute(
        """SELECT r.id, r.title, r.posted_date, run.started_at AS first_seen
             FROM role r
             JOIN skill_extraction x ON x.role_id = r.id
             JOIN run ON run.id = r.first_seen_run_id
            WHERE r.user_id = ? AND r.dropped_at IS NULL""", (user_id,))
    return [dict(row) for row in rows]


def unverified_total(conn: sqlite3.Connection, user_id: int) -> int:
    row = conn.execute(
        """SELECT COALESCE(SUM(x.unverified), 0) AS n
             FROM skill_extraction x JOIN role r ON r.id = x.role_id
            WHERE r.user_id = ? AND r.dropped_at IS NULL""",
        (user_id,)).fetchone()
    return int(row["n"])

