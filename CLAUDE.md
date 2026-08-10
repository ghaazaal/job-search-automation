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
   mode, per-user storage.
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
The job review dashboard HTML is at:
`~/.gstack/projects/JobSearchautomation/designs/job-review-dashboard-20260528/finalized.html`
Wire it to the Python backend by replacing the `JOBS` array with API output.
