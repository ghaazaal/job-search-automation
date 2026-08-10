# Handoff: Career Opportunity Map (ship 1)

## Overview
A daily-session view for job-seeking data professionals. A scraper produces a flat list of job
rows; this feature turns them into a short, ranked set of **company-centred opportunity maps**
the user can act on in one focused sitting. Two screens only:

1. **Opportunity map home** — a single ranked column of company cards.
2. **Role detail** — a right-hand drawer that opens over the home screen.

Out of scope for ship 1: onboarding, location/work-mode pickers, people-in-context hints.

## About the Design Files
The files in this bundle are **design references created in HTML** — prototypes showing intended
look and behaviour, not production code to copy. The task is to **recreate these designs in the
target codebase's existing environment** (React, Vue, SwiftUI, native, whatever is in use) using
its established component patterns, routing, and state libraries. If no environment exists yet,
pick the most appropriate framework and implement there.

The prototypes are single-file HTML components. Ignore their internal templating conventions
(`sc-if`, `sc-for`, `renderVals`) — those are artefacts of the prototyping tool. What matters is
the markup structure, the exact style values, the copy, and the interaction model described below.

## Fidelity
**High-fidelity** for `Opportunity Map Notebook.dc.html` (the chosen direction): final colours,
typography, spacing and interactions. Recreate it precisely, mapping the values below onto the
codebase's own token system where equivalents exist.

`Opportunity Map Wireframes.dc.html` is **low-fidelity** — the exploration that led here. It is
included for rationale only; do not implement it.

`Opportunity Map.dc.html` (dark) and `Opportunity Map Paper.dc.html` (light) are earlier
full-fidelity passes in a different palette, kept for reference. The **notebook** file is the one
to build.

---

## Product rules (breaking one is a bug)

1. **No numeric score appears anywhere.** No number, percentage, progress bar, star rating, or
   "8/10". Fit is expressed only as a band word plus a sentence.
2. **A fit band never appears without its reason sentence.** Bands are `STRONG FIT`,
   `PARTIAL FIT`, `STRETCH`. If a surface cannot fit the sentence, it must not show the band.
3. **Low confidence is a separate visual state from a low band.** When a listing arrived with no
   description, nothing was checked — the UI must not imply skills were compared and found
   lacking. It renders as a dashed "Not checked yet" block with a FETCH POSTING action, never as
   a band pill.
4. **The company owns the card; the role sits inside it.** Company name is the card's title; the
   role is a nested block below the rule.
5. **Watch entries have no role.** They are a different shape (compact tiles in a separate shelf),
   not a greyed-out act-now card.
6. **Every recommendation shows why it is there.** No unexplained ranking. Each card carries a
   company-level "why" line, and each role carries its band reason sentence.

**Success test:** a user can look at the top card and say out loud why it is there, without
opening anything.

---

## Screens / Views

### 1. Opportunity map home

**Purpose:** scan a ranked list, decide what deserves twenty minutes, open at most two or three.

**Layout**
- Page background `#F7F2E6` with a dot grid: `radial-gradient(rgba(42,51,66,.14) 1px, transparent 1px)`,
  `background-size: 22px 22px`, `background-position: 11px 11px`. Bottom padding 80px.
- A 26px hatched band at the very top of the page:
  `repeating-linear-gradient(112deg, rgba(59,126,168,.28) 0 1px, transparent 1px 7px)`
  masked with `linear-gradient(to bottom, #000, transparent)`. This is the only decorative
  hatching in the design — it is atmosphere, never meaning.
- Content column: centred, `max-width: 820px`, horizontal padding 40px.
- Header block: padding `30px 40px 34px`, baseline-aligned row, title left / meta right.
- Card list: vertical flex, `gap: 16px`.
- Watch shelf: below the list, `margin-top: 34px`, two-column grid, `gap: 12px`.

**Header**
- Title "today" — Caveat 600, 46px/1, `#D6482B`, letter-spacing .01em.
- Subtitle — Inter 400, 15px/1.6, `#4C5768`, `max-width: 46ch`, `text-wrap: pretty`.
  Copy: "Three companies worth twenty minutes. Everything below them is here for a reason you can read."
- Right meta, two lines, JetBrains Mono, letter-spacing .1em:
  `14 COMPANIES · 31 ROLES` (500, 11px, `#4C5768`) and `SCRAPED 06:40` (400, 11px, `#8A93A1`, margin-top 9px).

**Card anatomy (the core component)**
```
[company name]                              [n ROLES OPEN]
why this company — one line of evidence
────────────────────────────────────────────
[role title]
LOCATION · POSTED Nd · SALARY
[band pill]  reason sentence composed from matched evidence
────────────────────────────────────────────
[review role] [watch]                              [hide]
```

