# Plan — Paper shell redesign (design handoff: `design/wireframes/design_handoff_opportunity_map/`)

Date: 2026-09-01. Authority: `Opportunity Map App.dc.html` + the bundle's
README. The user attached the bundle and asked for the design to be
followed — that is the explicit approval CLAUDE.md requires to supersede
DESIGN.md's dark tokens for these pages. The tracker's dark theme (PR #23)
is explicitly superseded by the handoff ("the tracker is **not** a
dark-themed surface").

## What the handoff adds over what is already built

The map page (`map_page.py`) already implements the paper palette from the
ship‑1 Notebook handoff. The deltas:

1. **App shell** — a sticky top nav (14px solid hatch strip, wordmark
   "opportunity map" + user label, MAP/TRACKER/PROFILE tabs with counts)
   shared by all three pages, replacing each page's text-link nav and the
   map's 26px masked hatch band.
2. **Tracker** rebuilt in the paper palette as the design's kanban:
   sunk columns, band-accented cards, ←/→ arrow moves, ROLE opens the
   shared drawer.
3. **Profile** rebuilt to the design's five-card layout on the existing
   data (resumes, location/modes, skills, watchlist, filtered-out counts).
4. **Shared role drawer** — one drawer implementation used by map and
   tracker (module `src/drawer.py`), with the handoff's fixes
   (`height:100%` + `box-sizing:border-box`, MARK APPLIED navigates to
   the tracker).
5. Map card refinements to match the App file exactly (lead card's filled
   REVIEW ROLE, compact card's combined why+reason paragraph with the
   pill in the action row, 42px page title, header padding 30/40/30).

## Decisions where design and store disagree (recorded, not silent)

- **Six columns, not five.** The store has REJECTED between OFFER and
  CLOSED (`STATUSES` in `store/tracking.py`); dropping the column would
  hide real cards, violating flag-never-hide. The board renders SIX
  columns in the design's visual language; REJECTED is styled like CLOSED
  (sunk, finished). Arrow ladder: SAVED → APPLIED → INTERVIEWING → OFFER
  → REJECTED → CLOSED, clamped, no wrap.
- **Drag-and-drop stays.** The design specifies arrow moves; the shipped
  board has working cross-column drag-and-drop. Arrows are added per the
  design, DnD is kept (no visual cost, tested behaviour). The per-card
  status `<select>` is removed — arrows + DnD replace it.
- **Tracker cards show the band pill without the reason sentence** — as
  drawn in the App file (the design's own answer to rule 2 here is that
  the ROLE button opens the drawer, which carries the sentence). The pill
  still renders only when the role HAS a band+reason pair in the store,
  and stays muted when no description was captured.
- **Next-action note / next-action strip: omitted.** No store field holds
  a next action; the note is optional in the design and fabricating one
  breaks the no-invented-facts rule. `LAST MOVE Nd AGO` IS derivable
  (max `updated_at`) and renders.
- **Profile "NEXT RUN 06:40 DAILY" and "CHECKED DAILY": omitted.** The
  real schedule lives in Windows Task Scheduler, outside the app's
  knowledge; a hardcoded label would drift. Counts render; cadence claims
  do not.
- **"OPEN THE REJECT LOG": omitted.** No reject-log page exists. The
  sunk filtered-out card renders the true counts (closed / unverified /
  off-topic from `eligibility_counts` + latest run) with no dead button.
  Follow-up candidate, recorded here.
- **WHAT COUNTS AS A MATCH note** is rephrased to a sentence that is true
  of the scorer ("skills come from your active resumes; a posting must
  name them in its own description") — the design's "three of these"
  wording asserts a threshold the scorer does not express that way.
- **Map SAVE / ADD TO TRACKER / IN TRACKER wiring (PR #23) is kept** and
  restyled into the design's action rows; the prototype predates that
  wiring.
- **Setup/confirm screens are untouched** (pre-setup surfaces; the shell
  tabs would only bounce back to /setup).

## Numbered steps

1. **`src/shell.py`** — new module: `shell_css()` and
   `shell_nav(active, map_count, tracker_count, user_label)` returning
   the sticky nav HTML per the App file (strip 14px unmasked, wordmark
   Caveat 600 27px `#D6482B`, tabs mono 11.5px with active
   `#D6482B`/`#FFFDF8`/2px bottom rule, counts mono 10px `#A6AEB9`).
   Tabs are links (`/`, `/activity`, `/profile`) — a page change resets
   any drawer by construction.
2. **`src/drawer.py`** — shared drawer CSS + JS extracted from
   `map_page.py`, upgraded to the App file: panel `height:100%;
   box-sizing:border-box`, crumb/ESC row, role tabs (only when >1 role),
   band block, evidence grid, "why this company", footer with
   OPEN POSTING ↗ / ADD TO TRACKER / MARK APPLIED · GOES TO TRACKER /
   NEXT ROLE HERE → | BACK TO MAP →. MARK APPLIED posts then navigates to
   `/activity`. Exposes `drawer_css()`, `drawer_js(payload_json)` where
   the payload shape is the one `map_page._drawer_payload` builds today.
3. **Store: tracker counts + drawer data.**
   - `queries.py`: `live_tracker_count(conn, user_id)` (statuses
     SAVED/APPLIED/INTERVIEWING/OFFER) and
     `open_company_count(conn, user_id)` (distinct companies matching the
     map's open-roles filter) — both single COUNT queries for the nav.
   - `activity_board` gains `matched`, `gaps`, `work_mode`, `salary`,
     `posted_date`, `company_id` on each card so the tracker can build a
     drawer payload.
4. **`map_page.py`** — adopt shell (drop 26px masked hatch + text nav;
   header `30px 40px 30px`, title 42px), lead card filled REVIEW ROLE
   button, compact cards: combined why+reason paragraph
   (`#6E7787` + `#3A4557` span), pill in the action row; drawer moved to
   `drawer.py` import. Product rules stay enforced (no numerics, no band
   without reason, unchecked block).
5. **`activity_page.py`** — full rewrite to the paper board: shell nav,
   header ("in flight", Caveat 42px, derived count + LAST MOVE), board
   scroller (`max-width:1180px; overflow-x:auto`) wrapping
   `grid-template-columns:repeat(6,minmax(176px,1fr))`, columns/cards
   per the App file, arrows + DnD posting to
   `/api/roles/<id>/status`, ROLE button opening the shared drawer,
   empty-column dashed block, reduced-motion guard kept.
6. **`profile_page.py`** — new module rendering /profile in the design's
   layout: YOUR RESUMES card (accent rows, EDIT / PAUSE|RESUME / DELETE,
   footer ADD A RESUME + RUN THE SEARCH NOW), the two-column
   WHERE YOU ARE LOOKING / WHAT COUNTS AS A MATCH grid, YOUR WATCHLIST
   card (+ ADD A COMPANY reveals the name/domain/url inline form),
   sunk what-got-filtered-out card with true counts. Wires existing
   endpoints only. `setup_page.render_profile` is retired from /profile.
7. **`app.py`** — routes pass nav counts to renderers; /profile route
   gathers resumes, profile, watchlist, filtered counts; /activity
   passes drawer payload; / passes counts.
8. **Tests** — update `test_activity_page.py` (six columns stay; dark
   tokens test → paper tokens; select-control tests → arrow tests;
   drawer presence), `test_map_page.py` (shell nav), add
   `test_profile_page.py` (design layout on real data shapes, no
   numerics, escaping, wiring), keep every product-rule test green.
9. **Verify** — full pytest suite; then `python main.py --serve` against
   a scratch DB and browser-check all three pages + drawer on map and
   tracker (fresh port, mindful of the stale-server pitfall).
10. **Ship** — branch `feat/paper-shell-redesign`, commit (including the
    unzipped design bundle under `design/`), push, open PR.

## As built (corrections found during implementation)

- **Map header meta**: the design's right meta is one short line
  (`SCRAPED 06:40`); this app's meta line carries the full set-aside
  account and squeezed the subtitle to a sliver. `.meta-r` is capped at
  340px and wraps (line-height 1.7) instead.
- **Tracker column labels** render uppercase via `text-transform` on
  `.colname` — the label strings stay lowercase in Python, matching the
  old board's convention.
- **Empty-column placeholders**: a JS `fixPlaceholders()` removes the
  "nothing here yet" note when a card arrives in a column and restores it
  when the last card leaves — the design never showed a placeholder above
  a card.
- **Drawer back label** is a parameter: `BACK TO MAP →` over the map,
  `BACK TO BOARD →` over the tracker — the label must name the page the
  close returns to.
- **`src/nav.py` deleted**: the text-link nav helper had no callers left
  once all three pages adopted the shell.
- **Watchlist resolution note** (e.g. "pending next run") is kept on
  unresolved profile rows — it was live information on the old page and
  dropping it failed a route test for a reason.
- **Verified in browser** against a scratch copy of the real store
  (34 companies): map cards + drawer, tracker arrow move persisted
  end-to-end (SAVED→APPLIED, counts and badge updated), shared drawer
  over the board, profile cards on real resume/watchlist data. The
  sticky nav's DOM geometry was confirmed pinned (top=0 under scroll);
  an embedded-pane screenshot artifact made it look detached, the real
  browser renders it correctly.
- 920 tests passing (899 before the ship).
