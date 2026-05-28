# Claude Cowork Job Search Automation Guide

> Transform your job search with AI-powered automation that finds, evaluates, and prepares applications while you sleep

*Developed by Claude Code, Updated last on 5/24 by [Maryam R](https://www.linkedin.com/in/maryamrezapoor/)*

---

## What You Need

- **Paid Claude Plan** — Pro, Max, Team, or Enterprise
- **Claude Desktop** — macOS or Windows
- **Data Connectors** — Indeed + Apify installed

> **Critical:** Your computer must stay awake and Claude Desktop must be open when scheduled tasks run. If your machine sleeps, tasks will skip and run at next opportunity.

---

## Step 0 — Install Connectors

*Set up your data sources first*

### Indeed Connector

1. Open Claude Desktop
2. Go to Customize → Connectors
3. Find "Indeed" and click Install
4. Follow the setup instructions

**What you get:** No API key needed. Gives you live job search, salary data, company reviews.

### Apify Connector

1. Sign up for free at [apify.com](https://apify.com)
2. Get your API key from Account → Settings
3. In Claude Desktop: Customize → Connectors → Apify
4. Enter your API key

**Why Apify:** Free tier gives 1000 monthly operations. Scrapes company career pages, LinkedIn company data, and other job sites Indeed doesn't cover.

---

## Step 1 — Create Your Cowork Project

*Set up your automation workspace*

### Create Your Cowork Project First

1. Open Claude Desktop
2. Click "Cowork" tab in left sidebar
3. Under "Projects", click "Create new project"
4. Name it: **Job Search Automation**
5. Location: Choose a folder you'll remember
6. Click "Create"

**Why create project first:** Projects give Claude persistent memory and file access. Your job criteria and automation prompts will be saved here for daily use.

### Add Your Resume to the Project Folder

1. Find your project folder (Claude shows the path when you create it)
2. Drop your resume file into this folder
3. Back in Claude, ask: *"Can you access the resume in the project folder? If yes, return name"*

**File Format Options:**
- **PDF** — Best for formatting preservation, works perfectly with Claude
- **Word (.docx)** — Also works well, Claude reads all text content
- **Text (.txt)** — Simplest, fastest processing

**Resume-Based Benefits:** Instead of answering 15+ questions about your preferences, Claude reads your resume and asks only 5–7 targeted questions about criteria that aren't obvious from your background. Much faster setup.

---

## Step 2 — Define Your Job Criteria

*Let Claude create your personalized criteria*

In your "Job Search Automation" project, copy this prompt:

```
I want to create detailed job search criteria. Please:

1. Read my resume from the project folder
2. Ask me 5-7 targeted questions about preferences not clear from my resume
   (salary range, location preferences, company size, industry focus, etc.)
3. Create a comprehensive job criteria document covering:
   - Target roles and seniority levels
   - Compensation expectations
   - Location/remote preferences
   - Industry and company size preferences
   - Must-have vs nice-to-have skills
   - Deal-breakers
   - Cultural fit factors

4. Save the result as "job-criteria.md" in this project folder

Keep questions concise and avoid asking about things obvious from my background.
```

**Why this approach:** Claude analyzes your experience and only asks about non-obvious preferences, making the setup much faster than traditional questionnaires.

---

## Step 3 — Build Your Scoring Rubric

*Create weighted evaluation framework*

In your "Job Search Automation" project, copy this prompt:

```
Based on the job criteria we just created, please build a scoring rubric that:

1. Reviews the job-criteria.md file
2. Creates weighted scoring categories
   (compensation, growth, culture fit, technical match, etc.)
3. Defines 1-10 scoring for each category with specific criteria
4. Shows how to calculate final scores
5. Includes deal-breaker flags that auto-reject regardless of score

Save as "scoring-rubric.md" in this project folder.

Make it detailed enough that the scoring is consistent and objective.
```

---

## Step 4 — Create the Automation Prompt

*Build your daily job search workflow*

In your "Job Search Automation" project, use this automation prompt:

```
Please run my daily job search automation:

1. Read job-criteria.md and scoring-rubric.md from this project folder
2. Search for new jobs using Indeed connector based on my criteria
3. For each job found:
   - Extract key details (role, company, salary, requirements, etc.)
   - Research the company using available data
   - Score against my rubric (1-10 scale)
   - Flag any deal-breakers
4. Create ranked shortlist of top opportunities (score 7+)
5. For top 3 jobs, draft personalized cover letter outlines using my resume
6. Save results as "daily-results-[DATE].md" in this project

Focus on quality over quantity. I'd rather see 5 great matches than 50 mediocre ones.
```

> **Test First:** Run this prompt manually in a regular Cowork session before scheduling. Adjust until you're happy with results.

**Token Optimization:** These prompts are designed to be concise and token-efficient. This reduces costs and speeds up daily automation runs while maintaining full functionality.

---

## Step 5 — Schedule Daily Automation

*Set up recurring job search*

### Create Scheduled Task

1. Stay in your "Job Search Automation" project
2. Type `/schedule` or click "Scheduled" in sidebar
3. Click "Create new scheduled task"
4. Paste your tested prompt from Step 4
5. Set schedule (see recommendations below)

**Important:** Creating the scheduled task within your project ensures it has access to your job criteria and scoring rubric files.

### Choose Your Schedule

| Schedule | Best For | Benefit |
|----------|----------|---------|
| 7:00 AM Weekdays | Active job seeker | Results ready before work starts |
| Sunday 8:00 PM | Casual job seeker | Weekly batch approach |

---

## Step 6 — Your Daily Workflow

*How to process your automated results*

### Every Morning (or weekly):

1. Check your project folder for new `daily-results` file
2. Review the ranked job list (focus on scores 7+)
3. Use the provided cover letter outlines for top matches
4. Apply to 2–3 best opportunities that day
5. Update your criteria if you notice patterns in what you like/dislike

**The Real Advantage:** You spend energy on relationships and tailoring applications, not searching. Most people waste time scrolling — you focus on the right opportunities.

---

## Further Elevate Your Job Search Experience

*Advanced features to maximize your automated job search effectiveness*

### Mobile Notifications
- Get shortlist sent as text message to your phone
- Slack/Discord notifications with job summaries
- Email with formatted job cards and quick apply links

*Uses: Zapier connector + notification services*

### Networking Opportunity Discovery
- Find mutual connections at target companies
- Identify alumni from your school/previous companies
- Suggest warm introduction paths through your network

*Uses: LinkedIn connector + contact analysis*

### Interview Prep Automation
- Generate company-specific interview questions
- Create talking points about company challenges
- Prepare STAR method examples for role requirements

*Uses: Company research + role analysis prompts*

### Application Tracking Dashboard
- Track application status and response rates
- Analyze which criteria lead to interviews
- Optimize scoring rubric based on outcomes

*Uses: Spreadsheet connector + data analysis*

### Follow-up Automation
- Schedule reminder to follow up after applications
- Generate personalized follow-up email templates
- Track optimal timing for follow-up messages

*Uses: Calendar connector + email templates*

> **Implementation Tip:** Start with the basic automation first, then gradually add these advanced features one at a time. Each can be built as a separate scheduled task or integrated into your main workflow.

---

## Troubleshooting

### Connectors Not Working
- Fully quit and reopen Claude Desktop (don't just close)
- Check Settings → Integrations for status
- For Apify: verify your API key has available credits
- Test connectors manually before scheduling

### Scheduled Tasks Not Running
- Computer must stay awake during scheduled time
- Claude Desktop must remain open
- Check if you have sufficient token credits
- Review task history for error messages

### Poor Results
- Refine your job criteria to be more specific
- Adjust scoring rubric weights
- Add more deal-breakers to filter out irrelevant jobs
- Test with different search terms

---

*Built to visualize the Claude Cowork job search automation guide*
