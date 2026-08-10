# Design System — Job Search Automation (JobBot)

## Product Context
- **What this is:** A career opportunity mapping product for job-seeking data professionals. Scrapes and scores listings, then presents company-centred opportunity maps for daily review, and generates tailored resumes and cover letters for approved roles.
- **Who it's for:** Job-seeking data professionals (Analytics Engineer, Data Engineer, Data Analyst, Product Analyst). Ghazal is the author and also a user. Daily review session, desktop-first.
- **Space/industry:** Job search / data analytics workflow
- **Project type:** Web app, multi-user
- **Memorable thing:** "My personal intelligence layer" — every design decision should reinforce the feeling that this tool knows what matters and filters the noise. It surfaces signal, not volume.

## Aesthetic Direction
- **Direction:** Industrial/Utilitarian with personal warmth — data-forward, not cold.
- **Decoration level:** Minimal. Data density earns the real estate. Color carries semantic meaning.
- **Mood:** Serious tooling that happens to care about the user. Like a Bloomberg Terminal built for one person. Not generic SaaS. The user should feel like they're running an intelligence operation, not filling out a job board.
- **Reference:** Approved Variant A mockup at `~/.gstack/projects/JobSearchautomation/designs/job-review-dashboard-20260528/variant-A.png`

## Typography
- **Display/Hero/Data:** JetBrains Mono — every data point feels intentional; terminal precision. Note: match scores are never rendered — see Fit Band.
- **Body/Descriptions:** Inter — readable at density without fatigue
- **UI Labels/Headers/Chips:** JetBrains Mono, uppercase, letter-spacing 0.05–0.1em, muted color — feels like a terminal log, not a product label
- **Code:** JetBrains Mono (already the primary)
- **Loading:** Google Fonts — `https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap`
- **Scale:**
  - xs: 10px / 1.4 (chips, micro-labels)
  - sm: 11px / 1.5 (nav labels, secondary meta)
  - base: 13px / 1.7 (body, descriptions)
  - md: 14px / 1.5 (row titles, primary list text)
  - lg: 20px / 1.3 (detail panel titles)
  - xl: 22–32px / 1 (hero data, counts)

## Color
- **Approach:** Restrained but semantically precise. Color is signal, not decoration.

### Core Palette
```
--bg:           #0A0E1A   /* dark navy — main background */
--bg-panel:     #0D1117   /* panels, nav, sidebar */
--bg-row:       #111827   /* elevated surfaces, cards */
--bg-row-sel:   #0F1F35   /* selected row, active state */
--border:       #1E2A3A   /* all dividers and borders */
```

### Accent System
```
--cyan:         #00D4FF   /* primary interactive: company names, chips (matched), links */
--cyan-dim:     rgba(0, 212, 255, 0.6)   /* secondary cyan: reviewed counts, muted interactives */
--cyan-bg:      rgba(0, 212, 255, 0.08)  /* chip backgrounds for matched keywords */
--cyan-border:  rgba(0, 212, 255, 0.25)  /* chip borders, badge borders */
```

### Semantic Colors
```
--green:        #00D9A3   /* approve, met requirement, strong fit band, Approve button */
--amber:        #F59E0B   /* partial match, partial fit band, consider */
--red:          #E05C5C   /* skip, missing skill, stretch fit band, Skip button */
```

### Text Scale
```
--text:         #FFFFFF   /* primary text: titles, scores, key data */
--text-sec:     #8B9CB0   /* secondary: descriptions, meta, salary, location */
--text-muted:   #4B5563   /* muted: labels, dividers, inactive states */
```

### Dark Mode Strategy
This is a dark-mode-only tool. There is no light mode. The dark palette IS the identity.

### Fit Band Color Logic
The numeric match score is internal and is never rendered. It maps to one of
three bands, and the band is always accompanied by a reason sentence.

