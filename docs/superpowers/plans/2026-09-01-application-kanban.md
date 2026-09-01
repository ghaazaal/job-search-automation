# Application Kanban Board Implementation Plan (as executed)

> **Provenance:** this plan is retrospective. The board was built
> 2026-09-01 by a workflow (implement → three parallel reviewers → fix)
> from Ghazal's instruction "one column per application status, cards
> from the existing role table", before the spec's open questions were
> answered and before this plan existed. It is recorded so the ship
> keeps its plan-is-the-gate paper trail; checked boxes are what
> actually ran. Follow-on tasks at the bottom are real and unchecked.

**Goal:** `/activity` is a kanban board — one column per
`application.status`, cards built from fields the `role` table already
has, and moving a card calls the status endpoint that already exists.

**Architecture:** A view-only ship. One query grows three columns, one
page is rewritten, zero new routes, zero schema changes. The invariant
that shaped every task: *the board reads what the store already knows —
no new scoring, no new state, `match_score` never selected, a fit-band
pill never renders without its reason sentence* (MVP data rule #9,
DESIGN.md Fit Band).

**Tech Stack:** Python 3.13, pytest, Flask, SQLite; vanilla JS inline in
the rendered page (no libraries).

**Spec:** `docs/superpowers/specs/2026-08-30-application-kanban-design.md`
— including its "As built — 2026-09-01" section, which records where the
build superseded the proposal and which open question it decided by
omission.

Run all commands from the repo root: `python -m pytest job_hunt/tests -q`.
Baseline: **869 passing**. Final: **887 passing**.

---

## File structure

**Create:** nothing. No schema change, no new module, no new route.

**Modify:**
- `job_hunt/src/store/queries.py` — `_ACTIVITY_COLUMNS` becomes the six
  statuses; `activity_board()` also selects `band`, `reason`,
  `description_captured` (bool-coerced).
- `job_hunt/src/activity_page.py` — full rewrite: dark kanban.
- `job_hunt/tests/test_store_queries.py` — six-column + evidence-field
  + ordering coverage.
- `job_hunt/tests/test_activity_page.py` — rewritten against the new
  page.

**Untouched on purpose:** `app.py` (`render_activity(activity_board(...))`
signature kept), `store/tracking.py` and the status endpoint (already
validate every transition), schema (v10 stands).

---

### Task 1: six-column board query with card evidence — [x] DONE

**Files:** `src/store/queries.py`, `tests/test_store_queries.py`

- [x] Failing tests first: separate `REJECTED` and `CLOSED` columns
  (order-sensitive six-key assertion), `HIDDEN` excluded, cards carry
  `band` / `reason` / `description_captured` and never `match_score`.
- [x] Implement: `_ACTIVITY_COLUMNS = ("SAVED","APPLIED","INTERVIEWING",
  "OFFER","REJECTED","CLOSED")`; drop the REJECTED→CLOSED fold; extend
  the SELECT. Oldest-first `ORDER BY a.updated_at` and the STATUS-events
  attachment unchanged.

### Task 2: the kanban page — [x] DONE

**Files:** `src/activity_page.py`, `tests/test_activity_page.py`

- [x] Failing tests first: one column per status with counts; dark
  tokens present (`#0A0E1A`) and paper palette absent (`#F7F2E6`,
  Caveat); pill only when band AND reason both present; reduced-
  confidence class when `description_captured` falsy; no number/percent
  anywhere; attribute-breakout URL escaping; back link to `/`.
- [x] Implement per DESIGN.md: bg/panel/card/border tokens, JetBrains
  Mono uppercase labels + Inter body, mono column headers with counts,
  horizontal scroll for six columns, fit-band pill (15% bg / 35% border /
  full text; green/amber/red), reduced-confidence pill with NO band tint
  ("must not imply a verified skill match" read strictly), event log at
  card foot, `prefers-reduced-motion` zeroes transitions. All db strings
  through `_e` (html.escape); `role.url` only in an escaped href.

### Task 3: moving cards — [x] DONE

**Files:** `src/activity_page.py`, `tests/test_activity_page.py`

