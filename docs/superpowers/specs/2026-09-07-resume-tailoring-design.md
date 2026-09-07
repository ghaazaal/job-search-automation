# Resume Tailoring — Design

**Date:** 2026-09-07
**Status:** Draft, for review — open questions at the end are Ghazal's to
answer, not guessed here
**Builds on:** `2026-08-11-resume-profile-and-search-design.md` (the
`resume` table, one user / many resumes, "a tailored output can become a
new resume row" — see *Rejected alternatives* for why it does not),
`2026-08-30-application-kanban-design.md` (the `application` and `event`
tables the tailored document attaches to), `2026-08-14-background-run-design.md`
(the worker pattern reused here)

---

## Problem

Tailoring exists three times and reaches the user zero times.

```
resume_agent.generate_role_variant   one text file per TARGET ROLE TITLE, cached
                                     in output/, keyed on the title, not the
                                     job, not the user
tailoring_agent.tailor_job           cover letter + 3 highlights per JD, run by
                                     `python main.py --tailor --jd file.txt`,
                                     written to output/<company>_<date>/
tailoring_agent.shortlist_decision   3 "bullet_edits" per shortlisted job,
                                     written into the Excel tracker
```

None of it is in the store. None of it is on the map, in the drawer, or on
the tracker. The MVP spec's role-detail screen promises "application/tailoring
actions" and the drawer has none. `--tailor` takes a pasted `.txt` file when the
role's description is already in the `role` table, and it tailors against
`active[0]`, not the resume that actually won the scoring. The role-title
variant is a second copy of what the `resume` table already models — one
resume per role family — with a file cache instead of a row.

The output directory is shared by every user. Every path in it is built from a
company name and today's date.

And the part that matters most: nothing checks what the LLM wrote. A rewrite
that adds "Snowflake" because the posting wanted it, or turns "reduced load
time" into "reduced load time by 40%", ships as-is. This product is built for
someone applying into countries they cannot walk into for an interview. A
resume that says something the person cannot back up is not a tailored resume;
it is a trap.

This design replaces all three with one thing: a **tailored document**, per
role, in the store, built from the canonical resume under rules that make
fabrication a validation failure rather than a prompt request.

---

## Principles

The scoring rules carry across, sentence for sentence, because the problem is
the same one: an LLM producing something the user will trust.

| Scoring rule (CLAUDE.md) | Tailoring rule |
| --- | --- |
| The reason sentence is composed from evidence the scorer matched; the LLM may phrase it, it must not invent the facts. | The tailored resume is composed from the canonical resume's own bullets; the LLM may rephrase and reorder them, it must not invent experience, tools, numbers, dates, employers or titles. |
| Never state a skill-level match when no job description was captured. | Never tailor to a posting whose description was not captured. There is nothing to tailor to; the button does not appear. |
| Flag, never hide. | Every change is listed with what changed and why. Every gap the posting names that the resume cannot cover is stated as *not addressed*, never quietly papered over. |
| Silence is the default; every claim needs evidence. | A bullet the validator cannot trace to a source bullet reverts to the source text. A term it cannot find in the source is an invention, and the bullet reverts. |
| Never show a bare number. | The tailoring page shows the band and its sentence the card already showed. No score, no "match improved from X to Y", no ATS percentage. |

One consequence is worth stating plainly: **this tailoring makes a resume
shorter, sharper and re-ordered. It never makes it longer.** A tailored
document has at most as many bullets as the canonical one. What the user
gains is emphasis and vocabulary that matches the posting, plus a written list
of what they are missing so the cover letter can say so honestly. What they
do not gain is experience they do not have.

---

## The model

Three objects, one new.

**The canonical resume** is the `resume` row: the PDF, its extracted text,
and the confirmed profile (target roles, skills with aliases, seniority). It
gains one thing: **structure**.

**Structure** is the resume's text parsed once into sections, entries and
bullets, each with a stable id. It is stored on the `resume` row and
computed lazily — the first time any tailoring needs it — because parsing
costs an LLM call and most uploaded resumes will never be tailored.

```json
{"version": 1,
 "contact":   ["A. Example", "Yerevan, Armenia", "a.example@example.com"],
 "headline":  "Analytics Engineer",
 "summary":   "Five years building ...",
 "skills":    ["dbt", "SQL", "Power BI", "Python", "Airflow"],
 "experience": [
   {"id": "e1", "company": "Acme", "title": "Analytics Engineer",
    "dates": "2023 – present",
    "bullets": [{"id": "e1b1", "text": "Built the dbt project that ..."},
                {"id": "e1b2", "text": "Owned the Power BI ..."}]}],
 "education": [{"id": "d1", "lines": ["BSc Computer Science, ...", "2018"]}],
 "other":     [{"heading": "Certifications", "lines": ["dbt Analytics Engineering, 2024"]}]}
```

Ids are positional (`e1b2` is the second bullet of the first entry) and are
never renumbered once stored; they are what a tailored bullet cites.

The parse is validated before it is stored: **every bullet, line and field
must be found in the extracted text** after whitespace and punctuation
normalisation. pdfminer breaks lines and merges columns, so the check is
token-window overlap rather than an exact substring, but the rule is the
rule: the structure cannot contain a sentence the PDF does not. A parse that
fails this is rejected and the tailoring fails with a message naming the
problem, rather than tailoring a resume the person never wrote.

**The tailored document** is one row per generation, attached to a role and
to the resume that won that role's scoring. Its `document` has the same shape
as structure, with one addition: every experience bullet carries `source`,
the id of the canonical bullet it came from.

```json
{"version": 1,
 "contact":   [...verbatim from structure...],
 "headline":  "Analytics Engineer — dbt, Snowflake-adjacent warehouse work",
 "summary":   "...",
 "skills":    ["dbt", "SQL", "Airflow", "Python", "Power BI"],
 "experience": [
   {"id": "e1", "company": "Acme", "title": "Analytics Engineer",
    "dates": "2023 – present",
    "bullets": [{"source": "e1b1", "text": "Built and owned the dbt project ..."}]}],
 "education": [...verbatim...],
 "other":     [...verbatim...]}
```

The LLM never produces this document. It produces an **edit plan**, and code
merges the plan into the structure:

```json
{"headline": "...",
 "summary":  "...",
 "skills":   ["dbt", "SQL", "Airflow", "Python", "Power BI"],
 "experience": [{"id": "e1",
                 "bullets": [{"source": "e1b1", "text": "..."},
                             {"source": "e1b2", "text": "..."}]}]}
```

Entries the plan does not mention are copied verbatim. A bullet the plan
omits from an entry it does mention is **dropped**, and the drop is listed.
Company, title and dates come from structure, never from the plan — the LLM
cannot rename an employer or extend a tenure because those fields are not
in its output.

**The change log** is what the page shows beside the document. It is
computed by code from the two documents, not written by the LLM:

| kind | meaning | evidence shown |
| --- | --- | --- |
| `kept` | text unchanged, position unchanged | — |
| `moved` | text unchanged, position changed | resume terms the bullet shares with the posting |
| `rephrased` | text changed | before / after, and the shared terms |
| `dropped` | bullet absent from the tailored document | — |
| `reverted` | the LLM's rewrite failed validation and the source text was used | the term or number that caused it |
| `summary`, `headline`, `skills` | section-level rewrite or reorder | before / after |

"Shared terms" are the resume's skill names and aliases found, word-bounded,
in both the bullet and the posting — the same `matching` helpers the scorer
uses. That is the reason a bullet moved up, and it is a fact the code
established, so it can be shown. The LLM is not asked why it did anything.

**Unaddressed gaps** are `role.gaps` — the market tools the posting names
that the resume does not carry — restated on the tailoring page in the
drawer's existing wording: *named in the posting, not found on your resume,
so the tailored version does not claim them; worth a line in the cover letter.*
By construction every gap is unaddressed, because adding is not allowed. The
list exists so the user reads it before they send anything.

---

## The validator

This is the load-bearing module and the reason the design is structure-in,
structure-out rather than text-in, text-out. Every rule is deterministic and
unit-testable without an LLM.

| Rule | On failure |
| --- | --- |
| Every `source` id exists in the structure and is used at most once | the bullet is discarded; if an entry ends up empty, the entry reverts whole |
| Every entry id in the plan exists in the structure | unknown entries are ignored |
| **Term guard:** any `vocabulary.yaml` `market_tools` term in a rewritten bullet must appear in its source bullet, or in the resume's skills and aliases | bullet reverts to source; logged as `reverted` naming the term |
| **Number guard:** every numeral in a rewritten bullet must appear in its source bullet (`40%` cannot appear where the source had no `40`) | bullet reverts; logged naming the number |
| Summary and headline pass the term guard against the whole resume's terms and the number guard against the whole extracted text | section reverts to the structure's |
| `skills` is a subset of the structure's skills plus the profile's skill names; aliases may substitute (the posting says `PowerBI`, the resume says `Power BI`, either spelling is the user's) | unknown skills are removed, listed as `reverted` |
| Bullet count per entry never exceeds the structure's | extra bullets are discarded |
| Plan is not JSON, or has no `experience` | the tailoring fails with a retry; nothing is stored as READY |

The term guard is the scorer's `gaps` function pointed the other way: instead
of "which of the posting's tools are missing from the resume", it asks "which
of this bullet's tools are missing from the resume". Same dictionary, same
word-bounding, already tested.

What the validator does not catch, stated so nobody assumes it does: a
rephrase that inflates scope without a new tool or number ("assisted with"
becoming "led"). The prompt forbids it and the change log shows before and
after on every rephrased bullet, so the user sees it. A second LLM pass as a
judge would be a per-tailoring cost buying a soft guarantee; it is out of
scope until the change log proves insufficient in use.

---

## The LLM calls

Three prompts, each a separate function in `src/agents/`, each returning
JSON through the existing regex-extract-then-parse pattern, each given the
`build_system_prompt` description of the resume that already exists in
`tailoring_agent.py` (multi-user safe; tested).

1. **Structure parse** (`structure_parser.parse_structure`) — extracted text
   in, structure out. Once per resume, cached on the row. Prompt asks for
   verbatim bullets, explicitly: *copy each bullet exactly as written; do not
   summarise, merge or improve.* Validated as above before storing.

2. **Tailor** (`tailoring_agent.plan_tailoring`) — structure, the posting's
   title and description, and the **scorer's evidence** in. The evidence is
   `role.matched`, `role.gaps`, the seniority band and the penalties that
   fired: the same facts the card's sentence was built from, so the tailored
   document leads with what the card said matched. The prompt states the
   rules the validator enforces — rephrase and reorder only, cite a source
   for every bullet, no new tools, no new numbers — so the model is told
   the contract rather than discovering it through reverts.

3. **Cover letter** (`tailoring_agent.write_cover_letter`, Ship 2) — the
   tailored document, the posting, and the unaddressed gaps in. A separate
   call so it can be regenerated without re-tailoring, and so the tailoring
   plan stays small enough for a 70B model on Groq to return intact. The
   cover letter is prose the user will edit; it gets the term and number
   guards against the whole resume and nothing else.

`LLMClient.complete` stays a text interface. Provider JSON modes differ and
the extract-and-validate pattern already handles a model that wraps its
JSON in prose. Each prompt carries a `PROMPT_VERSION` constant; it is stored
on the row and is part of the cache key, so changing a prompt makes old
rows regenerable without making them wrong.

---

## Schema

`SCHEMA_VERSION` goes 10 → 11.

### `resume` — new columns

| Column | Type | Notes |
| --- | --- | --- |
| `structure` | TEXT | JSON, NULL until first tailoring needs it |
| `structure_version` | INTEGER | the parser's `PROMPT_VERSION`; a bump re-parses on next use |

### `tailoring` — new table

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PRIMARY KEY | |
| `user_id` | INTEGER NOT NULL REFERENCES user(id) | |
| `role_id` | INTEGER NOT NULL REFERENCES role(id) | |
| `resume_id` | INTEGER REFERENCES resume(id) ON DELETE SET NULL | the resume that won the scoring |
| `resume_label` | TEXT NOT NULL | snapshot, so the page can still say which resume after a delete |
| `status` | TEXT NOT NULL CHECK IN ('RUNNING','READY','FAILED') | |
| `stage` | TEXT | `parsing`, `tailoring`, `validating`, `writing` — what the poll shows |
| `error` | TEXT | shown when FAILED |
| `description_sha` | TEXT NOT NULL | sha256 of the posting text tailored against |
| `prompt_version` | INTEGER NOT NULL | |
| `provider`, `model` | TEXT | which LLM wrote it |
| `document` | TEXT NOT NULL DEFAULT '{}' | the tailored document, post-validation |
| `changes` | TEXT NOT NULL DEFAULT '[]' | the change log |
| `unaddressed` | TEXT NOT NULL DEFAULT '[]' | gaps restated |
| `cover_letter` | TEXT | Ship 2 |
| `edited_document` | TEXT | Ship 2: the user's edits, same shape; NULL means unedited |
| `created_at`, `finished_at` | TEXT | |

Rows are append-only. Regenerating adds a row; the newest READY row for a
role is *the* tailoring; older ones are history and are never DELETEd, in
line with the store's rule that a wrong result must stay recoverable. There
is no `is_current` flag to keep in sync — `MAX(id) … WHERE status = 'READY'`
is the query.

`delete_resume` today NULLs `role.resume_id`; with `ON DELETE SET NULL` and
`PRAGMA foreign_keys = ON` (already set in `db.py`) the tailoring row keeps
itself with `resume_label` as the attribution. Dropping a resume must not
delete a document the user already sent to an employer.

A role with a tailoring row counts as a role the user touched: the soft-drop
in `drop_roles_from_runs` extends its `application` exclusion to
`tailoring`, for the same reason.

Rendered files live at `data/tailored/<user_id>/<tailoring_id>.<ext>` —
under `data/`, which is per-user and gitignored, not `output/`, which is
neither. The path is built from two integers; nothing the user or the
posting supplied ever becomes part of it.

### `event`

One new `kind`, `TAILORED`, written with the row when it reaches READY, so
the tracker's activity feed shows *tailored with your BI Developer resume*
between *SAVED* and *APPLIED*. No new `application.status`: the old Excel
tracker's `Tailored` stage was a status because a spreadsheet had nowhere
else to put it. Here the row's existence is the fact.

---

## Screens and routes

```
POST /api/roles/<role_id>/tailorings     start one -> 202 {tailoring_id}
                                          409 one RUNNING for this user
                                          422 no description captured
                                          422 role has no winning resume
GET  /api/tailorings/<id>                {status, stage, error}
GET  /tailoring/<id>                     the page; polls the above while RUNNING
GET  /tailoring/<id>/download.md         Ship 1: Markdown
GET  /tailoring/<id>/download.docx       Ship 2: Word
POST /api/tailorings/<id>/document       Ship 2: save the user's edits
POST /api/tailorings/<id>/cover-letter   Ship 2: (re)generate the letter
```

### Where it starts

The drawer footer gains one button, `TAILOR RESUME`, beside `ADD TO TRACKER`.
It renders only when `captured` is true and the role has a `resume_id` —
the same guard the 422s enforce, expressed in the UI as absence rather than
a disabled control that needs explaining. Roles scored before Ship 2 of the
profile work have no `resume_id`; they are the ones the reduced-confidence
wording already covers, and they get the button after the next run rescores
them.

When a READY tailoring exists the button reads `TAILORED · OPEN` and links to
the page. Tracker cards carry the same link.

### The page

Reached from the drawer or a tracker card, not from the nav — it belongs to
a role, not to the app. Paper shell, same as every other page.

```
  ← Acme · Analytics Engineer                              tailored with your
                                                           analytics engineer resume
  [STRONG FIT]  your analytics engineer resume names dbt, SQL and Airflow ...

  NOT ADDRESSED
  The posting names Snowflake and Looker. Your resume does not show them,
  so this version does not claim them. Worth a line in the cover letter.

  ┌ ORIGINAL ──────────────────────┐  ┌ TAILORED ─────────────────────────┐
  │ Analytics Engineer             │  │ Analytics Engineer — dbt-first    │
  │                                │  │                                   │
  │ Acme · 2023 – present          │  │ Acme · 2023 – present             │
  │ • Owned the Power BI ...       │  │ • Built and owned the dbt project │ ↑ moved up: names dbt, SQL
  │ • Built the dbt project ...    │  │ • Owned the Power BI ...          │   rephrased
  │ • Ran the weekly ...           │  │                                   │   dropped
  └────────────────────────────────┘  └───────────────────────────────────┘

  CHANGES (7)
  moved      Built the dbt project ...           names dbt and SQL, both in the posting
  rephrased  Owned the Power BI ...  →  Owned ... shares Power BI with the posting
  reverted   Ran the weekly ...                  the rewrite named Snowflake, which
                                                 your resume does not
  dropped    Ran the weekly ...

  [ DOWNLOAD .MD ]  [ REGENERATE ]                      [ MARK APPLIED → TRACKER ]
```

Rules the page enforces, carried from the map and the drawer:

- The band renders only beside its reason, and it is the role's stored
  band and reason — the page does not re-score and does not claim the
  tailored version scores better. It might; we do not know, and saying so
  would be the fabricated-precision pattern in a new coat.
- `NOT ADDRESSED` is above the fold, before the document, because it is the
  part the user is most likely to skip and least able to afford to.
- A `reverted` change says what tripped it. The user learns what the tool
  refused to write on their behalf, which is also how they learn what it
  would never write.
- While RUNNING the page shows the stage and polls every 2 seconds, like
  `/searching/<id>`. On FAILED it shows the error and a retry, and does not
  show a half-document.

### Stale tailorings

The page compares the row's `description_sha` with the current posting text
and its `prompt_version` with the current one. A mismatch renders a one-line
notice — *this was tailored against an earlier version of the posting* — and
the REGENERATE button. The old document stays readable. Nothing is
regenerated on the user's behalf; an LLM call the user did not ask for is a
cost and a surprise.

---

## The background work

Reuses the run worker's shape exactly, because the failure modes are the
same: an LLM call that takes twenty seconds, a Flask request that must not
wait for it, and a row that must never be left RUNNING.

`POST /api/roles/<id>/tailorings` inserts the row RUNNING, starts a daemon
thread with its own connection, returns 202. The thread runs `service.tailor`:
load structure (parsing and storing it if absent), build the prompt from the
role and its evidence, call the LLM, validate, compute the change log, write
the row READY, write the `TAILORED` event. Any exception marks the row FAILED
with the message. The startup sweep that fails orphaned RUNNING runs learns
to fail orphaned RUNNING tailorings too.

One tailoring per user at a time, 409 otherwise. This is a person clicking
a button on one role, not a batch; serialising it keeps the LLM spend
legible and the code the same shape as runs. If use shows people queueing
five at once, a queue is a later ship, not a wider lock now.

The service takes the LLM client and the connection as arguments, as
`run_core.execute` does, so tests drive it synchronously with a fake LLM
and never touch a thread.

---

## Consequences elsewhere

- `resume_agent.generate_role_variant` and its `output/resume_<role>.txt`
  cache are **deleted**. A per-role-family variant is what a `resume` row
  is; the user who wants one uploads one. The pipeline's shortlist step,
  which preferred the cached variant as its resume text, reads the winning
  resume's `extracted_text` directly.
- `tailoring_agent.tailor_job` and `save_tailoring_output` are **replaced**
  by `plan_tailoring` and `write_cover_letter`. `python main.py --tailor`
  changes its argument from `--jd file.txt` to `--role <id>` and calls the
  same service the route does, synchronously, printing the change log.
  Pasting a description into a text file when the store holds it was a
  workaround for not having the store.
- `shortlist_decision` keeps `apply_now`, `reason`, `risk_flags` and
  `cover_angle`, and **drops `bullet_edits`**: three unvalidated rewrites in
  a spreadsheet cell are exactly what this design exists to stop. The
  Excel column goes with it.
- `Scorer._tailoring` — `Minor` / `Moderate` / `Significant` from a
  score-threshold lookup — is the `interview_chance` pattern in words: a
  label derived from the internal number and nothing else. It is reported
  in the Excel tracker as "Tailoring Needed". This design does not remove
  it, but names it as a residual: once tailorings exist, "needed" can mean
  the count of unaddressed gaps, which is evidence, and the lookup can go.
- `.gitignore` already covers `job_hunt/data/`. No change.
- `requirements.txt` gains nothing in Ship 1. Ship 2's `.docx` export adds
  `python-docx`.

---

## Testing

No network. `MockLLMClient` returns a canned structure and a canned plan;
the validator is the thing under test, and it needs no LLM at all.

Cases worth naming because they are the ones that protect the user:

- a plan bullet naming a tool the source does not carry reverts, and the
  change log names the tool
- a plan bullet containing `40%` where the source has no `40` reverts
- a bullet whose `source` id does not exist is discarded; an entry left
  empty reverts whole
- two bullets citing the same source keep the first only
- an entry the plan does not mention is copied verbatim, dates and all
- a plan cannot rename a company, title or date range, because the merge
  never reads those fields from it
- the tailored document never has more bullets than the structure
- a structure parse whose bullet is not in the extracted text is rejected
- `POST` with no description captured returns 422 and the drawer payload
  for that role has no button
- `POST` while one is RUNNING returns 409
- a worker that raises leaves the row FAILED, never RUNNING
- a RUNNING row from a previous process is FAILED at boot
- deleting the resume keeps the tailoring, with its label
- a soft-drop run does not drop a role that has a tailoring
- a description change makes the page show the stale notice and not
  regenerate on its own
- `match_score` and any percentage never appear in the page or any JSON
  response, checked the way the map and tracker already check it
- the change log's evidence terms are ones present in both bullet and
  posting — mutation test: removing the posting check must fail

---

## Ships

**Ship 1 — the tailoring exists.** Migration to 11. Structure parser with
its validator. `plan_tailoring`, the merge, the validator, the change log.
`tailoring` table and store module. Worker and routes. The page with
side-by-side, changes, unaddressed gaps and Markdown download. Drawer
button. `--tailor --role`. `generate_role_variant` deleted. This is the
ship that makes the invariant real: after it, nothing in the product can
write a resume claim the validator did not pass.

**Ship 2 — the user finishes it.** Cover letter (its own call, its own
regenerate). In-page editing of bullets, summary and headline, saved to
`edited_document`; the validator runs on user edits too and *warns* rather
than reverts — it is their resume, they may claim what they can back up,
but they are told when they add a tool the canonical resume never showed.
`.docx` download via `python-docx`, with a plain single-column layout.
`shortlist_decision` loses `bullet_edits`.

**Ship 3 — only if used.** A queue instead of the one-at-a-time lock.
A second pass that flags scope inflation in rephrased bullets. Replacing
`Scorer._tailoring` with unaddressed-gap counts. Each earns its place by a
person hitting the limit, not by anticipation.

---

## Rejected alternatives

**Promote a tailored document to a `resume` row.** The profile spec
anticipated it. It is wrong for this product: every active resume's target
roles join the search union and every active resume is scored against every
job, so promoting each application's document would grow the search and the
scoring with each application and make the map's "which resume matched"
attribution meaningless. A tailored document is an application artifact.
If a user wants one as a new base, they upload its PDF and it goes through
the same confirm screen as any other resume.

**Text in, text out.** Hand the LLM the extracted text and the posting, get
a resume back. It is what the three existing pieces do, and it is why none
of them can be checked: there is no unit to check. Structure costs one parse
per resume and buys a validator that can revert a single bullet and say why.

**Per-target-role variants, kept.** They are a cache of an LLM rewrite keyed
on a title string. Two users with the same target role share a file. The
`resume` table is the per-role-family model, and it is per-user.

**An ATS "match percentage" for the tailored version.** Re-scoring the
tailored document against the posting and showing the delta. The scorer's
number is internal for the same reason here: it would show a bigger number
for a document that had been made to contain the words, which is precisely
the incentive that produces dishonest resumes. The band and sentence shown
are the role's, unchanged.

**Letting the LLM write the change reasons.** Free text about why it moved
a bullet is the one place in this feature where plausible fiction would go
unnoticed. Shared terms with the posting are computed, true, and enough.

---

## Out of scope

- Reproducing the original PDF's layout. pdfminer text has no layout to
  recover. Ship 1 renders Markdown; Ship 2 renders a plain `.docx` the user
  finishes in Word. A user who needs their exact template pastes into it.
- Any language other than the resume's own. The prompt is told to keep the
  resume's language; nothing translates.
- Tailoring against a posting without a description. The FETCH POSTING
  button in the drawer is the path to a description; this design depends
  on it and does not build it.
- Auto-apply, form fill, sending anything anywhere. Unchanged from the MVP
  spec's exclusions.
- Batch tailoring of a shortlist. One role, one click.
- Embeddings, semantic matching, keyword-density optimisation.

---

## Open questions — for Ghazal

1. **Dropping bullets.** The plan may omit a bullet and the drop is listed.
   Is that wanted, or should the tailored document keep every bullet and
   only reorder and rephrase? Dropping makes a one-page resume possible;
   not dropping makes the document strictly a rewording. The validator
   handles both; the prompt differs.
2. **Word or PDF.** Ship 2 proposes `.docx` because it is editable and the
   ATS-safe common denominator. If applications in your target markets are
   PDF-first and you finish documents elsewhere anyway, a PDF export via
   `reportlab` is the same effort and the `.docx` can wait.
3. **Edit in the app or in Word.** Ship 2's in-page editor is the larger
   piece of UI in this design. If the workflow is "download, finish in
   Word, upload nothing back", the editor is not needed and Ship 2 shrinks
   to the cover letter and the export.
4. **Cover letter tone.** First person, three paragraphs, names the
   unaddressed gaps honestly where the user has adjacent experience — or
   leaves gaps unmentioned unless the user edits them in? The current
   `tailor_job` prompt says nothing about gaps.
