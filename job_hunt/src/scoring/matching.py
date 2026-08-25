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
    return bool(re.search(_bounded(term), haystack))


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

    A missing or unrecognised tier is treated as 'working' rather than
    raising, for the same reason band_distance treats an unrecognised
    seniority as mid.

    Expects body to already be lowercased — unlike gaps/mismatch_penalty,
    this does not lowercase internally, to avoid re-lowercasing a body the
    caller may reuse across several skill_hits calls.
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


# How far past a list phrase ("open to candidates in ...") country names
# are looked for. A fixed window rather than sentence-splitting, because
# "u.s." breaks naive period logic. Real eligibility lists commonly run
# 15-30 countries written out in full ("united kingdom", "united arab
# emirates") — a window too narrow truncates the list before it reaches
# the reader's own country and reads a false exclusion into silence. 400
# chars comfortably covers such a list without reading so far past it
# that unrelated prose starts counting as candidates.
_LIST_WINDOW = 400


def _display_name(name: str) -> str:
    """`uk` -> "UK", `united kingdom` -> "United Kingdom"."""
    name = (name or "").strip().lower()
    return name.upper() if len(name) <= 3 else name.title()


def _join_names(names: list[str], maybe_more: bool = False) -> str:
    """`[a, b, c]` -> "a, b and c"; four or more cap at three + others.

    `maybe_more` forces the "and others" suffix even under four names —
    set when a window that produced a hit ran out before the body did,
    so the enumeration may have continued with countries we never read
    that far to see.
    """
    if not names:
        return ""
    if len(names) > 3:
        return f"{', '.join(names[:3])} and others"
    if maybe_more:
        return f"{', '.join(names)} and others"
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _bounded(term: str) -> str:
    """The has_term lookaround pattern, reusable inside larger regexes."""
    return r"(?<!\w)" + re.escape(term) + r"(?!\w)"


def _find_bounded(term: str, body: str, start: int):
    """A bounded match for `term` at or after `start`, or None.

    Searches the real, unbounded `body` rather than a slice — slicing at
    a window edge can cut a name mid-word ("ukraine" clipped to "uk") and
    the boundary lookahead would then pass, because the engine has
    nothing past the cut to check against. `start` only constrains where
    a match may *begin*; the caller is responsible for rejecting a match
    that starts at or past its own window's limit.
    """
    term = (term or "").strip()
    if not term:
        return None
    return re.compile(_bounded(term)).search(body, start)


def _in_window(term: str, body: str, start: int, limit: int) -> bool:
    """Whether `term` is bounded-matched somewhere inside [start, limit)."""
    match = _find_bounded(term, body, start)
    return bool(match and match.start() < limit)


def _named_anywhere_after(term: str, body: str, start: int) -> bool:
    """Whether `term` is bounded-matched anywhere at or after `start` —
    no `limit`, unlike `_in_window`.

    Used only for the user's own country. If a posting names it anywhere
    after a list phrase — even hundreds of characters into a bullet list,
    well past any display window — the safe and correct verdict is
    eligible. A limit here is exactly what let a real, later mention of
    the user's own country get discarded as exclusion evidence instead of
    read as what it is.
    """
    return bool(_find_bounded(term, body, start))


def _window_hits(body: str, start: int, limit: int,
                 countries: dict, user_country: str) -> dict:
    """Foreign country codes named within one list window.

    Maps code -> (match.start(), match.end()) of its first occurrence at
    or after `start` that begins before `limit`. Never includes the
    user's own country — by the time this runs, phase 1 has already
    returned "eligible" if any window named it, checked to end of body.
    """
    hits: dict[str, tuple[int, int]] = {}
    for code, names in countries.items():
        if code == user_country:
            continue
        for name in names:
            match = _find_bounded(name, body, start)
            if match and match.start() < limit:
                hits[code] = (match.start(), match.end())
                break
    return hits


