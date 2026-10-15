"""Does a tailored line say anything its sources did not?

The prompt forbids inventing; this is the check that does not trust the
prompt. A tailored line passes when every number in it, every known skill
or tool it names, and every proper-noun-looking word in it (capitalised
mid-sentence, or capitalised inside the word: "Snowflake", "ClickHouse",
"AWS") also appears in the master lines it cites. Rewording verbs and
reordering pass; a new tool, a new figure or a new employer name does not.

What this cannot see: a plain lower-case claim ("led the team") that the
sources do not make. The prompt's hard rule covers that; the card says
the check is about named things and figures, never that it proves more.
"""
import re

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#&./'-]*")
_SENTENCE_END = re.compile(r"[.!?:;•(\[]\s*$")
# Emails and links are copied, never written: a contact line or a
# portfolio link that is not in the sources is made up, whatever its case.
_ADDRESS = re.compile(
    r"\S+@\S+|\S*(?:https?://|www\.)\S+"
    r"|\S+\.(?:com|org|net|io|dev|me|co|ai|app|info|am|ir|uk|de)"
    r"(?![A-Za-z0-9])(?:/\S*)?",
    re.IGNORECASE)


# PDF extraction turns curly quotes, dashes and bullets into U+FFFD or
# their typographic forms; the master and the model write them plainly.
_FOLD = str.maketrans({"�": "'", "’": "'", "‘": "'",
                       "–": "-", "—": "-", "×": "x"})


def _norm(text: str) -> str:
    return " ".join((text or "").translate(_FOLD).lower().split())


def _numbers(text: str) -> set[str]:
    found = set()
    for raw in _NUMBER.findall(text or ""):
        found.add(raw)
        found.add(raw.replace(",", ""))
    return found


def _has(term: str, text_norm: str) -> bool:
    """Word-bounded, case-insensitive containment."""
    term = _norm(term).strip(".,;:")
    if not term:
        return True
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])",
                     text_norm) is not None


def _named_words(text: str) -> list[str]:
    """Words that look like names: capitalised anywhere but a sentence's
    first word, or with a capital inside the word, or all caps."""
    out = []
    for match in _WORD.finditer(text or ""):
        # "1B+", "10M+", "22 GB" after a digit: a unit, judged with its number.
        if match.start() and text[match.start() - 1].isdigit():
            continue
        word = match.group(0).rstrip(".,;:'/-")
        if word.endswith("'s"):
            word = word[:-2]
        if len(word) < 2 or not any(c.isupper() for c in word):
            continue
        inner_caps = any(c.isupper() for c in word[1:])
        before = text[:match.start()]
        starts_sentence = not before.strip() or bool(
            _SENTENCE_END.search(before))
        if inner_caps or not starts_sentence:
            out.append(word)
    return out


def unsupported(text: str, sources: str, terms: list[str]) -> list[str]:
    """What `text` says that `sources` does not, as short labels.

    `terms` is the known-skill dictionary (vocabulary.yaml plus the user's
    own resume skills). Empty list = grounded.
    """
    src_norm = _norm(sources)
    text_norm = _norm(text)
    missing: list[str] = []

    src_numbers = _numbers(sources)
    for number in _NUMBER.findall(text or ""):
        if number not in src_numbers \
                and number.replace(",", "") not in src_numbers:
            missing.append(number)

    for term in terms:
        if _has(term, text_norm) and not _has(term, src_norm):
            # Named as the line wrote it, not as the dictionary spells it.
            shown = re.search(r"(?<![A-Za-z0-9])" + re.escape(term.strip())
                              + r"(?![A-Za-z0-9])", text or "", re.IGNORECASE)
            missing.append(shown.group(0) if shown else term)

    # PDF text breaks long links across lines, so compare without spaces.
    src_squashed = src_norm.replace(" ", "")
    for token in _ADDRESS.findall(text or ""):
        if _norm(token).rstrip(".,;:)") not in src_squashed:
            missing.append(token.rstrip(".,;:)"))

    for word in _named_words(text):
        if _has(word, src_norm):
            continue
        # "Analytics/BI", "Git-based": a joined form of words the sources
        # use separately says nothing new.
        parts = [p for p in re.split(r"[/-]", word) if p]
        if len(parts) > 1 and all(
                _has(p, src_norm) or not any(c.isupper() for c in p)
                for p in parts):
            continue
        missing.append(word)

    seen: set[str] = set()
    out = []
    for item in missing:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def term_dictionary(vocabulary: dict, resumes: list[dict]) -> list[str]:
    """Known skill and tool names: the market's and the user's own."""
    terms = list(vocabulary.get("market_tools") or [])
    terms += list(vocabulary.get("skill_names") or [])
    for resume in resumes:
        for skill in resume.get("skills") or []:
            terms.append(str(skill.get("name") or ""))
            terms += [str(a) for a in skill.get("aliases") or []]
    seen: set[str] = set()
    out = []
    for term in terms:
        key = _norm(term)
        # One-letter names ("R") match too much prose to be evidence.
        if len(key) >= 2 and key not in seen:
            seen.add(key)
            out.append(term.strip())
    return out
