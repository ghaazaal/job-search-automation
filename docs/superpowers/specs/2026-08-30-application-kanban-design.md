# Application status — kanban view

Date: 2026-08-30
Status: implemented 2026-09-01 — see "As built" below. Open question 1
(the `NEW` column) was NOT answered by Ghazal and remains open; the build
resolved it by omission (see residuals).
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

## As built — 2026-09-01

Built on Ghazal's instruction "one column per application status, cards
from the existing role table", via a workflow (implement → three parallel
reviewers → fix). 887 passing (baseline 869). Uncommitted on master at
time of writing. This section was written AFTER the build: the
implementation did not read this spec, and where the two disagree, what
follows is what shipped.

### What shipped

`GET /activity` (`job_hunt/src/activity_page.py`, full rewrite) is the
board — no new page. `job_hunt/src/store/queries.py::activity_board`
feeds it; `app.py` unchanged.

- **Six live columns**, left to right: `SAVED`, `APPLIED`,
  `INTERVIEWING`, `OFFER`, `REJECTED`, `CLOSED`. This supersedes this
  spec's proposed collapsed end-group: the instruction said one column
  per status, so outcomes got real columns. `HIDDEN` has no column —
  hiding means the user asked not to see it (unchanged from the old
  page). Oldest-first within a column, now mutation-tested (deleting the
  `ORDER BY` fails `test_activity_board_is_oldest_first_within_a_column`;
  before 2026-09-01 nothing would have caught that).
- **Cards** read only what the `role` table already has: company, title
  (link), location, days-in-state, fit band + reason, status-event log.
  `activity_board` now also selects `band`, `reason`,
  `description_captured`; `match_score` is never selected (data rule #9).
  The fit-band pill renders ONLY when band and reason are both present —
  a pill without its sentence is a bug (DESIGN.md). When
  `description_captured` is falsy the pill drops the band tint entirely
  (muted border, secondary text): "must not imply a verified skill
  match" was read as no band colour at any opacity, not a dimmer one.
- **Both interaction modes** from open question 2: HTML5 drag-and-drop
  AND a per-card status select. Both funnel through one `moveCard()`
  posting to the existing `/api/roles/{id}/status` — the endpoint fit
  as-is; no new route was needed, as this spec suspected. Failure
  reverts card, select, and counts, with a brief inline error. The
  header "in flight" number counts only SAVED/APPLIED/INTERVIEWING/OFFER
  (outcomes are not motion) and live-updates via `#live-count` +
  `data-live` column marks.
- **Dark design system.** The page moved from the paper palette to the
  DESIGN.md tokens (CLAUDE.md makes DESIGN.md the authority for visual
  decisions). All db strings are `html.escape`d; `role.url` lands only
  in an escaped href; inline JS reads `dataset` only, never
  interpolated values. `prefers-reduced-motion` zeroes all transitions.

### Review corrections (applied 2026-09-01)

1. Card `border-radius` removed — cards are structural containers,
   DESIGN.md says no rounding on those. Regression-tested.
2. Card hover used an invented hex (#2A3A4E); now the `--bg-row-sel`
   token (#0F1F35). Regression-tested.
3. Header count drifted after a drag (per-column counts refreshed, the
   header didn't) — now recomputed on every move and revert.
4. The oldest-first mutation test above.

### Open question resolutions — all answered

- **NEW roles (no `application` row): not on the board — Ghazal decided
  2026-09-01.** Instead, the flow is: the map (card actions AND the
  role detail drawer) offers ADD TO TRACKER, and once a role is on the
  board the map KEEPS it, marked "IN TRACKER · status" linking to
  `/activity`. Before this, `map_sections` dropped any role with an
  application row (`a.id IS NULL`) — saving a role made it vanish from
  the map. Now only `HIDDEN` removes it (the user asked not to see it);
  every other tracked status stays listed with `app_status` on the role
  view. The drawer's MARK APPLIED button, which had been dead since the
  drawer was built (no data attributes, no role id in the payload), is
  now wired: ADD TO TRACKER posts SAVED, MARK APPLIED posts APPLIED,
  both through the existing endpoint. Superseded acceptance criterion 5
  ("applied leaves the map") updated in `test_end_to_end.py`; the
  watched-company shelf now means "no VISIBLE role" (hidden), since a
  tracked role keeps its company a card. 896 passing.
- Drag vs click: both (above).
- Outcomes visible: yes, as real columns (above); HIDDEN stays off.

### Accepted residuals

- Failed-move revert appends the card to the BOTTOM of its origin
  column — oldest-first is silently wrong until reload. Fix is
  `nextElementSibling` + `insertBefore`.
- Column `dragleave` flickers the drop-target highlight when the pointer
  crosses a child card, and `dragover` accepts foreign drags (text or
  links dragged from elsewhere highlight columns).
- `role.url` is escaped but scheme-unvalidated: a scraped
  `javascript:` URL renders as a clickable stored-XSS link. Pre-existing
  pattern (old page and map page share it); spun into its own task
  2026-09-01, in progress in a separate worktree.
- Minor DESIGN.md deviations left as taste calls: card titles are Inter
  (decision log says mono for all non-body; the typography scale's "row
  titles" names no font), card padding 12/14 vs the stated 14/16, the
  status select is mono 10px vs 11px for row-level controls.
- Dangling "· in this state" separator when `updated_at` is unparseable;
  `applied_at` selected but unused; per-card events query is N+1. All
  pre-existing or cosmetic.
- `map_page.py` still uses the retired paper palette — out of this
  scope, flagged per the CLAUDE.md QA rule, needs its own decision.
