"""The master resume's shape: Markdown with a fixed, small grammar.

    # Name
    header lines (headline, contact) until the first section
    ## Section
    paragraph lines
    - loose bullets
    ### Entry heading (title, company)
    entry meta lines (dates, place)
    - entry bullets

Markdown because the user edits the master in a plain text box and gets
back what they typed. The parse gives every paragraph, entry and bullet a
positional id (p1, g1, b1 ...), which is what the tailoring prompt cites
and what the grounding check holds each tailored line to. Ids are only
meaningful against the exact text they were parsed from, so a tailored
resume stores the master it was built from.
"""
import re

_BULLET = re.compile(r"^\s*(?:[-*•●▪·])\s+(.*)$")


def _clean(line: str) -> str:
    return " ".join(line.split())


def parse(markdown: str) -> dict:
    """Markdown -> {name, header, sections:[{id, title, blocks}]}.

    A block is a paragraph {kind: para, id, text} or a group {kind: group,
    id, heading, meta, bullets:[{id, text}]}. Loose bullets in a section
    form a group with no heading. Never raises: text that fits no rule
    becomes a paragraph, so nothing the user typed is lost.
    """
    doc = {"name": "", "header": [], "sections": []}
    counters = {"s": 0, "p": 0, "g": 0, "b": 0}

    def next_id(kind: str) -> str:
        counters[kind] += 1
        return f"{kind}{counters[kind]}"

    section = None
    group = None        # the group bullets currently attach to
    para = None         # the paragraph lines currently attach to
    last_bullet = None

    def open_section(title: str) -> dict:
        new = {"id": next_id("s"), "title": title, "blocks": []}
        doc["sections"].append(new)
        return new

    for raw in (markdown or "").replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            para = None
            last_bullet = None
            continue
        if stripped.startswith("### ") and section is not None:
            group = {"kind": "group", "id": next_id("g"),
                     "heading": _clean(stripped[4:]), "meta": [],
                     "bullets": []}
            section["blocks"].append(group)
            para = last_bullet = None
            continue
        if stripped.startswith("## "):
            section = open_section(_clean(stripped[3:]))
            group = para = last_bullet = None
            continue
        if stripped.startswith("# ") and not doc["name"] and section is None:
            doc["name"] = _clean(stripped[2:])
            continue
        if section is None:
            doc["header"].append(_clean(stripped))
            continue

        bullet = _BULLET.match(line)
        if bullet:
            if group is None or (group["heading"] is None and para is not None):
                group = {"kind": "group", "id": next_id("g"),
                         "heading": None, "meta": [], "bullets": []}
                section["blocks"].append(group)
            last_bullet = {"id": next_id("b"), "text": _clean(bullet.group(1))}
            group["bullets"].append(last_bullet)
            para = None
            continue
        if last_bullet is not None and raw[:1] in (" ", "\t"):
            # An indented line continues the bullet above it.
            last_bullet["text"] = _clean(last_bullet["text"] + " " + stripped)
            continue
        if group is not None and group["heading"] is not None \
                and not group["bullets"]:
            group["meta"].append(_clean(stripped))
            continue
        if para is None:
            para = {"kind": "para", "id": next_id("p"), "text": ""}
            section["blocks"].append(para)
            group = None
        para["text"] = _clean(para["text"] + " " + stripped)
        last_bullet = None
    return doc


def render(doc: dict) -> str:
    """The inverse of parse: parse(render(d)) has the same text and ids."""
    out: list[str] = []
    if doc.get("name"):
        out.append(f"# {doc['name']}")
    out.extend(doc.get("header") or [])
    for section in doc.get("sections") or []:
        out.append("")
        out.append(f"## {section['title']}")
        for block in section["blocks"]:
            if block["kind"] == "para":
                out.append("")
                out.append(block["text"])
                continue
            out.append("")
            if block.get("heading"):
                out.append(f"### {block['heading']}")
                out.extend(block.get("meta") or [])
            out.extend(f"- {b['text']}" for b in block["bullets"])
    return "\n".join(out).strip() + "\n"


def index(doc: dict) -> dict:
    """id -> {kind, text, group, section} for every citable piece."""
    found: dict = {}
    for section in doc.get("sections") or []:
        for block in section["blocks"]:
            if block["kind"] == "para":
                found[block["id"]] = {"kind": "para", "text": block["text"],
                                      "group": None, "section": section["id"]}
                continue
            found[block["id"]] = {
                "kind": "group", "section": section["id"], "group": block["id"],
                "text": " ".join([block.get("heading") or ""]
                                 + list(block.get("meta") or []))}
            for bullet in block["bullets"]:
                found[bullet["id"]] = {"kind": "bullet", "text": bullet["text"],
                                       "group": block["id"],
                                       "section": section["id"]}
    return found


def annotated(doc: dict) -> str:
    """The master as the model sees it: every piece prefixed by its id."""
    out = [f"# {doc.get('name') or ''}"]
    out.extend(f"  [h{i}] {line}"
               for i, line in enumerate(doc.get("header") or [], 1))
    for section in doc.get("sections") or []:
        out.append(f"[{section['id']}] ## {section['title']}")
        for block in section["blocks"]:
            if block["kind"] == "para":
                out.append(f"  [{block['id']}] {block['text']}")
                continue
            heading = block.get("heading")
            out.append(f"  [{block['id']}] "
                       + (f"### {heading}" if heading else "(bullet list)"))
            out.extend(f"       {m}" for m in block.get("meta") or [])
            out.extend(f"    [{b['id']}] {b['text']}" for b in block["bullets"])
    return "\n".join(out)


def full_text(doc: dict) -> str:
    """Everything the document says, as one string, for whole-text checks."""
    parts = [doc.get("name") or ""] + list(doc.get("header") or [])
    for section in doc.get("sections") or []:
        parts.append(section["title"])
        for block in section["blocks"]:
            if block["kind"] == "para":
                parts.append(block["text"])
            else:
                parts.append(block.get("heading") or "")
                parts.extend(block.get("meta") or [])
                parts.extend(b["text"] for b in block["bullets"])
    return "\n".join(p for p in parts if p)


def from_structure(data: dict) -> dict:
    """The model's structured master -> a parsed document.

    Built by rendering and re-parsing, so ids come from the same counter a
    later parse of the saved Markdown would use.
    """
    lines = [f"# {_clean(str(data.get('name') or ''))}"]
    lines += [_clean(str(h)) for h in data.get("header_lines") or []
              if _clean(str(h))]
    for section in data.get("sections") or []:
        title = _clean(str(section.get("title") or ""))
        if not title:
            continue
        lines += ["", f"## {title}"]
        for paragraph in section.get("paragraphs") or []:
            text = _clean(str(paragraph))
            if text:
                lines += ["", text]
        for group in section.get("groups") or []:
            heading = _clean(str(group.get("heading") or ""))
            # "### Skills" under "## Skills" says nothing twice.
            if heading.lower() == title.lower():
                heading = ""
            bullets = [_clean(str(b)) for b in group.get("bullets") or []
                       if _clean(str(b))]
            lines.append("")
            if heading:
                lines.append(f"### {heading}")
                lines += [_clean(str(m)) for m in group.get("meta") or []
                          if _clean(str(m))]
            lines += [f"- {b}" for b in bullets]
    return parse("\n".join(lines))