**Lead card** (rank 1, the only full-height card)
- `background:#FFFDF8`, `border:1px solid #CBBFA5`, `border-left:3px solid #2E7D5B`,
  `border-radius:4px`, `padding:22px 26px 20px`, `box-shadow:0 1px 0 rgba(42,51,66,.06)`.
- Company name: Inter 500, 21px/1.25, `#1F2937`, letter-spacing -.015em.
- Role count: JetBrains Mono 500, 11px, `#8A93A1`, letter-spacing .1em, right-aligned.
- Company why: Inter 400, 15px/1.65, `#4C5768`, margin-top 9px.
- Divider: 1px `#EBE3D2`, margin 18px 0.
- Role title: Inter 500, 17px/1.3, `#1F2937`.
- Role meta: JetBrains Mono 400, 11.5px, `#6E7787`, letter-spacing .06em, margin-top 9px.
- Band row: flex, gap 13px, align-items flex-start, margin-top 15px.
- Reason: Inter 400, 14.5px/1.6, `#3A4557`, `text-wrap: pretty`.
- Action row: flex, gap 10px; HIDE pushed right with `margin-left:auto`.

**Compact cards** (all subsequent companies with an open role — this includes both
"act now" and "new to you" entries; they differ only in weight, never in section)
- `background:#FFFDF8`, `border:1px solid #E0D8C4`, `border-radius:4px`, `padding:17px 22px`.
- Hover: `border-color:#CBBFA5`.
- Company name Inter 500, 18px/1.3, `#1F2937`, letter-spacing -.01em.
- Right meta JetBrains Mono 500, 10.5px, `#8A93A1`, letter-spacing .1em
  (e.g. `1 ROLE · SENIOR DATA ENG · 5d`, `NEW TO YOU · 2 ROLES · 3d`).
- Combined why + reason line: Inter 400, 14px/1.65; company evidence in `#6E7787`, the role's
  reason sentence in `#3A4557` within the same paragraph.
- Action row: band pill + REVIEW ROLE + WATCH, HIDE right-aligned; buttons `padding:7px 13px`,
  11px JetBrains Mono.

**Band pills**
| Band | Style |
|---|---|
| STRONG FIT | `background:#2E7D5B`, text `#FFFDF8`, JetBrains Mono 700 10px, letter-spacing .11em, `padding:5px 11px`, `border-radius:2px` |
| PARTIAL FIT | transparent, `border:1px solid #2A5F86`, text `#2A5F86`, `padding:4px 10px` |
| STRETCH | transparent, `border:1px solid #B9C4D0`, text `#6E7787`, `padding:4px 10px` |

**Low-confidence block** (rule 3) — replaces the band row entirely:
- `border:1px dashed #C9BFA8`, `background:#F4EFE1`, `border-radius:3px`, `padding:11px 13px`,
  margin-top 13px, flex row with 12px gap.
- Text Inter 400, 13.5px/1.6, `#6E7787`; the lead-in "Not checked yet." in `#3A4557`.
  Copy: "**Not checked yet.** This listing arrived without a description, so no skills have been
  compared against it."
- Trailing button FETCH POSTING: `background:#FFFDF8`, `border:1px solid #D5CDB9`, text `#D6482B`,
  hover `border-color:#D6482B`.

**Fold marker** — centred JetBrains Mono 400 10.5px `#8A93A1` letter-spacing .1em, flanked by 1px
`#DED5C1` rules: `8 MORE COMPANIES WITH OPEN ROLES`.

**Watch shelf** (rule 5)
- Heading "keeping an eye on" — Caveat 600, 26px, `#2E7D5B`; right meta `NO ROLE OPEN · 4`
  JetBrains Mono 400 10.5px `#8A93A1`; 12px bottom padding over a 1px `#E0D8C4` rule.
- Tiles: `background:#F4EFE1`, `border:1px solid #E0D8C4`, `border-radius:3px`, `padding:13px 15px`.
  Name Inter 500 14.5px `#3A4557`; reason Inter 400 13px/1.55 `#8A93A1`, margin-top 5px.
- No role, no band, no primary action. The tile's reason line is what earns its space.

**Quiet-day header** (rendered above the list when nothing reaches the top tier)
- Card `#FFFDF8` / `1px solid #E0D8C4` / radius 4 / padding 24px 26px, margin-bottom 20px.
- Title "nothing to apply to today" Caveat 600 26px `#2A3342`.
- Body Inter 400 14.5px/1.65 `#4C5768`, max-width 52ch:
  "31 postings came in; none named enough of your stack to earn the top of the list. That is the
  check working, not a dry spell."
- Two outline actions: FETCH 4 MISSING DESCRIPTIONS (`#D6482B` border + text),
  WIDEN SOURCES (`#E0D8C4` border, `#6E7787` text).

### 2. Role detail (drawer)

**Purpose:** confirm the recommendation, see the evidence, jump to the posting or to the
company's other roles.

