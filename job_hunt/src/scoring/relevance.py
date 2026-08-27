"""Is this posting one of the roles the user searches for?

Title only. The description is not consulted: an ad for a nurse can
mention "data" a dozen times, and 41% of the store arrived that way.

Phrases only, word-bounded, same discipline as `work_mode` — a bare-word
test is what admitted "Data Center & Edge Infrastructure Lead".
"""
import re
from functools import lru_cache


@lru_cache(maxsize=None)
def _patterns(phrases: tuple[str, ...]) -> tuple[re.Pattern, ...]:
    """One compiled, bounded pattern per phrase, cached per phrase-tuple.

    Called once per scraped job, so the compile cost is paid once per
    run rather than once per job. `cfg` arrives as lists (unhashable),
    so callers pass an already-lowered tuple as the cache key.
    """
    return tuple(re.compile(r"(?<!\w)" + re.escape(p) + r"(?!\w)")
                 for p in phrases)


def _phrases(cfg: dict, key: str) -> tuple[str, ...]:
    return tuple(sorted({str(p).strip().lower()
                         for p in cfg.get(key) or [] if str(p).strip()}))


def is_relevant(title: str, cfg: dict) -> bool:
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