- [x] Failing tests first: cards carry `data-role-id` + `draggable`;
  a six-status move control per card; the script targets `/api/roles/`.
- [x] Implement: HTML5 drag-and-drop (columns as drop targets with a
  visible state) AND a per-card status select — both through one
  `moveCard()` posting `{"status": ...}` to the existing endpoint. On
  failure: card, select, and counts revert; brief inline error. JS reads
  `dataset` only — no interpolated db values in script.

### Task 4: review corrections — [x] DONE (4 must-fix of 17 findings)

- [x] Card `border-radius` removed — structural containers are square
  (DESIGN.md Layout). Regression test.
- [x] Hover color was an invented hex (#2A3A4E) → `--bg-row-sel`
  (#0F1F35) token. Regression test.
- [x] Header "in flight" count drifted after a move → `#live-count` +
  `data-live` marks, recomputed on every move and revert. It counts
  SAVED/APPLIED/INTERVIEWING/OFFER only — outcomes are not motion.
- [x] Oldest-first ordering was untested → backdated-row test, mutation-
  checked (removing the `ORDER BY` fails it).

### Task 5: follow-on fixes — [x] DONE 2026-09-01 (889 passing)

- [x] Failed-move revert: `nextElementSibling` captured before the move,
  `insertBefore` on revert — oldest-first survives a failed POST.
  Test: `test_failed_move_reverts_to_original_position` (string-level,
  like the rest of the page's JS coverage — no browser harness exists).
- [x] Drop-target highlight: `_dragDepth` counter on each column nets
  out per-child dragenter/dragleave pairs; a `.card.dragging` guard on
  dragenter, dragover AND drop ignores foreign drags; `dragend` clears
  any stranded highlight after a cancelled drag. Test:
  `test_drop_highlight_survives_child_hover_and_ignores_foreign_drags`.

### Task 6: map ↔ tracker wiring — [x] DONE 2026-09-01 (896 passing)

Ghazal's answer to the NEW-column question: no NEW column — instead the
map adds roles to the tracker and shows when it has.

- [x] `queries.py`: `_OPEN_ROLES` keeps tracked roles on the map
  (`a.id IS NULL OR a.status != 'HIDDEN'`), selects
  `a.status AS app_status`; `_role_view` carries it. Tests: tracked
  role stays with its status, untracked is None, HIDDEN leaves,
  watched-shelf test moved from APPLIED to HIDDEN.
- [x] `map_page.py` cards: a tracked role's SAVE button becomes an
  "IN TRACKER · status" marker linking to `/activity` (page-palette
  #3B7EA8). Tests: marker replaces SAVE; untracked still offers SAVE.
- [x] `map_page.py` drawer: payload gains `rid` + `app_status`; the
  dead MARK APPLIED replaced by wired ADD TO TRACKER (SAVED) and
  MARK APPLIED (APPLIED) via the existing delegated `[data-status]`
  handler; tracked roles show the marker instead; no buttons when the
  role has no id (in-memory render). Tests: payload fields, both
  buttons wired.
- [x] `test_end_to_end.py`: criterion 5 rewritten (applied stays on
  map, marked, and reaches the board) + 5b (HIDDEN leaves both).

### Task 7: cross-page navigation — [x] DONE 2026-09-01 (899 passing)

The three screens (map, tracker, profile) had no shared navigation —
only one-way "back to map" links. New `src/nav.py::nav_links(current)`
returns MAP · TRACKER · PROFILE links with the current page marked
(`aria-current="page"`, not linked); each page wraps and styles it in
its own palette, so the helper knows no CSS. Wired into the map header,
the board header (replacing the lone back link), and `/profile`'s shell
nav slot. One nav test per page.

### Decision-gated — [ ] BLOCKED, not on this plan's path
- [ ] `role.url` scheme guard (`javascript:` renders clickable) — in
  flight as its own task in a separate worktree (spun off 2026-09-01);
  do not duplicate here.
- [ ] `map_page.py` still on the retired paper palette — its own ship,
  flagged per the CLAUDE.md QA rule.