**Shell**
- Full-viewport overlay: `position:fixed; inset:0; z-index:60; display:flex; justify-content:flex-end`.
- Scrim: absolutely positioned, `background:rgba(42,51,66,.26)`, closes on click.
- Panel: `position:relative; width:min(560px,94vw); height:100%; box-sizing:border-box;
  overflow:auto; overscroll-behavior:contain; background:#FFFDF8;
  border-left:1px solid #CBBFA5; padding:28px 32px 32px;
  box-shadow:-18px 0 40px -26px rgba(42,51,66,.55)`.
  `box-sizing:border-box` and `height:100%` (not `100vh`) are load-bearing — without them the
  footer actions fall below the viewport on short windows.
- Body scroll is locked (`document.body.style.overflow = 'hidden'`) while the drawer is open and
  restored on close/unmount.

**Contents, top to bottom**
1. Crumb row — `NORTHWIND ANALYTICS · ROLE 1 OF 3`, JetBrains Mono 500 10.5px `#6E7787`
   letter-spacing .1em; right-side ESC button (`border:1px solid #E0D8C4`, 11px mono, `#8A93A1`).
2. Role title — Inter 500, 24px/1.25, `#1F2937`, letter-spacing -.02em, margin-top 16px.
3. Meta line — JetBrains Mono 400, 11.5px/1.75, `#6E7787`, letter-spacing .05em
   (e.g. `REMOTE (US) · POSTED 2d · $145–170k · FULL DESCRIPTION CAPTURED`).
4. **Role tabs** (only when the company has more than one open role) — wrapping flex, gap 7px,
   above a 1px `#EBE3D2` rule. Active: `border:1px solid #2E7D5B`, `background:#EAF2ED`,
   text `#215E44`, Inter 500 11.5px. Inactive: `border:1px solid #E0D8C4`, text `#6E7787`,
   hover `border-color:#CBBFA5; color:#3A4557`. Clicking swaps title, meta, band, reason and
   evidence in place.
5. Band + reason block — `background:#F4EFE1`, `border:1px solid #E0D8C4`, radius 3,
   `padding:15px 16px`, flex gap 13px. Same three pill styles as the list.
6. Evidence grid — two equal columns, gap 22px, margin-top 24px.
   - Left heading `MATCHED FROM YOUR RESUME`, JetBrains Mono 500 9.5px `#6E7787`
     letter-spacing .11em, 10px bottom padding over a **solid** `#2E7D5B` 1px rule.
     Chips: `background:#EAF2ED`, `border:1px solid #C3DACD`, text `#215E44`, Inter 400 12.5px,
     `padding:5px 10px`, radius 2, `display:inline-block`, `white-space:nowrap`.
   - Right heading `IN THE POST, NOT ON YOUR RESUME` over a **dashed** `#C9BFA8` rule.
     Chips: transparent, `border:1px dashed #C9BFA8`, text `#4C5768`, same metrics.
     Followed by a gap note, Inter 400 12.5px/1.6 `#8A93A1`, margin-top 12px.
   - Gaps are never red and never labelled as failures — neutral heading, dashed outline, and a
     sentence saying what the gap actually means.
7. "why this company" — Caveat 600 22px `#2E7D5B` over a 1px `#EBE3D2` rule; body Inter 400
   13.5px/1.65 `#4C5768`.
8. Footer actions over a 1px `#EBE3D2` rule: OPEN POSTING ↗ (filled `#D6482B`, text `#FFFDF8`),
   MARK APPLIED (outline `#D5CDB9`, hover border/text `#2E7D5B`), and a right-aligned
   NEXT ROLE HERE → / BACK TO MAP → text button (`#8A93A1`, hover `#3A4557`).

---

## Interactions & Behavior

- **REVIEW ROLE** (any card) opens the drawer at that company, role index 0.
- **Role tab click** switches the displayed role within the same company; the crumb updates to
  `ROLE n OF m`.
- **Next control**: when more roles remain at this company the label is `NEXT ROLE HERE →` and it
  advances the index; on the last role the label becomes `BACK TO MAP →` and it closes the drawer.
- **Close**: ESC button, `Escape` key, or clicking the scrim.
- **Body scroll lock** on open; restored on close and on unmount.
- **Drawer scroll** is contained (`overscroll-behavior:contain`) so it never chains to the page.
- **Hover states**: compact cards lift their border to `#CBBFA5`; primary buttons darken
  `#D6482B → #A83519`; secondary buttons take a `#2E7D5B` border and text; HIDE goes
  `#9AA3AE → #4C5768`.
- **No animation** is specified. If the codebase has a drawer primitive with a slide-in, use its
  default; do not invent motion.
- **Responsive**: desktop-first, single column capped at 820px. The drawer is
  `min(560px, 94vw)`, so it degrades to a near-full-width sheet on narrow windows without
  reflowing the list.

