# Market learning path — design (as built)

**Ask (2026-10-14, refined the same morning):** analyse all scraped postings
together for the most in-demand skills, emerging trends and requirements
across relevant roles; compare with the user's resume and skills; produce
ONE personalised learning path ranked by market demand, relevance to the
user's background and employability impact. Not one path per role.

## Rule the feature is built around

Every fact traces back to text that exists. Claude interprets; code
verifies.

| Claim | Evidence required | If missing |
|---|---|---|
| A posting asks for skill X | A quote from that posting (letters and digits must appear, in order, in the posting) | Skill dropped, counted as "unverified" |
| You have X / X builds on Y | Your confirmed skill list, a word-bounded match in the resume text, or a quote from the resume | Treated as missing |
| X is in the path | X is in the ranked gap list | Cut from the stage |
| Numbers on the page | Counts of stored postings | Never a model's number, never the internal score |

## Pipeline (`src/skills/`)

1. **extract** — Claude reads each live posting (relevance-kept, description
   captured) once, in batches of 5, and lists skills with category,
   required/preferred and a quote. Stored in `posting_skill`; every read
   posting gets a `skill_extraction` row (even with zero skills) so it is
   never re-read. A posting Claude's answer skipped stays unread. Three
   failures with nothing read stop the run and surface the API error.
2. **market** — spellings merged (case/punctuation), then Claude groups
   synonyms, restricted to names the postings produced. Counts postings
   (not mentions) per skill, per role family (`vocabulary.yaml:
   role_families`), and trends: postings in the last 28 days vs before,
   only with ≥60 postings each side, ≥8 mentions, a ≥3-point shift and a
   1.5× ratio. Otherwise the page says why there are no trends.
3. **compare** — all active resumes read as one person. Exact pass first;
   Claude reviews the 40 most-demanded unplaced non-soft skills and must
   quote the resume for "have"/"builds on".
4. **rank** — gaps exclude soft skills and skills you have. Internal score:
   0.5 demand (required 1, preferred 0.5) + 0.3 near misses (postings where
   the skill is one of at most two missing requirements) + 0.2 builds on
   your background. Shown as reasons: "Named in N of M postings (K as a
   requirement). One of your last 2 missing requirements in J postings.
   Builds on Y. Rising: …". Coverage before/after the path is computed the
   same way.
5. **path** — Claude orders the top 12 gaps into 3–6 stages (goal, why now,
   topics, a project using existing skills, how to show it, rough effort).
   Validated: unknown skills cut, every gap placed or listed as left out,
   links stripped.

## Defaults picked (the ask left these open)

- **Models:** reading postings and grouping names use
  `learning_path.read_model` (default `claude-sonnet-5-5`); comparing with
  the resume and writing the path use `learning_path.model` (default
  `claude-opus-5-5`, server-side refusal fallback on). Reading is ~95% of
  the tokens. The user asked to cut the first-run cost but keep Sonnet or
  Opus (2026-10-14), so a read of 50+ unread postings goes through the
  Message Batches API (half price, minutes to an hour; no refusal fallback
  there, a declined request just stays unread) and quotes are capped at 12
  words. Quote verification means a cheaper reader risks missed skills,
  not invented ones. Estimated first full read of 1,085 postings: Sonnet +
  batch ~$4-5, Opus + batch ~$9-10, Haiku ~$0.50 (estimates from character
  counts, not measured).
  Residual: an app restart while a batch is waiting discards that batch's
  results (already paid for); the next analysis resubmits. Run the first
  big read from the command line to avoid it.
- **Window:** only postings from the past `learning_path.days` days (default
  30; 0 = everything stored), dated by posted date, else the day a run first
  saw them. The user asked for the past month (2026-10-14): 331 of 1,085
  stored postings. Older postings are neither read nor counted, and the
  trend split becomes the window's halves (last 15 days vs the 15 before).
- **Path format:** stages in the app's LEARN tab (paper shell), not a file.
- **Soft skills:** shown in the market list, not planned.
- **Several resumes:** merged; one path per person.

## Surfaces

- `GET /learn` — the path, the market table with quotes, role families,
  trends, and a "how this was built" note with dropped/unread counts.
- `POST /api/learning-path` (background thread), `GET /api/learning-path/<id>`
  (poll). Boot recovery fails a RUNNING analysis; read postings are kept.
- `python main.py --learning-path [--limit N]`.
- Schema v11: `skill_extraction`, `posting_skill`, `learning_path` (new
  tables only, no ALTERs).

## Not verified yet

No Anthropic key was available on the build machine, so the live path was
exercised only with a fake model (33 tests, grounding checks
mutation-tested). The first real run should start small:
`python main.py --learning-path --limit 25`.
