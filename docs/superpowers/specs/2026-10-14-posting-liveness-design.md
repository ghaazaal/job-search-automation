# Posting liveness — is a stored posting still open?

Asked by Ghazal, 2026-10-14: check whether past positions are still
available; when one is not, change its status and drop it from the map and
the tracker.

## Rule

A posting is CLOSED only when its own board says so. OPEN when the board
shows it with nothing saying otherwise. Everything else — rate limit, bot
wall, timeout, an unreadable page — is UNKNOWN, and UNKNOWN changes nothing.
A network error is a check that did not happen, not a closure.

## Evidence per board (measured on the live store, 2026-10-14)

| Board | Closed when | Open when |
|---|---|---|
| LinkedIn | 301 to `…?trk=expired_jd_redirect`; "No longer accepting applications" banner; HTTP 404 | public apply link present |
| Jobicy | HTTP 404/410; `jv-closed` "Applications closed" section | 200 with neither |
| The Muse | "This job is no longer available." in the job header; 404/410 | 200 without it |
| RemoteOK | the posting's OWN row has class `closed` (related rows ignored) | own row without it |
| We Work Remotely | 301 to the home page | 200 |
| Working Nomads | `/job/go/<id>/` redirects back to a Working Nomads listing | redirects to the employer |
| Hacker News | comment deleted or dead (HN API) | never — HN has no "closed" |

No checker, no request: Himalayas (Cloudflare 403 on every page), devitjobs
(every URL redirects to a jobcopilot sign-up), DataArt (JS shell, identical
for every vacancy).

## What a closure does

| Where | Effect |
|---|---|
| `role` | `closed_at` + `closed_evidence` stamped (a column, never a DELETE) |
| `posting_check` | one row per check that reached a board, any verdict |
| `event` | `POSTING OPEN→CLOSED`; plus `STATUS SAVED→CLOSED` when it applies |
| Map | role hidden; header says "N HIDDEN (POSTING CLOSED)" |
| Tracker, SAVED | moves to CLOSED — nothing was sent, nothing left to do |
| Tracker, APPLIED or later | stays put; card says "POSTING CLOSED", evidence on hover — an employer taking the ad down does not end an application in their hands |

A closed role is not re-checked. A wrong closure is undone by clearing
`closed_at`; the evidence that caused it stays in `posting_check`.

## When it runs

- `python main.py --check-postings [--limit N]` — on demand, prints each closure.
- After every browser run, on the run's own thread once the run is on the
  map: up to 150 postings, least-recently-checked first.
- After the weekly scheduled scrape (`scripts/weekly_scrape.py`): all of them.

Tracked roles go first. LinkedIn gets 3 s between requests, other boards
1 s; a board that rate-limits (429/999) is left alone for the rest of the
pass.

## Residuals

- Himalayas (about 300 live rows) cannot be checked from a plain HTTP
  client. Its public API carries an `expiryDate`, which a later change
  could store at scrape time.
- A talent-platform role that also closes is counted in both the platform
  and the closed clause of the header.
