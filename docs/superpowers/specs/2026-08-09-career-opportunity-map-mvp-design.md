# Career Opportunity Map MVP Design

## Goal

Help an actively job-seeking data professional identify and act on the strongest path toward a role: a relevant company, a live opportunity or watch signal, and the people who can provide useful context.

## Target user

An Analytics Engineer, Data Engineer, Data Analyst, or Product Analyst who is actively seeking a role and wants a focused daily plan rather than a large, undifferentiated job list.

This is a multi-user product. The author is also a user, but nothing may assume a single candidate — anything tuned to one person, keyword weights above all, is per-user data.

## Product promise

After uploading a resume and confirming search preferences, the user sees a small set of explainable opportunity maps. Each map answers:

1. Why is this company relevant?
2. Is there a role to act on now?
3. If so, why does the role fit?
4. Which people or role types are relevant to research, and why?
5. What is the next action?

## Primary user journey

1. The user uploads a PDF resume.
2. The product extracts and proposes target roles; the user confirms or edits them.
3. The user selects one or more locations and a work preference: remote, hybrid, onsite, or any.
4. The product discovers relevant jobs and derives companies from those jobs.
5. The home screen shows opportunity maps in two states:
   - **Act now:** company → relevant open role → relevant people/role types → review and apply.
   - **Build access:** company → no matching role or a hiring signal → watch company and research relevant people/role types.
6. The user can review a role, apply through the original listing, save or remove a company from their watchlist, and open a pre-filled research search for a relevant person or role type.

## Opportunity map

```text
Career goal
  → Company
    → Open role or watch signal
      → People in context
        → Next action
```

The map must never recommend a company, role, or person/role type without visible evidence explaining why it relates to the user's goal.

## Phase 1 scope

Phase 1 contains three features that do not depend on each other. Ship them in
sequence so each is testable on its own, rather than gating everything behind
one release:

1. **The map** — company entity, `ACT_NOW`/`WATCH`/`DISCOVER`, ranking, evidence.
   Runs on data the existing pipeline already produces. Single user is fine here.
2. **Multi-user shell** — resume upload, role confirmation, location and work
   mode, per-user storage and per-user keyword weights.
3. **People in context** — only after the map has real use. It introduces a new
   entity and screen section to produce a public search query, which is the
   least proven part of the product.

Acceptance criteria below are grouped by which of the three they belong to.

### Candidate profile

- Canonical resume PDF and extracted text.
- Confirmed target job titles.
- Selected locations and work mode.

### Company intelligence

- Company name, website when available, source job URL, and careers-page URL when available.
- Company state: `ACT_NOW`, `WATCH`, or `DISCOVER`.
- Last checked timestamp and user watch status.
- Human-readable explanation of relevance based on the associated role, candidate skills, and location/work-mode compatibility.

### Role intelligence

- Relevant open roles with title, company, location, source URL, posting date, description, and salary when available.
- A fit band — `strong fit`, `partial fit`, or `stretch` — and a one-sentence reason. The underlying numeric score is internal and used only for ranking; it is never rendered.
- The reason sentence is composed from evidence the scorer actually matched: named skills, seniority band, penalties that fired, and work-mode/location fit. An LLM may phrase it but must not introduce facts the scorer did not produce.
- Existing resume-tailoring output remains available only after the user chooses to review a role.

### People in context

- For each opportunity map, recommend relevant role types: hiring manager/data leader, similar-role employee, and recruiter when the information is available.
- Explain the role type's relationship to the opportunity and the appropriate action: research team context, understand the role, or understand the application process.
- Phase 1 does not store private contact data, send messages, scrape authenticated social-network content, or automate outreach.
- The user may open a pre-filled public-web search for the company and recommended role type.

### Actions

- `Review role`
- `Apply` (opens the original listing)
- `Watch company`
- `Remove from watchlist`
- `Research people`
- `Hide recommendation`

## Explicit exclusions

- Automatic connection requests, messages, or email outreach.
- Application-form autofill or automatic submission.
- Personal-brand content generation.
- A full contact CRM.
- Industry, culture, funding, or deep company-intelligence scoring.
- Outcome-driven recommendation learning; capture only basic user actions for now.

