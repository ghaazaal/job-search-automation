# Job Search Automation — Claude Code Instructions

## Project
Career opportunity mapping product for job-seeking data professionals
(Analytics Engineer, Data Engineer, Data Analyst, Product Analyst).
Ghazal is both the author and a user — build for multiple users, not just her.

Scrapes Indeed + LinkedIn via Apify, scores listings against the job
description, and presents company-centred opportunity maps rather than a
flat job list. AI layer: resume parsing, tailoring, cover letters.

Dev environment: Windows 11, Python + PowerShell.

Design spec: `docs/superpowers/specs/2026-08-09-career-opportunity-map-mvp-design.md`

### Build order
Phase 1 is three independent features. Ship them in sequence, not together:
1. The map — company entity, ACT_NOW/WATCH/DISCOVER, ranking, evidence.
   Runs on existing scrape data. Single user is fine here.
2. Multi-user shell — resume upload, role confirmation, location + work
   mode, per-user storage. SHIPPED (Ship 1 + Ship 2).
3. People-in-context hints — only if phase 1 gets real use.

## Scoring
Never show a bare number to the user. Every recommendation is explained in
one sentence built from evidence the scorer actually matched — named skills,
seniority band, penalties that fired, location/work-mode fit.

- The numeric score is internal, used for ranking only.
- The reason sentence is composed from the scorer's breakdown. The LLM may
  phrase it; it must not invent the facts.
- Never state a skill-level match when no job description was captured —
  use reduced-confidence wording instead.
- Do not present fabricated precision. `interview_chance` was a hardcoded
  lookup table rendered as a percentage; do not reintroduce that pattern.

Scoring input comes from the user's active resumes in the store, not from a
keyword file. `vocabulary.yaml` holds only language and market facts —
seniority wording, known tools, employment constraints, point values. Nothing
in it may describe a particular person.

## Design System
Always read `DESIGN.md` before making any visual or UI decisions.
All font choices, colors, spacing, and aesthetic direction are defined there.
Do not deviate without explicit user approval.
In QA mode, flag any code that doesn't match DESIGN.md.

Key tokens from DESIGN.md:
- Background: `#0A0E1A`, Surface: `#0D1117`, Border: `#1E2A3A`
- Cyan: `#00D4FF` (primary interactive), Green: `#00D9A3` (approve), Amber: `#F59E0B` (partial), Red: `#E05C5C` (skip)
- Fonts: JetBrains Mono (data/labels/scores) + Inter (body/descriptions)
- Dark mode only — no light mode toggle

## Finalized UI
The job-list dashboard (`job_hunt/src/dashboard.py`, the `JOBS`-array HTML
file) is retired — superseded by the company-centred opportunity map.

The live product is a local Flask app (`job_hunt/src/app.py`):
`GET /` renders the opportunity map (`job_hunt/src/map_page.py`), `GET
/activity` renders the in-flight application board
(`job_hunt/src/activity_page.py`), both reading from the SQLite store
(`job_hunt/src/store/`). Run it with `python main.py --serve`.