## State Management

```
openCompany: string | null   // which company's drawer is open
openRoleIndex: number        // index within that company's roles, reset to 0 on open
```

Derived per render: the active role object, band flags (`isStrong`/`isPartial`/`isStretch`),
`hasSiblings = roles.length > 1`, crumb string, next-control label.

Feature flags used during design review, worth keeping as props:
`showWatchShelf` (boolean, default true) and `quietDay` (boolean, default false).

**Data shape** the screens expect:
```ts
type Band = 'STRONG FIT' | 'PARTIAL FIT' | 'STRETCH';

type Role = {
  title: string;
  tab: string;            // short label for the role tabs
  meta: string;           // location · posted · salary · capture status
  band: Band | null;      // null when the listing had no description
  reason: string;         // required whenever band is non-null (rule 2)
  matched: string[];
  gaps: string[];
  gapNote: string;
  descriptionCaptured: boolean;   // false drives the low-confidence block (rule 3)
};

type Company = {
  name: string;
  why: string;            // company-level evidence line (rule 6)
  state: 'ACT_NOW' | 'DISCOVER' | 'WATCH';
  roles: Role[];          // empty for WATCH (rule 5)
};
```

Ranking is server-side; the client renders the order it is given. `ACT_NOW` and `DISCOVER`
companies share one column (weight differs, section does not); `WATCH` companies render only in
the shelf.

## Design Tokens

**Colour**
| Token | Hex | Use |
|---|---|---|
| paper | `#F7F2E6` | page background |
| paper-dot | `rgba(42,51,66,.14)` | dot grid |
| surface | `#FFFDF8` | cards, drawer |
| surface-sunk | `#F4EFE1` | reason block, watch tiles, low-confidence block |
| border | `#E0D8C4` | default card border |
| border-strong | `#CBBFA5` | lead card, drawer edge, hover |
| border-dashed | `#C9BFA8` | low-confidence, gap chips |
| rule | `#EBE3D2` | inner dividers |
| rule-faint | `#DED5C1` | fold marker rules |
| ink | `#1F2937` | titles |
| ink-body | `#3A4557` | reason sentences |
| ink-muted | `#4C5768` | body copy |
| ink-soft | `#6E7787` | meta, secondary |
| ink-faint | `#8A93A1` | labels, watch reasons |
| ink-ghost | `#9AA3AE` | HIDE at rest |
| green | `#2E7D5B` | strong fit, section headings, secondary hover |
| green-deep | `#215E44` | matched chip text |
| green-tint | `#EAF2ED` | matched chip / active tab background |
| green-tint-border | `#C3DACD` | matched chip border |
| blue | `#2A5F86` | partial fit |
| blue-hatch | `rgba(59,126,168,.28)` | top hatch band only |
| grey-blue | `#B9C4D0` | stretch border |
| vermilion | `#D6482B` | primary action, "today" |
| vermilion-dark | `#A83519` | primary hover |

**Type**
- Display / section headings: **Caveat** 600 — 46px (page title), 26px (section), 22px (drawer section).
- Body: **Inter** 400/500 — 24 / 21 / 18 / 17 / 15 / 14.5 / 14 / 13.5 / 12.5px.
- Data, labels, buttons: **JetBrains Mono** 400/500/700 — 11.5 / 11 / 10.5 / 10 / 9.5px,
  uppercase, letter-spacing .05–.11em.
- Google Fonts: `Caveat:wght@500;600`, `Inter:wght@400;500;600`, `JetBrains Mono:wght@400;500;700`.

**Spacing** — 8px base, used at 4 / 6 / 7 / 9 / 10 / 12 / 13 / 16 / 18 / 22 / 24 / 26 / 34 / 40px.
Comfortable-dense: one full card, then compact rows.

**Radius** — 2px (pills, chips), 3px (buttons, tiles, sunk blocks), 4px (cards, drawer).

**Shadow** — cards `0 1px 0 rgba(42,51,66,.06)`; drawer `-18px 0 40px -26px rgba(42,51,66,.55)`.

## Assets
None. No images, icons, or illustrations — the only graphic element is the CSS hatch/dot-grid
gradients described above. The visual reference images that informed the direction (notebook
hatching, gouache marks) are mood only and are not part of the build.

## Files
- `Opportunity Map Notebook.dc.html` — **the design to build** (home + role-detail drawer).
- `Opportunity Map Wireframes.dc.html` — lo-fi exploration, six options across two rounds; useful
  for the reasoning behind the layout (why one column, why watch is a shelf, why folded rows keep
  their reason line).
- `Opportunity Map.dc.html` — earlier dark-palette pass.
- `Opportunity Map Paper.dc.html` — earlier light-palette pass.
- `design-brief-opportunity-map.md` — the original brief, including the product rules.
