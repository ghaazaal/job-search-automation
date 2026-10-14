# Talent platforms hidden + LinkedIn metro names — plan

2026-09-25, after run 21. Two user decisions, both taken in chat:

1. Talent platforms (Proxify, Toptal, ...) are not employers posting a
   job — they recruit into a freelance pool. **Hide them, counted in the
   header** (option a). This is a THIRD user-approved exception to
   flag-never-hide, and CLAUDE.md must say so.
2. **Fix metro names.** `geo.location_candidates` returns nothing for
   LinkedIn metro phrasings like "Seoul Incheon Metropolitan Area", so a
   hybrid role in Korea is read as unplaceable and flagged instead of
   hidden as ON-SITE ELSEWHERE. A bug, not a policy change.

## Evidence (live store, 2026-09-25)

Talent-platform rows not dropped: Proxify 3, Proxify AB 2, Toptal 1,
micro1 1, mercor 1 (already closed), Lemon.io 1, Careerswift 2,
Jobgether 1. Sources: weworkremotely, working_nomads, himalayas.

Hybrid/on-site rows whose location parses to no country: exactly 4 —
"Seoul Incheon Metropolitan Area", "Metro Manila",
"Washington DC-Baltimore Area", "Greater Hamilton (Burlington)
Metropolitan Area". All LinkedIn.

## Decisions baked in (say if any is wrong)

- **D1 — marketplaces, not agencies.** The list names platforms whose
  "job" is a pool to join. Recruitment agencies (Nigel Wright, Kforce,
  Opus Recruitment...) usually front a real employer's real opening and
  are NOT included.
- **D2 — seed list:** `proxify`, `toptal`, `micro1`, `mercor`,
  `lemon.io`. **Careerswift and Jobgether are left out until you confirm**
  (Jobgether reposts other companies' jobs; Careerswift is unclear).
- **D3 — hidden at read time, not scrape time.** The filter runs where
  the map reads roles, so the 8 platform rows already stored disappear
  too, and removing a name from the list brings them back. Nothing is
  deleted or stamped. Cost: those rows still get scored each run
  (a handful — negligible).
- **D4 — tracker untouched.** Your saved Proxify role stays on the
  tracker; it leaves the map. The header count includes it.
- **D5 — match rule:** company name folded (case, accents,
  punctuation), trailing legal suffix removed (AB, Inc, Ltd, LLC, GmbH,
  BV, OÜ, SA, SRL), then EXACT equality with a list entry. No substring
  match — "Toptal Recruiting Partners" would not match `toptal`.
- **D6 — metro fallback is narrow.** Individual words are tried as city
  names ONLY when the segment carried a metro marker (a stripped
  "greater"/"metro" prefix or "... area/region" suffix) and nothing else
  matched. A bare "Hybrid" or "Remote" location never reaches it.
  Membership logic is unchanged: if any reading is Armenia → silence.
- **D7 — the 4 stored rows are re-judged once** with the same drop rule
  the scrape uses and soft-dropped via `role.dropped_at` (reversible,
  never a role with an application row). Reported as a count.

## Steps

Worktree `.worktrees/talent-platforms`, branch
`feat/talent-platforms-metro-names` from local HEAD.

1. **vocabulary.yaml** — new `talent_platforms:` block: `names:` (D2) and
   `legal_suffixes:` (D5). Comment says what qualifies (D1).
2. **`src/scoring/platforms.py`** — `is_talent_platform(name, cfg) ->
   bool`. Tests: each seed name, "Proxify AB", "TOPTAL, Inc.", negatives
   "Toptal Recruiting Partners", "Nigel Wright Recruitment", "", None.
3. **Store queries** (`src/store/queries.py`) — `platform_company_ids(conn,
   user_id, cfg) -> set[int]`; `map_sections`, `eligibility_counts`,
   `open_company_count` take an `exclude_company_ids` argument and skip
   them. New `platform_role_count(...)` for the header. Tests on an
   in-memory store: a platform company vanishes from all three and is
   counted; a tracked platform role still appears in `activity_board`.
4. **app.py + map_page.py** — load the vocab once, pass the ids, render
   `N HIDDEN (TALENT PLATFORM)` after the on-site clause, only when N>0.
   Profile page's filtered-summary line gains the same count. Render test.
5. **geo.py metro fallback** (D6) — split segments additionally on `-`,
   `(`, `)`; strip a `metro ` prefix; word-level fallback for
   metro-marked segments. Tests: the 4 real strings → foreign for `am`;
   "Yerevan Metropolitan Area" → local; "Hybrid", "Remote",
   "Armenia" unchanged; full existing geo suite green.
6. **One-off re-judge** (D7) — `scripts/rejudge_unplaced.py`, dry-run by
   default, `--apply` to stamp. Run dry against a COPY of
   `job_hunt.db`, then on the real db after merge (asks you first).
7. **CLAUDE.md** — add exception 3 to the flag-never-hide list, with the
   D1 boundary and the header wording.
8. Full suite (920 on master), browser check of the header on a scratch
   db copy (port 5057, not 5000), opus review of steps 3 and 5,
   mutation-check each new test, push, PR.
