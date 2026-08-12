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
