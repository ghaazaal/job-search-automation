# Job Search Automation — Claude Code Instructions

## Project
Personal job search automation tool for Ghazal (Analytics/Data Engineer).
Scrapes Indeed + LinkedIn via Apify, scores listings, outputs styled Excel tracker.
AI layer: resume tailoring, cover letter generation, company intelligence.
Single user, Windows 11, Python + PowerShell environment.

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
