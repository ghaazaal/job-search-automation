# Design brief — career opportunity map (ship 1)

## One line

Turn a flat list of scraped job rows into a short, ranked set of company-centred
opportunity maps a job seeker can act on in a single daily session.

## What is being designed

Two screens only:

1. **Opportunity map home** — a ranked list of company cards.
2. **Role detail** — the panel behind "review role".

Out of scope: onboarding, location/work-mode pickers (ship 2), people-in-context
hints (ship 3). Do not design them.

## Who it is for

Job-seeking data professionals — Analytics Engineer, Data Engineer, Data Analyst,
Product Analyst. Desktop-first, used in one focused session per day. The user is
tired, applying to many roles, and cannot afford to read everything.

## Fixed — do not redesign

From `DESIGN.md`:

- Dark mode only. No light mode.
- Background `#0A0E1A`, surface `#0D1117`, border `#1E2A3A`.
- Cyan `#00D4FF` primary interactive · green `#00D9A3` approve · amber `#F59E0B`
  partial · red `#E05C5C` skip.
- JetBrains Mono for labels and data, Inter for body and descriptions.
- 8px base spacing unit. Comfortable-dense.

## Product rules that constrain the visual design

These are not preferences. Breaking one is a bug.

1. **No numeric score appears anywhere.** No number, no percentage, no progress
   bar, no star rating, no 8/10.
2. **A fit band never appears without its reason sentence.** The band is
   `strong fit`, `partial fit`, or `stretch`.
3. **Low confidence is a separate visual state from a low band.** When a listing
   had no description, the design must not imply that skills were checked and
   found lacking — nothing was checked at all.
4. **The company owns the card; the role sits inside it.** This is the product's
   core reframe and must survive the visual pass.
5. **`WATCH` cards have no role.** They are a different card shape, not a greyed
   out `ACT_NOW`.
6. Every recommendation shows why it is there. No unexplained ranking.

## Structure already agreed

See the approved wireframe. Card anatomy:

```
[state pill]  Company name
why this company — one line of evidence
──────────────────────────────
Role title
location · posted · salary
[fit band pill]
reason sentence, composed from matched evidence
──────────────────────────────
[review role] [watch] [hide]
```

## Open questions for the design session

1. **Three states, one list.** `ACT_NOW`, `WATCH` and `DISCOVER` are ranked in a
   single column. How do they read as one prioritised list rather than three
   filtered groups?
2. **Variable card height.** The reason sentence runs one to three lines
   depending on how much evidence matched. Cards will not be uniform. Cap the
   sentence, let cards breathe, or something else?
3. **Density loss.** The old design showed roughly 12 job rows above the fold.
   These cards are far taller. How many maps should be visible before scrolling,
   and does that change the card?
4. **Two dimensions on one pill.** Band (strong/partial/stretch) and confidence
   (description captured or not) are independent. One component or two?
5. **Empty and first-run states.** What does the screen look like on day one
   before any scrape, and on a day when nothing reaches `ACT_NOW`?
6. **The `WATCH` card.** It has no role, no fit band, and one action. What earns
   its space in the list?
7. **Evidence chips on role detail.** Matched skills and "not on your resume"
   gaps sit side by side. How is a gap shown without reading as failure?

## Success test

A user can look at the top card and say out loud why it is there, without
opening anything.
