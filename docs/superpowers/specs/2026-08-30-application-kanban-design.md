# Application status — kanban view

Date: 2026-08-30
Status: proposed
Builds on: `job_hunt/src/store/schema.py` (`application`, `event` tables),
`job_hunt/src/store/tracking.py` (`set_role_status`)

## Why

Ghazal asked for "something like Trello" to show application stages. The
backend for exactly this **already exists and is not the gap**:

- `application.status` already has seven states — `SAVED`, `APPLIED`,
  `INTERVIEWING`, `OFFER`, `REJECTED`, `CLOSED`, `HIDDEN`.
- `set_role_status()` already validates and writes every transition in
  one DB transaction with a matching `event` row (`from_status` →
  `to_status`, timestamped) — a full audit trail already, not something
  this spec needs to add.
- `map_page.py` already has SAVE/HIDE buttons posting to
  `/api/roles/{id}/status`, and `activity_page.py` already renders the
  event history as a feed.

**What's actually missing is the board itself** — a view with one column
per status, cards for each role, and a way to move a card between
columns that calls the endpoint that already exists.

This also surfaces a real inconsistency worth resolving as part of this
work, not after: the standalone spreadsheet tool
(`job_tracker_updater.py`) has its **own, different** seven-stage
vocabulary — `New`, `Ready to Apply`, `Tailored`, `Applied`, `Interview`,
`Rejected`, `Ignored` — tracked in an Excel file, disconnected from
`application.status` entirely. Two definitions of "where is this
application" exist in the project right now. Ghazal has said she wants
the tracker retired in favor of the in-app version — this spec is what
that retirement actually depends on.

## Scope (v1)

- A new page (or a new mode on the existing opportunity map) showing one
  column per `application.status` value, in a sensible left-to-right
  order: `SAVED → APPLIED → INTERVIEWING → OFFER`, with `REJECTED` /
  `CLOSED` / `HIDDEN` as a collapsed or end-of-board group rather than
  live columns a role is expected to sit in day-to-day.
- Each card: role title, company, and whatever's already computed
  (`band`, `reason`) — no new scoring or data needed, this reads fields
  the `role` table already has.
- Moving a card calls the existing `/api/roles/{id}/status` endpoint.
  No new backend route unless the current one turns out not to fit a
  drag interaction (e.g. it may need to accept the same payload shape
  from a drag-drop library instead of a button click — check before
  assuming a new endpoint is needed).
- `NEW` (a role with no `application` row yet — see `role_status()`'s
  fallback) needs a home too: either its own leftmost column, or folded
  into `SAVED` as "not yet actioned." Pick one — see open question.

## What this explicitly is not

- Not a rebuild of the status backend — it's done.
- Not the career-page scraping work from the companion spec
  (`2026-08-30-career-page-scraping-design.md`) — unrelated, sequenced
  independently.
- Not (yet) the retirement of `job_tracker_updater.py` itself — that's a
  follow-on cleanup once the kanban view is live and actually used, not
  a precondition for shipping it.

## Open questions — for Ghazal, not guessed here

- Does `NEW` (no `application` row yet) get its own column, or fold
  into `SAVED`? Affects how the board reads for roles fresh off a run.
- Drag-and-drop, or click-a-role-to-see-status-options? Drag reads more
  "Trello"; a click menu is far less UI work and just as functional.
- Do `REJECTED` / `CLOSED` / `HIDDEN` need to be visible columns at all,
  or does a "show closed" toggle keep the live board focused on what's
  actually in motion?

## Note — `job_tracker_updater.py`

Its "Interview Chance" column computes a hardcoded percentage
(`job_tracker_updater.py:163`, `interview_chance = f"{max(5, min(base,
60))}%"`) — precisely the pattern the MVP spec's data rule #9 bans. The
live app already agrees this should not exist: `job_hunt/main.py` hardcodes
the same column to an empty string, and two tests
(`test_interview_chance_is_gone`, `test_interview_chance_is_still_gone`)
assert it never reappears. The standalone script was simply never updated
when that rule was enacted for the real app. This resolves itself once
the script is retired — no separate fix needed.
