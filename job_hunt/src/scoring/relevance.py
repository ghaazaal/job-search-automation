"""Is this posting one of the roles the user searches for?

Title only. The description is not consulted: an ad for a nurse can
mention "data" a dozen times, and 41% of the store arrived that way.

Phrases only, word-bounded, same discipline as `work_mode` — a bare-word
test is what admitted "Data Center & Edge Infrastructure Lead".
"""
import re
from functools import lru_cache

from .matching import bounded


@lru_cache(maxsize=None)
def _patterns(phrases: tuple[str, ...]) -> tuple[re.Pattern, ...]:
    """One compiled, bounded pattern per phrase, cached per phrase-tuple.

    Called up to twice per `is_target_role` call — once for the exclude
    phrases, once for the include phrases — so caching means each
    category's patterns are compiled once per run rather than once per
    title checked. That's a smaller win than `_phrase_patterns` in
    `matching.py`, which amortises compilation against three full-body
    scans per job; here it's amortised against a single short title
    string, but still worth it once a run checks more than a couple of
    titles. `cfg` values arrive as lists (unhashable), so callers pass
    an already-lowered, already-stripped tuple as the cache key — and
    vocabulary.yaml only ever produces two distinct tuples (include,
    exclude) in a process's lifetime.
    """
    return tuple(re.compile(bounded(p)) for p in phrases)


def _phrases(cfg: dict, key: str) -> tuple[str, ...]:
    """The phrase list at `cfg[key]`, lowered and stripped of blanks.

    Order preserved, not deduped or sorted — matches the inline
    comprehension `work_mode` uses for its own phrase lists in
    matching.py. Order has no effect on the match outcome here, only on
    which duplicate a cache lookup would see first, so there is no
    reason to diverge from the sibling.
    """
    return tuple(str(p).strip().lower()
                 for p in cfg.get(key) or [] if str(p).strip())


def is_target_role(title: str, cfg: dict) -> bool:
    """True when the title names a searched-for role and no trap phrase.

    Exclusions are checked first and win outright: "Data Engineer, Data
    Center Operations" matches an include phrase and is still a
    data-centre job.

    An empty include list accepts everything not excluded, so a
    misconfigured vocabulary degrades to today's behaviour rather than
    rejecting an entire run.
    """
    text = (title or "").strip().lower()
    if not text:
        return False
    cfg = cfg or {}

    exclude = _phrases(cfg, "exclude")
    if exclude and any(p.search(text) for p in _patterns(exclude)):
        return False

    include = _phrases(cfg, "include")
    if not include:
        return True
    return any(p.search(text) for p in _patterns(include))
