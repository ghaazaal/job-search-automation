# Design System — Job Search Automation (JobBot)

## Product Context
- **What this is:** A personal job search automation tool for an Analytics/Data Engineer. Scrapes, scores, and presents shortlisted jobs for daily review, then generates tailored resumes and cover letters for approved roles.
- **Who it's for:** Ghazal — solo user, daily AM review session, Windows 11 desktop.
- **Space/industry:** Personal tooling / job search / data analytics workflow
- **Project type:** Web app / internal tool (personal use, not SaaS)
- **Memorable thing:** "My personal intelligence layer" — every design decision should reinforce the feeling that this tool knows what matters and filters the noise. It surfaces signal, not volume.

## Aesthetic Direction
- **Direction:** Industrial/Utilitarian with personal warmth — data-forward, not cold.
- **Decoration level:** Minimal. Data density earns the real estate. Color carries semantic meaning.
- **Mood:** Serious tooling that happens to care about the user. Like a Bloomberg Terminal built for one person. Not generic SaaS. The user should feel like they're running an intelligence operation, not filling out a job board.
- **Reference:** Approved Variant A mockup at `~/.gstack/projects/JobSearchautomation/designs/job-review-dashboard-20260528/variant-A.png`

## Typography
- **Display/Hero/Scores:** JetBrains Mono — every number feels intentional; terminal precision
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
  - xl: 22–32px / 1 (score numbers, hero data)

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
--cyan:         #00D4FF   /* primary interactive: company names, score numbers, chips (matched), links */
--cyan-dim:     rgba(0, 212, 255, 0.6)   /* secondary cyan: reviewed counts, muted interactives */
--cyan-bg:      rgba(0, 212, 255, 0.08)  /* chip backgrounds for matched keywords */
--cyan-border:  rgba(0, 212, 255, 0.25)  /* chip borders, badge borders */
```

### Semantic Colors
```
--green:        #00D9A3   /* approve, met requirement, high score (75+), Approve button */
--amber:        #F59E0B   /* partial match, medium score (60–74), consider */
--red:          #E05C5C   /* skip, missing skill, low score (<60), Skip button */
```

### Text Scale
```
--text:         #FFFFFF   /* primary text: titles, scores, key data */
--text-sec:     #8B9CB0   /* secondary: descriptions, meta, salary, location */
--text-muted:   #4B5563   /* muted: labels, dividers, inactive states */
```

### Dark Mode Strategy
This is a dark-mode-only tool. There is no light mode. The dark palette IS the identity.

### Score Color Logic
- Score ≥ 75: `--green` (#00D9A3)
- Score 60–74: `--amber` (#F59E0B)
- Score < 60: `--red` (#E05C5C)

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
  - xs: 3px (chips, badges, score bars)
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

### Score Bar
Horizontal track, 4–6px height, `--border` background, color-coded fill, `border-radius: 2px`. Width = score percentage.

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
