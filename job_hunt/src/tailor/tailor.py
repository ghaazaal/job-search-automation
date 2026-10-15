"""Building the master resume and tailoring it to a posting.

Both steps are one Claude call each, and both are followed by a check that
does not trust the call: a master line its source resumes do not support
is left out (and listed), and a tailored line its cited master lines do
not support is put back to the master's own words (and listed).

`model` is any callable shaped like `skills.claude.ClaudeJson`: keyword
system / prompt / schema / effort / max_tokens, returning the parsed JSON.
Tests pass a fake.
"""
import copy

from . import document, grounding

# $ per million tokens: (input, output). Cache writes bill at 1.25x input,
# cache reads at 0.1x. Used only to show the user what a call cost.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-1": (10.0, 50.0),
}

MAX_DESCRIPTION = 15000

# ── building the master ───────────────────────────────────────────────────

MASTER_SYSTEM = """You assemble one master resume from several resume documents written by the same person. The master is the complete record that is later tailored to individual job postings, so it must keep every distinct fact from every source: every job, every bullet, every figure, every skill, every education entry, certification, project and language.

Merge duplicates. When two sources describe the same job or the same achievement, keep one entry and one bullet, using the more specific wording and keeping every distinct detail from both.

Hard rule: use only what the sources say. Do not add, infer, generalise or embellish. No skill, tool, number, title, employer, date, degree or responsibility that is not written in a source. Copy wording as closely as you can; you may only repair characters broken by PDF extraction (for example a stray replacement character used as a bullet, dash or apostrophe) and join lines that a page break split.

Shape:
- name: the person's name.
- header_lines: the headline and contact lines under the name, one per line: each distinct headline the sources use, then location, email, phone and links, each as written. Tailoring later picks the ones that fit a posting.
- sections: in this order when the sources have them: Summary, Skills, Experience, Projects, Education, Certifications, Languages, then anything else.
- A summary is a paragraph; when sources have differently worded summaries, keep each as its own paragraph. Skills are one group with an empty heading and one bullet per skill group, such as "Languages & Databases: SQL, Python".
- Each job is a group: heading "Job title | Company", meta lines for the dates and the place, then its bullets. Most recent job first.
- Education and certification entries are groups with a heading and meta lines, and bullets only when the source has details."""