def geo_verdict(body: str, user_country: str,
                cfg: dict) -> tuple[str, str | None]:
    """What a posting says about where it hires, judged for one user.

    Returns one of:
      ("eligible", None)      — a standalone worldwide phrase, a list
                                phrase naming the user's country anywhere
                                after it (no window limit — see below), an
                                anywhere-word in a window, or a region the
                                user's country belongs to
      ("restricted", "UK")    — a restriction template fired with a foreign
                                country in the slot
      ("excluded", "UK, ...") — a list window names known countries, none
                                of them the user's; the display gains "and
                                others" if a hit-bearing window may have
                                continued past what was scanned
      ("unknown", None)       — nothing matched, or `user_country` is
                                unset: the check cannot run, so nothing is
                                claimed

    Checked in that order — positive evidence anywhere in the body settles
    it before any flag is considered. The user's own country is searched
    from each list phrase to the end of the body, not capped at the
    display window: a country list can run for hundreds of characters
    (bullet points, numbered lists), and if the user's own country
    appears anywhere in it the correct verdict is eligible regardless of
    how far in. Anywhere-words and regions keep the window cap — their
    misses stay silent rather than search-everywhere, since a stray
    "globally" elsewhere in the body is not list evidence. Because the
    user's own country is never missed this way, an "excluded" verdict
    needs no separate check that the enumeration "finished" — the eligible
    pass already ruled out the user's own country appearing anywhere
    past the window; what an unfinished window leaves genuinely unknown
    is only whether *other*, unrecognised countries follow, which is why
    such a window still contributes but earns the "and others" hedge.
    Regions are eligible-only evidence: a region that does not include the
    user yields silence, never exclusion, because membership is fuzzy at
    the edges. An "excluded" verdict is only claimed when the user's
    country is one this config knows the names of — otherwise it might be
    in the list, just unrecognised. Matching uses the same lookaround
    boundaries as has_term ('us' must not fire inside 'campus');
    restriction templates allow an optional `the ` before the country
    name.
    """
    user_country = (user_country or "").strip().lower()
    if not user_country:
        return ("unknown", None)
    body = (body or "").lower()
    cfg = cfg or {}
    countries = {
        str(code).strip().lower():
            [str(n).strip().lower() for n in (names or []) if str(n).strip()]
        for code, names in (cfg.get("countries") or {}).items()
    }

    windows: list[tuple[int, int]] = []
    for phrase in cfg.get("list_phrases") or []:
        phrase = str(phrase).strip().lower()
        if not phrase:
            continue
        for match in re.finditer(_bounded(phrase), body):
            windows.append((match.end(), match.end() + _LIST_WINDOW))
    # Text order, not config order — a list phrase configured first can
    # still occur later in the body than another one. Processing windows
    # out of text order would let a later-occurring window's match for a
    # repeated country be recorded (via setdefault, below) ahead of an
    # earlier one, reporting the wrong position for it.
    windows.sort(key=lambda w: w[0])

    # 1. Eligible — every window is scanned before anything may flag.
    user_names = countries.get(user_country) or []
    anywhere = [str(w).strip().lower()
                for w in cfg.get("anywhere_words") or []]

    # Standalone worldwide statements ("open to candidates worldwide") open
    # no list window — the phrase itself is the evidence. Only phrases a
    # following country cannot grammatically narrow belong in this list.
    for phrase in cfg.get("eligible_phrases") or []:
        phrase = str(phrase).strip().lower()
        if phrase and has_term(phrase, body):
            return ("eligible", None)

    for start, limit in windows:
        # Unlimited on purpose — see the docstring.
        if any(_named_anywhere_after(name, body, start) for name in user_names):
            return ("eligible", None)
        if any(_in_window(word, body, start, limit)
               for word in anywhere if word):
            return ("eligible", None)
        for region in cfg.get("regions") or []:
            codes = {str(c).strip().lower()
                     for c in (region.get("codes") or [])}
            names = [str(n).strip().lower()
                     for n in (region.get("names") or [])]
            if user_country in codes and any(
                    _in_window(n, body, start, limit) for n in names if n):
                return ("eligible", None)

    # 2. Restricted — a template stating where hiring is locked to.
    # Most bodies carry no restriction language at all, so a template
    # whose literal text around {country} never appears in the body is
    # filtered out with a plain substring check before it ever reaches
    # the per-country-name regex loop — cheap insurance against building
    # and running (country names) x (templates) patterns for nothing.
    templates = cfg.get("templates") or []
    candidates: list[tuple[str, str]] = []
    for template in templates:
        before, _, after = str(template).lower().partition("{country}")
        before_stem, after_stem = before.strip(), after.strip()
        if before_stem and before_stem not in body:
            continue
        if after_stem and after_stem not in body:
            continue
        candidates.append((before, after))

    for code, names in countries.items():
        if code == user_country:
            continue
        for name in names:
            for before, after in candidates:
                pattern = (r"(?<!\w)" + re.escape(before) + r"(?:the\s+)?"
                           + re.escape(name) + re.escape(after) + r"(?!\w)")
                if re.search(pattern, body):
                    return ("restricted", _display_name(names[0]))

    # 3. Excluded — list windows that name countries, none of them the
    # user's. The user's absence was verified through end of body by the
    # eligible pass above; what remains unknown is only whether MORE
    # countries follow past wherever a given window stopped reading. A
    # window is "full" when its limit falls short of the body — the
    # enumeration may have continued beyond it — and any hit-bearing full
    # window forces the "and others" hedge on the whole result, even when
    # three or fewer countries were actually recognised.
    if windows and user_names:
        hits: dict[str, int] = {}
        maybe_more = False
        for start, limit in windows:
            window_hits = _window_hits(body, start, limit,
                                       countries, user_country)
            if window_hits:
                if limit < len(body):
                    maybe_more = True
                for code, (match_start, _) in window_hits.items():
                    hits.setdefault(code, match_start)
        if hits:
            ordered = sorted(hits, key=hits.get)
            return ("excluded", _join_names(
                [_display_name(countries[code][0]) for code in ordered],
                maybe_more=maybe_more))

    return ("unknown", None)
