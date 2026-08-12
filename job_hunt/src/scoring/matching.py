"""Pure matching rules, shared by the scorer.

Every function takes plain data and returns plain data — no config objects, no
database, no LLM. The scorer composes them. They live apart from it because
these are the rules a reader will want to argue with, and an argument is
easier to settle against a unit test than against a 90-line method.
"""
import re

# Ordered, so the distance between two of them is an integer.
BANDS = ("junior", "mid", "senior", "exec")

_TOKEN_RE = re.compile(r"[a-z0-9+#]+")


def has_term(term: str, haystack: str) -> bool:
    """Word-boundary match.

    Descriptions are long enough that substring matching produces false
    positives on short tokens — 'opt' inside 'optimize', 'bi' inside
    'ambitious'. Boundaries keep multi-word terms ('power bi') working.

    Uses lookarounds rather than `\\b` because `\\b` only anchors on a
    transition to/from a word character, and a term ending in `+` or `#`
    (a skill named "C++", say) has no such transition at its own edge —
    `\\b` would silently fail to match it in the ordinary case of the term
    being followed by whitespace or punctuation.
    """
    term = (term or "").strip()
    if not term:
        return False
    pattern = r"(?<!\w)" + re.escape(term) + r"(?!\w)"
    return bool(re.search(pattern, haystack))


def tokens(text: str) -> list[str]:
    """Lowercased words. `+` and `#` survive so C++ and C# stay one token."""
    return _TOKEN_RE.findall((text or "").lower())


def significant(text: str, stopwords) -> list[str]:
    """Tokens worth comparing: over two characters, and not a stopword."""
    stop = set(stopwords or ())
    return [t for t in tokens(text) if len(t) > 2 and t not in stop]


def title_tier(job_title: str, target_roles: list[dict], stopwords) -> str:
    """How well a posting's title matches any of the resume's target roles.

    Returns 'exact', 'all_tokens', 'some_tokens' or 'none'. The caller turns
    that into points, so the rule and its weight stay separable.

    `all_tokens` needs at least two significant tokens to fire. Without that
    floor a target role of `BI Developer` — which reduces to the single token
    `developer`, since `bi` is too short to be significant — would let
    `Frontend Developer` score as though the whole role matched.
    """
    title = (job_title or "").lower()
    if not title:
        return "none"

    phrases: list[str] = []
    for role in target_roles or []:
        phrases.append(str(role.get("title") or ""))
        phrases.extend(str(alias) for alias in (role.get("aliases") or []))
    phrases = [p.strip().lower() for p in phrases if p and p.strip()]

    if any(has_term(phrase, title) for phrase in phrases):
        return "exact"

    present = set(tokens(title))
    best = "none"
    for phrase in phrases:
        wanted = significant(phrase, stopwords)
        if not wanted:
            continue
        if len(wanted) >= 2 and all(w in present for w in wanted):
            return "all_tokens"
        if any(w in present for w in wanted):
            best = "some_tokens"
    return best


def seniority_band(job_title: str, seniority_cfg: dict) -> str:
    """The band a posting's title implies.

    Checked exec-first because the lists overlap — `director` and `head of`
    appear in both the senior and the exec list, and an exec title is an exec
    title.
    """
    title = (job_title or "").lower()
    if any(k in title for k in seniority_cfg.get("exec_keywords") or []):
        return "exec"
    if any(k in title for k in seniority_cfg.get("junior_keywords") or []):
        return "junior"
    if any(k in title for k in seniority_cfg.get("senior_keywords") or []):
        return "senior"
    return "mid"


def band_distance(one: str, other: str) -> int:
    """How many bands apart two seniority levels are.

    Anything unrecognised reads as `mid` rather than raising — a resume
    written before the field existed should score, not crash the run.
    """
    def _index(band) -> int:
        return BANDS.index(band) if band in BANDS else BANDS.index("mid")

    return abs(_index(one) - _index(other))


def resume_terms(skills: list[dict]) -> set[str]:
    """Every string that counts as "this person has that" — names and aliases.

    Lowercased, because everything it is compared against is lowercased.
    """
    terms: set[str] = set()
    for skill in skills or []:
        name = str(skill.get("name") or "").strip().lower()
        if name:
            terms.add(name)
        for alias in skill.get("aliases") or []:
            alias = str(alias).strip().lower()
            if alias:
                terms.add(alias)
    return terms


def skill_hits(body: str, skills: list[dict],
               scores: dict) -> tuple[list[str], int]:
    """The resume's skills that this posting names, and what they earn.

    Returns display names rather than whichever alias happened to match, so
    the reason sentence reads like the resume. Core skills are considered
    first, so the cap is spent on the strongest signals and the sentence names
    them in that order.
    """
    core_points = scores.get("core", 5)
    working_points = scores.get("working", 2)
    cap = scores.get("cap", 20)

    ordered = sorted(skills or [],
                     key=lambda s: 0 if s.get("tier") == "core" else 1)

    matched: list[str] = []
    total = 0
    for skill in ordered:
        name = str(skill.get("name") or "").strip()
        if not name:
            continue
        candidates = [name.lower()]
        candidates += [str(a).strip().lower() for a in skill.get("aliases") or []]
        if any(has_term(c, body) for c in candidates if c):
            matched.append(name)
            total = min(total + (core_points if skill.get("tier") == "core"
                                 else working_points), cap)
    return matched, total


def gaps(description: str, market_tools, mine: set[str]) -> list[str]:
    """Tools the posting names that the resume does not carry.

    Read from the description only — a title is not evidence that a tool is
    actually used on the job.
    """
    body = (description or "").lower()
    return [tool for tool in market_tools or []
            if has_term(tool, body) and tool.lower() not in mine]


def mismatch_penalty(description: str, market_tools, mine: set[str],
                     cfg: dict) -> int:
    """Points off when a posting is dense with tooling that is not yours.

    Replaces the old hardcoded legacy_tech/frontend_tech lists. Because the
    rule is a ratio against the reader's own skills, a React-heavy posting
    still lands hard for someone running dbt and lands not at all for someone
    whose resume is React — which is the whole point.
    """
    body = (description or "").lower()
    named = [tool for tool in market_tools or [] if has_term(tool, body)]
    if len(named) < cfg.get("min_tools", 4):
        # Too small a sample to conclude anything from.
        return 0

    ratio = sum(1 for tool in named if tool.lower() in mine) / len(named)
    if ratio < cfg.get("hard_ratio", 0.25):
        return cfg.get("hard_value", 20)
    if ratio < cfg.get("soft_ratio", 0.5):
        return cfg.get("soft_value", 10)
    return 0