MASTER_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "header_lines": {"type": "array", "items": {"type": "string"}},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "paragraphs": {"type": "array",
                                   "items": {"type": "string"}},
                    "groups": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "heading": {"type": "string"},
                                "meta": {"type": "array",
                                         "items": {"type": "string"}},
                                "bullets": {"type": "array",
                                            "items": {"type": "string"}},
                            },
                            "required": ["heading", "meta", "bullets"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["title", "paragraphs", "groups"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["name", "header_lines", "sections"],
    "additionalProperties": False,
}


def build_master(sources: list[dict], model, terms: list[str]) -> dict:
    """Merge source resumes into one master.

    `sources` is [{label, text}]. Returns {markdown, report, usage}: the
    report lists every line left out because no source supports it, and
    every heading kept with a figure or name the sources do not show.
    """
    usable = [s for s in sources if (s.get("text") or "").strip()]
    if not usable:
        raise ValueError("There is no resume text to build from.")
    prompt = "\n\n".join(
        f"=== SOURCE {i}: {s['label']} ===\n{s['text'].strip()}"
        for i, s in enumerate(usable, 1))
    prompt += "\n\nAssemble the master resume from these sources."
    answer = model(system=MASTER_SYSTEM, prompt=prompt, schema=MASTER_SCHEMA,
                   effort="medium", max_tokens=16000)
    usage = usage_of(model)

    doc = document.from_structure(answer or {})
    all_text = "\n".join(s["text"] for s in usable)
    left_out: list[dict] = []
    warnings: list[dict] = []

    kept_header = []
    for line in doc["header"]:
        missing = grounding.unsupported(line, all_text, terms)
        if missing:
            left_out.append({"text": line, "missing": missing})
        else:
            kept_header.append(line)
    doc["header"] = kept_header

    for section in doc["sections"]:
        blocks = []
        for block in section["blocks"]:
            if block["kind"] == "para":
                missing = grounding.unsupported(block["text"], all_text, terms)
                if missing:
                    left_out.append({"text": block["text"],
                                     "missing": missing})
                else:
                    blocks.append(block)
                continue
            # A heading stays even when unsure: dropping a job would lose
            # everything under it. The user is told to look at it.
            for line in [block.get("heading") or ""] + list(
                    block.get("meta") or []):
                missing = grounding.unsupported(line, all_text, terms)
                if missing:
                    warnings.append({"text": line, "missing": missing})
            bullets = []
            for bullet in block["bullets"]:
                missing = grounding.unsupported(bullet["text"], all_text,
                                                terms)
                if missing:
                    left_out.append({"text": bullet["text"],
                                     "missing": missing})
                else:
                    bullets.append(bullet)
            block["bullets"] = bullets
            if bullets or block.get("heading"):
                blocks.append(block)
        section["blocks"] = blocks
    doc["sections"] = [s for s in doc["sections"] if s["blocks"]]

    markdown = document.render(doc)
    return {"markdown": markdown,
            "report": {"left_out": left_out, "warnings": warnings},
            "usage": usage}


# ── tailoring ─────────────────────────────────────────────────────────────

TAILOR_SYSTEM = """You tailor a candidate's master resume to one job posting. The master is given with an id in brackets before every header line [h], section [s], paragraph [p], entry [g] and bullet [b].

You may:
- choose the header lines to show: one headline that fits this posting, and one of each contact detail (one email, the location, the links). You choose them by id in header; you cannot change their words;
- choose which bullets of each entry to keep, and put the ones that matter most for this posting first;
- drop bullets that matter less for this posting;
- reword a bullet so it leads with what this posting cares about, or merge two bullets of the same entry into one;
- use the posting's word for something the master already says, but only when it is genuinely the same thing;
- rewrite the summary to speak to this posting, from anything the master says. List in paragraphs every paragraph you keep, rewritten or not; a paragraph you leave out is dropped. When the master has several summaries, keep one;
- reorder skill lines, and the items inside a skill line, to put this posting's needs first;
- reorder sections.

Hard rules. A line that breaks one is thrown out and replaced with the master's own words:
1. Never add a skill, tool, technology, employer, title, number, metric, date, certification, degree, team size, or responsibility that the master does not state. If the posting asks for something the master does not show, put it in not_in_master and leave it out of the resume entirely. Do not soften it into "familiar with", "exposure to" or "eager to learn".
2. Every bullet lists in sources the master bullet ids it was written from. A bullet may only cite bullets of the entry it sits in. A paragraph may draw on anything in the master; list the ids it draws from.
3. Copy every figure exactly as the master writes it.
4. Job titles, company names, dates, places and education are copied from the master by the program. You do not write them, so do not put them in bullets either unless the cited bullet already says them.

Keep the resume no longer than the master. In emphasis, give two to five short lines on what you brought forward and which part of the posting it answers. In not_in_master, list the posting's requirements the master does not support, in the posting's words, most important first."""

TAILOR_SCHEMA = {
    "type": "object",
    "properties": {
        "paragraphs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "sources": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "text", "sources"],
                "additionalProperties": False,
            },
        },
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "bullets": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "sources": {"type": "array",
                                            "items": {"type": "string"}},
                            },
                            "required": ["text", "sources"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["id", "bullets"],
                "additionalProperties": False,
            },
        },
        "header": {"type": "array", "items": {"type": "string"}},
        "section_order": {"type": "array", "items": {"type": "string"}},
        "emphasis": {"type": "array", "items": {"type": "string"}},
        "not_in_master": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["header", "paragraphs", "groups", "section_order",
                 "emphasis", "not_in_master"],
    "additionalProperties": False,
}


def tailor_prompt(master_doc: dict, role: dict) -> str:
    description = (role.get("description") or "").strip()[:MAX_DESCRIPTION]
    return (f"MASTER RESUME\n{document.annotated(master_doc)}\n\n"
            f"JOB POSTING\nTitle: {role.get('title') or ''}\n"
            f"Company: {role.get('company') or ''}\n\n{description}\n\n"
            "Tailor the master resume to this posting.")


def tailor(master_markdown: str, role: dict, model, terms: list[str]) -> dict:
    """One tailored resume. Returns {markdown, report, usage}."""
    master = document.parse(master_markdown)
    if not any(block["kind"] == "group" and block["bullets"]
               for section in master["sections"]
               for block in section["blocks"]):
        raise ValueError("The master resume has no bullets to tailor.")
    answer = model(system=TAILOR_SYSTEM, prompt=tailor_prompt(master, role),
                   schema=TAILOR_SCHEMA, effort="medium", max_tokens=16000)
    usage = usage_of(model)
    tailored, report = apply(master, answer or {}, terms)
    return {"markdown": document.render(tailored), "report": report,
            "usage": usage}