## Data and recommendation rules

1. Jobs come from the existing Indeed and LinkedIn Apify integrations.
2. Duplicate jobs are collapsed with the existing URL and company/title fingerprint logic.
3. A job match uses the existing configurable scoring model. Location and work-mode checks do not exist yet and are net-new work, not an enhancement — the scrapers currently hardcode remote/worldwide and the scorer has no notion of either.
4. A company becomes `ACT_NOW` when it has at least one non-hidden, location-compatible role whose internal score meets the configured shortlist threshold.
5. A company becomes `WATCH` when the user explicitly watches it, or when it had a relevant role but no longer has one during a later check.
6. A company becomes `DISCOVER` when it is found from job data but does not yet meet the `ACT_NOW` threshold and the user has not watched it.
7. The home screen ranks `ACT_NOW` maps above `WATCH`, then `DISCOVER`; within each state, it sorts by evidence-backed relevance and recency.
8. Never render a numeric score. The user sees a fit band and a reason sentence; a band shown without its reason is a bug.
9. Do not present fabricated precision. `interview_chance` — a hardcoded lookup table rendered as a percentage — is removed and must not be reintroduced.
10. Scoring keyword weights are tuned per candidate, so they are per-user data, not a single committed config file.

## Initial data model

| Object | Required fields |
|---|---|
| CandidateProfile | resume path, target roles, locations, work mode |
| Company | id, name, website, careers URL, state, watch status, last checked |
| Job | id, company id, title, description, location, source URL, posting date, internal score, fit band, reason sentence, matched evidence |
| OpportunityMap | candidate id, company id, optional job id, state, explanation, next action |
| PersonResearchHint | opportunity-map id, role type, relationship explanation, public-search query |
| UserAction | entity type, entity id, action, recorded timestamp |

## Screens

### Onboarding

Resume upload, extracted target roles for confirmation, location input, and work-mode selection.

### Opportunity Map home

Displays a compact ranked list of company-centered maps. Each map shows the user's goal, company, state, open role or watch signal, people-in-context hints, evidence, and one primary next action.

### Role detail

Shows the job description, fit band with its reason sentence, risk signals, source link, and application/tailoring actions.

### Company detail

Shows company state, current relevant roles, watch status, last checked time, and people-in-context research hints.

## Error handling and trust

- If a source fails, show the recommendation's last successful check time and do not imply a current opening was confirmed.
- If there is no job description, show reduced-confidence wording and do not claim a skill-level match.
- If a careers-page URL is unavailable, allow the user to watch the company based on the job-source record and clearly label the monitoring source.
- Never claim a specific person is associated with a role unless the source supports that claim; otherwise present a role type and public research query.

## Success metrics

Track for a private beta:

- onboarding completion rate;
- percentage of users who review an opportunity map;
- percentage who apply through an `ACT_NOW` map;
- percentage who watch a company;
- percentage who use a people-research action;
- weekly return rate;
- recommendation hide rate;
- qualitative trust feedback: whether users can explain why a recommendation appeared.

## Acceptance criteria

**Ship 1 — the map**

1. The product can generate an opportunity map from at least one successfully scraped job.
2. An `ACT_NOW` map shows a source-linked job, a fit band with its reason sentence, and an apply action.
3. No numeric score appears anywhere in the interface.
4. A role with no captured job description shows reduced-confidence wording and does not claim a skill-level match.
5. A user can watch a company and later see its last checked time and any newly found relevant role.
6. A user can hide an unwanted recommendation.
7. Automated tests cover band assignment, reason composition, state assignment, ranking, company watch behaviour, and missing-source-data fallbacks.

**Ship 2 — multi-user shell**

8. A user can complete onboarding with a resume, target roles, location, and work mode.
9. Two users with different resumes receive different bands for the same job.
10. Location and work-mode preferences visibly change which roles appear.

**Ship 3 — people in context**

11. A people-in-context hint contains a role type, relationship explanation, and a public-search action without storing contact details.
