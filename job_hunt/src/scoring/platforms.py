"""Talent platforms — companies whose "job" is a pool to join.

Proxify, Toptal and the like recruit freelancers to place later; their
postings are not an employer's opening. The map hides them and counts them
in its header (plan 2026-09-25, decision D3: hidden where roles are read,
so stored rows go too and removing a name brings them back).
"""
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

VOCABULARY_PATH = Path(__file__).resolve().parent.parent.parent / "vocabulary.yaml"


@lru_cache(maxsize=1)
def _vocabulary_block() -> dict:
    with open(VOCABULARY_PATH, encoding="utf-8") as handle:
        return yaml.safe_load(handle).get("talent_platforms") or {}


def _fold(name: str) -> list[str]:
    """Lowercase, accents and punctuation gone, split into words."""
    plain = unicodedata.normalize("NFKD", name)
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", plain.lower()).split()


def is_talent_platform(name: str | None, cfg: dict | None = None) -> bool:
    """True when `name` IS a listed platform, legal suffix aside.

    Exact equality, never substring: "Toptal Recruiting Partners" is a
    different company from Toptal."""
    if not name:
        return False
    cfg = _vocabulary_block() if cfg is None else cfg
    suffixes = {" ".join(_fold(s)) for s in cfg.get("legal_suffixes", [])}
    names = {" ".join(_fold(n)) for n in cfg.get("names", [])}
    words = _fold(name)
    if len(words) > 1 and words[-1] in suffixes:
        words = words[:-1]
    return " ".join(words) in names