def apply(master: dict, answer: dict, terms: list[str]) -> tuple[dict, dict]:
    """Put the model's choices onto a copy of the master, checking each.

    Headings, meta lines, the name and the header are never taken from the
    model. A rewritten line whose cited sources do not support it reverts
    to the master's words; a bullet citing nothing in its own entry is
    dropped. Every revert and drop is in the report.
    """
    idx = document.index(master)
    doc = copy.deepcopy(master)
    blocks = {block["id"]: block for section in doc["sections"]
              for block in section["blocks"]}
    report = {"rewritten": 0, "kept_as_is": 0, "reverted": [], "dropped": [],
              "emphasis": _strings(answer.get("emphasis"))[:6],
              "not_in_master": _strings(answer.get("not_in_master"))[:15]}

    # Header lines are chosen, never written: only master lines, in the
    # master's order. Choosing none keeps them all.
    header = master.get("header") or []
    chosen = sorted({int(h[1:]) for h in _strings(answer.get("header"))
                     if h[:1] == "h" and h[1:].isdigit()
                     and 1 <= int(h[1:]) <= len(header)})
    if chosen:
        doc["header"] = [header[i - 1] for i in chosen]

    whole = document.full_text(master)
    kept_paras: set[str] = set()
    for item in answer.get("paragraphs") or []:
        block = blocks.get(str(item.get("id") or ""))
        if block is None or block["kind"] != "para":
            continue
        kept_paras.add(block["id"])
        text = " ".join(str(item.get("text") or "").split())
        if not text:
            continue
        # A summary sums up the whole master, so the whole master is its
        # source (titles included); bullets are held to their own entry.
        missing = grounding.unsupported(text, whole, terms)
        if missing:
            report["reverted"].append({"text": text, "missing": missing,
                                       "kept": block["text"]})
            continue
        _count(report, text, block["text"])
        block["text"] = text

    for item in answer.get("groups") or []:
        block = blocks.get(str(item.get("id") or ""))
        if block is None or block["kind"] != "group":
            continue
        own = {block["id"]} | {b["id"] for b in block["bullets"]}
        original = {b["id"]: b["text"] for b in block["bullets"]}
        out: list[dict] = []
        used: set[str] = set()
        for bullet in item.get("bullets") or []:
            text = " ".join(str(bullet.get("text") or "").split())
            cited = [s for s in _strings(bullet.get("sources")) if s in own]
            if not text:
                continue
            if not cited:
                report["dropped"].append(
                    {"text": text,
                     "why": "it cites nothing from this entry"})
                continue
            sources = " ".join(idx[s]["text"] for s in cited)
            missing = grounding.unsupported(text, sources, terms)
            if missing:
                fallback = next((s for s in cited
                                 if s in original and s not in used), None)
                report["reverted"].append(
                    {"text": text, "missing": missing,
                     "kept": original.get(fallback, "")})
                if fallback is None:
                    continue
                text = original[fallback]
            else:
                _count(report, text, sources)
            if any(b["text"] == text for b in out):
                continue
            used.update(cited)
            out.append({"id": cited[0], "text": text})
        if out:
            block["bullets"] = out

    # A section keeps only the paragraphs listed, unless none of its
    # paragraphs was listed: then nothing was decided and all stay.
    for section in doc["sections"]:
        paras = [b["id"] for b in section["blocks"] if b["kind"] == "para"]
        if any(p in kept_paras for p in paras):
            section["blocks"] = [b for b in section["blocks"]
                                 if b["kind"] != "para"
                                 or b["id"] in kept_paras]

    order = [s for s in _strings(answer.get("section_order"))]
    by_id = {s["id"]: s for s in doc["sections"]}
    seen: list[str] = []
    for sid in order:
        if sid in by_id and sid not in seen:
            seen.append(sid)
    seen += [s["id"] for s in doc["sections"] if s["id"] not in seen]
    doc["sections"] = [by_id[s] for s in seen]
    return doc, report


def _count(report: dict, text: str, source: str) -> None:
    if " ".join(text.split()) == " ".join(source.split()):
        report["kept_as_is"] += 1
    else:
        report["rewritten"] += 1


def _strings(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [" ".join(str(v).split()) for v in value if str(v).strip()]


# ── cost ──────────────────────────────────────────────────────────────────

def usage_of(model) -> dict:
    """Token counts from the model's last call, priced. {} for a fake."""
    usage = getattr(model, "last_usage", None)
    if usage is None:
        return {}
    name = getattr(model, "last_model", None) or getattr(model, "model", "")
    counts = {
        "input": int(getattr(usage, "input_tokens", 0) or 0),
        "output": int(getattr(usage, "output_tokens", 0) or 0),
        "cache_write": int(getattr(usage, "cache_creation_input_tokens", 0)
                           or 0),
        "cache_read": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
    }
    return {"model": name, **counts, "usd": cost(name, counts)}


def cost(model_name: str, counts: dict) -> float | None:
    price = next((p for key, p in PRICES.items()
                  if (model_name or "").startswith(key)), None)
    if price is None:
        return None
    per_in, per_out = price[0] / 1e6, price[1] / 1e6
    return round(counts.get("input", 0) * per_in
                 + counts.get("cache_write", 0) * per_in * 1.25
                 + counts.get("cache_read", 0) * per_in * 0.1
                 + counts.get("output", 0) * per_out, 4)
