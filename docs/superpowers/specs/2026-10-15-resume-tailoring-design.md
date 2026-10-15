# Resume tailoring: one master, cut per posting

Asked 2026-10-15: "a feature tailoring the resume. Also we need to create a
master resume and tailor it for different job positions."

## Shape

- **Master resume** — one per user (`master_resume`), stored as the Markdown
  the user edits on the RESUME tab. Grammar in `src/tailor/document.py`:
  `# name`, header lines, `## section`, paragraphs, `### entry` + meta lines,
  `- bullets`. Built by one Claude call (`build_master`) from every uploaded
  resume plus any extra PDFs added at build time (older CVs, a LinkedIn
  export). Extra PDFs are read for the master only and never become a
  `resume` row, so they cannot change what the search looks for.
- **Tailored resume** — one Claude call per posting (`tailor`), triggered
  from TAILOR RESUME in the shared role drawer (map and tracker) or the
  RESUME tab's list. Stored in `tailored_resume` with the master text it was
  cut from. Output: an in-app page, a `.md` download, and a print view for
  the browser's Save as PDF.

## Grounding (the hard rule)

Tailoring may reorder, drop, reword and merge; it may not add. The prompt
says so, and `src/tailor/grounding.py` checks without trusting the prompt:

- Every bullet cites master ids, and only from its own entry. A bullet that
  cites nothing valid is dropped.
- A rewritten line passes only when every number, every known skill/tool
  (vocabulary `market_tools` + `skill_names` + the user's resume skills),
  every email/link and every proper-noun-looking word in it is in its
  sources (its entry's bullets; for the summary, the whole master).
- A failing line reverts to the master's own words, and the page lists it.
- Header lines are chosen by id, never written; headings, companies, dates
  and education are copied by the program, never by the model.
- The same check runs on the master build against the source resumes: an
  unsupported line is left out and listed for the user to add by hand.

Known limit, stated on the page: a plain lower-case claim the master does
not make ("led the team") is not caught by the check, only by the prompt.

## Defaults chosen

| Fork | Default | Why |
|---|---|---|
| How the master is made | Claude merges uploaded resumes + optional extra PDFs, then the user edits | Builds on the stored resume text; the user stays the authority |
| Format | Markdown in-app, `.md` download, print → PDF | No new dependency; DOCX needs python-docx |
| Trigger | Role drawer button + RESUME tab | One drawer serves map and tracker |
| Model | `claude-opus-5-5`, effort medium (`resume_tailoring.model`) | Quality matters per application; cost is small |
| Schema version | Not bumped | New tables only; a bump collides with open branches |

## Measured (2026-10-15, live store)

- Master from 3 sources (12k chars): 59 s, $0.16, 1 line left out (a
  LinkedIn URL split across PDF lines; fixed after by comparing links
  without spaces).
- Tailoring Principal BI Engineer @ ABC Fitness: ~40 s, $0.11; 10 lines
  reworded, 18 kept, 0 reverted after two false-positive fixes ("1B+" read
  as a word; "Analytics/BI" joined forms).
