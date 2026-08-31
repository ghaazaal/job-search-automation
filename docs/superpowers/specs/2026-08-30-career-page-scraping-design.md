# Company-suggested career-page scraping — design

Date: 2026-08-30
Status: proposed
Builds on: `2026-08-09-career-opportunity-map-mvp-design.md` (Company
intelligence, data rule #1)

## Why

Today a company only enters the system as a byproduct of a board-scraped
job posting (MVP spec, data rule #1: "Jobs come from the existing Indeed
and LinkedIn Apify integrations"). A company that hires remotely from
Armenia but posts only to its own site — never to a board this product
scrapes — is invisible, no matter how good the fit. This is the same gap
that motivated dropping Indeed in Ship 8: the boards available are
necessarily incomplete for a persona for whom remote is the only category
that exists.

This spec adds a second, company-first ingestion path: given a company's
careers-page URL, scrape it directly for open roles. It complements the
existing board-first path; it does not replace it.

## Scope (v1)

- **Company source for this spec: user-supplied.** Ghazal (or, in the
  multi-user shell, any user) supplies a company name and careers-page
  URL by hand.
- LLM-driven company discovery ("search the web for companies known to
  hire remotely from Armenia") is explicitly **out of scope here** — it's
  the second stage Ghazal described, and deserves its own spec once this
  ships and gets used. Keeping it separate keeps this ship shippable.
- For each supplied company: fetch the careers page, extract open roles
  (title, location, description, posting date if available, apply URL).
- Extracted roles flow through the **existing, unchanged** scorer and
  eligibility engine. This spec is a new ingestion source, not a new
  scoring path.
- Company state transitions (`ACT_NOW` / `WATCH` / `DISCOVER`) use the
  existing rules (MVP spec, data rules #4–6) unmodified — a
  user-suggested company becomes `ACT_NOW` the same way a board-sourced
  one does.

## What this explicitly is not

- Not automatic company discovery — separate, later spec.
- Not the kanban application-tracker UI Ghazal also asked for — separate
  concern, separate spec (see note below).
- Not a general-purpose scraper for arbitrary company sites. Careers
  pages vary wildly: static HTML, JS-rendered SPAs, or hosted on an ATS
  (Greenhouse, Lever, Ashby, Workable). v1 should likely target
  ATS-hosted pages first, since their markup is structured and
  predictable, and treat bespoke company sites as a fallback case —
  possibly manual entry rather than scraped, at least initially.

## Decided (2026-08-30)

- **Target companies already exist.** Ghazal has already tried working
  with some of them by hand and "couldn't reach and get their data" —
  the failure mode isn't documented in this repo (no matching commits,
  scripts, or notes found), so it needs to be pinned down before this
  ship starts: was the careers page blocked (Akamai/anti-bot, the same
  pattern `catalog-pipeline` hit on Zara/H&M and solved with an Apify
  actor)? JS-rendered with nothing in the initial HTML? Or something
  else? **This determines the fetch strategy** (plain HTTP vs.
  browser-rendered vs. an Apify actor) and should be answered per
  company before writing a general solution.
- **Refresh cadence: every two weeks**, not the board scrapers' cadence.
  Career pages move slower than aggregator listings; no reason to hit
  them as often.

## Open questions — for Ghazal, not guessed here

- Which ATS platforms actually matter — do the companies on Ghazal's
  radar mostly use Greenhouse/Lever/Ashby, or bespoke career pages? (An
  ATS — Applicant Tracking System — is the software a company's careers
  page runs on, e.g. Greenhouse or Lever, rather than a page they built
  themselves. Companies on the same ATS share the same page structure,
  so one parser covers all of them; a bespoke company site needs its
  own parser, one at a time. Worth checking before writing the fetcher,
  since it decides whether v1 is a handful of reusable parsers or many
  one-off ones.)
- A user-suggested company that currently has zero open roles: sits in
  `DISCOVER` indefinitely like today, or does it need a distinct
  "watching, nothing found yet" sub-state so it doesn't read as an error?

## Data model changes

| Object | Change |
|---|---|
| Company | new `source` field: `board` \| `user_suggested` — distinguishes how the company entered the system. Existing board-sourced companies keep `board`; nothing is retroactively relabeled. |
| Company | `careers URL` becomes **required** (not optional) for `user_suggested` companies — it's their only entry point. |
| Job | new `source` field: `apify_board` \| `careers_page_scrape`, mirroring the per-source provenance tracking Ship 8 already added for board reach. |

## Note — the application tracker

Ghazal also wants the application tracker (currently
`job_tracker_ghazal.xlsx` / `job_tracker_updater.py`) moved into the app
as a kanban board over `job_hunt.db`, retiring the spreadsheet. That is
separate work from career-page scraping and should get its own spec —
flagged here so it isn't lost, not designed here.

## Flagged, not fixed here

`job_tracker_updater.py` has an "Interview Chance" column. The MVP
spec's data rule #9 bans exactly this pattern — a hardcoded
interview-chance percentage — as "fabricated precision" and says it
"must not be reintroduced." Worth checking whether this column is live
or a pre-rule leftover before the tracker migration builds on top of it.