- `strong fit`: `--green` (#00D9A3)
- `partial fit`: `--amber` (#F59E0B)
- `stretch`: `--red` (#E05C5C)

A band shown without its reason sentence is a bug. When no job description was
captured, the band renders in `--text-sec` with reduced-confidence wording
rather than a colour that implies a verified skill match.

### Keyword Chip Color Logic
- `chip-match` (keyword found in profile): cyan border + cyan text on `--cyan-bg`
- `chip-partial` (related/adjacent skill): amber border + amber text on amber-bg
- `chip-missing` (skill gap): `--border` + `--text-sec` on minimal bg

## Spacing
- **Base unit:** 8px
- **Density:** Comfortable-dense (this is a daily-use review tool; compact but not claustrophobic)
- **Scale:**
  - 2xs: 2px
  - xs: 4px
  - sm: 8px
  - md: 12–14px (row padding)
  - lg: 16px (panel padding)
  - xl: 20–24px (section gaps)
  - 2xl: 32px (major section breaks)
- **Row padding:** 14px 16px (vertical / horizontal)
- **Panel padding:** 16px 20px

## Layout
- **Approach:** Grid-disciplined, left/right split
- **Primary split:** ~52% left (job list queue) / ~48% right (detail panel)
- **Min widths:** list panel min-width 420px; detail panel flex-grows to fill
- **Top nav:** 48px fixed height
- **Filter bar:** 36px, toggles on Filter button click
- **Max content width:** Full viewport (this is a full-screen tool, not a constrained-width content site)
- **Border radius:**
  - xs: 3px (chips, badges, fit band pills)
  - sm: 4px (buttons, inputs, small controls)
  - md: 5px (primary action buttons)
  - none: rows, panels (no rounding on structural containers)
- **Responsive breakpoint:** At ≤ 900px, hide detail panel and show list full-width

## Motion
- **Approach:** Minimal-functional
- **Easing:** ease-out for enter, ease-in for exit, ease-in-out for state transitions
- **Duration:**
  - micro (hover states): 120–150ms
  - short (row selection, button press): 150ms
  - medium (panel transitions): not used — snappy switching preferred
- **Reduced motion:** Always honor `prefers-reduced-motion: reduce` — zero transitions when set

## Components

### Fit Band
Replaces the old score bar and score number. A small pill plus a reason line.

- **Pill:** JetBrains Mono, 10px, uppercase, `letter-spacing: 0.05em`, `padding: 2px 8px`, `border-radius: 3px`. Band colour at 15% opacity background, 35% border, full-strength text. Label is one of `strong fit`, `partial fit`, `stretch`.
- **Reason line:** Inter, 13px / 1.7, `--text-sec`, directly beneath the pill. One sentence, composed from matched evidence — named skills, seniority band, penalties that fired, location/work-mode fit.
- **No bar, no percentage, no number.** Length of the reason is the only visual weight.
- **Reduced confidence:** when no job description was captured, the pill uses `--text-muted` border and `--text-sec` text, and the reason states that the listing had no description.

### Keyword Chip
JetBrains Mono, 10px, `letter-spacing: 0.03em`, `padding: 2px 7px`, `border-radius: 3px`, border 1px. Three types: match (cyan), partial (amber), missing (muted).

### Action Buttons (row-level)
Small, `font-family: mono`, 11px, semibold, `padding: 5px 12px`, `border-radius: 4px`. Approve: green bg at 15% opacity, green border at 35% opacity, green text. Skip: red equivalent.

### Primary Action Buttons (detail panel)
Approve & Apply: solid `--green` background, dark text `#0A0E1A`, 8px 18px padding, 5px radius, 12px mono bold. Skip: semi-transparent surface, `--text-sec`, border `--border`.

### Nav Badge
JetBrains Mono, 11px, semibold, `--cyan` text, cyan bg at 15%, cyan border at 25%, `padding: 2px 8px`, `border-radius: 10px`.

### Date Filter Bar
Cyan-tinted background (`rgba(0, 212, 255, 0.04)`), 36px height. Filter buttons: mono 11px, transparent border, toggle active state to cyan bg + cyan border + cyan text.

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-05-28 | Initial design system created | Formalized from /design-shotgun Variant A approval. Memorable thing: "my personal intelligence layer". |
| 2026-05-28 | Cyan `#00D4FF` as primary interactive | Not blue, not indigo — cyan reads as "system intelligence actively working for you". Differentiates from generic analytics SaaS. |
| 2026-05-28 | JetBrains Mono for ALL non-body text | Reinforces terminal/intelligence aesthetic vs. standard dashboard feel. Makes every data point feel intentional. |
| 2026-05-28 | Dark mode only | Daily AM review tool. Reduces eye strain. Dark IS the identity, not a preference toggle. |
| 2026-05-28 | Semantic color = semantic meaning | Cyan/green/amber/red carry fixed meanings (interactive/approve/consider/skip) everywhere. Color is signal, not decoration. |
| 2026-05-28 | Matched keyword chips stay cyan even on skipped jobs | User should always understand the score, even when passing. Cognitive transparency. |
| 2026-08-09 | Repositioned from solo personal tool to multi-user product | Ghazal remains a user but is no longer the only one. Anything tuned to one person (keyword weights) becomes per-user data. |
| 2026-08-09 | Match score is internal; UI shows a fit band + reason sentence | A bare number invites false precision and cannot be argued with. The band gives scannable ordering; the sentence carries the evidence. Replaces the score bar and score number entirely. |
| 2026-08-09 | Reason sentences are composed from scorer evidence, not written by the LLM | The LLM may phrase the sentence but must not invent the facts. Prevents plausible-sounding fiction in the one place the user places trust. |
