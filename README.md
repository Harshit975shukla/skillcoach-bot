# SkillCoach Bot

A personal Cloud DevOps interview coaching system delivered entirely through Telegram. It sends a structured daily lesson at 9 AM, an evening quiz at 6 PM, a weekend mock test, and a Sunday weekly review — all automated via GitHub Actions.

---

## Project Structure

```
skillcoach-bot/
├── morning_lesson.py      # 9 AM Mon-Fri: lesson + concept videos + architecture video
├── evening_quiz.py        # 6 PM Mon-Fri: 5-question MCQ quiz on today's topic
├── weekend_test.py        # 10 AM Saturday: 10-question full mock test
├── sunday_plan.py         # 10 AM Sunday: week review + next week plan
├── lesson_content.py      # Pre-written lessons for EC2, S3, RDS, VPC, IAM, Lambda
├── reminder.py            # Sends /publish reminder if bot hasn't run
├── bot.py                 # Standalone Telegram polling bot (local use)
├── api/
│   └── webhook.py         # Vercel serverless handler for /ask, /mock, /interview etc.
├── .github/
│   └── workflows/
│       ├── morning_lesson.yml
│       ├── evening_quiz.yml
│       └── weekend.yml
├── requirements.txt
├── vercel.json
└── .env.example
```

> **Dashboard repo** (separate): `Harshit975shukla/skillcoach-dashboard` — GitHub Pages static site at `https://harshit975shukla.github.io/skillcoach-dashboard`

---

## How It Works

### Daily Schedule (IST)

| Time | Script | What it does |
|------|--------|--------------|
| 9 AM Mon–Fri | `morning_lesson.py` | Full lesson: header, 4 concepts each with an animated diagram video, end-to-end flow, architecture video, tasks, key terms, interview Q&A |
| 6 PM Mon–Fri | `evening_quiz.py` | 5 MCQ questions on today's morning topic; answers graded inline via `/q` |
| 10 AM Saturday | `weekend_test.py` | 10-question mock test covering the full week's topics |
| 10 AM Sunday | `sunday_plan.py` | Week score review + generates next week's 6-day learning plan |

### Morning Lesson Flow

```
data.json (GitHub) → look up today's topic from week_plan
    ↓
Pre-written lesson? (EC2/S3/RDS/VPC/IAM/Lambda)
    YES → lesson_content.py (zero API calls for core content)
    NO  → Groq API → Gemini fallback
    ↓
Send to Telegram:
  1. Greeting + Why + What
  2. Concept 1 text → animated MP4 (Ken Burns zoom via ffmpeg)
  3. Concept 2 text → animated MP4
  4. Concept 3 text → animated MP4
  5. Concept 4 text → animated MP4
  6. End-to-end flow
  7. Full architecture animated MP4
  8. Tasks + Key Terms
  9. Interview Q&A (1 small Groq call ~500 tokens)
 10. Resources footer
    ↓
Push updated data.json (marks topic as covered today)
```

### Diagram Animation

Each Mermaid diagram is converted to a 25-second animated MP4:
- Image downloaded from `mermaid.ink`
- `ffmpeg` applies **Ken Burns zoom** (1.0x → 1.25x, center-anchored)
- 1s fade in, 2s fade out
- Concept name caption overlay (white text, black box, bottom-centered)
- Output: H.264 1280×720 @ 24fps, ~4–8 MB
- Fallback: sends static image if ffmpeg fails

### AI Stack

```
Groq API (primary)   → openai/gpt-oss-120b — 14,400 RPD free
Gemini API (fallback) → gemini-3.6-flash    — 1,500 RPD free

Combined: ~15,900 requests/day
```

The `ai(prompt, max_tokens)` function tries Groq first, falls back to Gemini automatically.

---

## Telegram Bot Commands

Handled by `api/webhook.py` (Vercel serverless):

| Command | What it does |
|---------|-------------|
| `/ask <question>` | Answers any Cloud DevOps question |
| `/mock <topic>` | Sends a random interview question + model answer |
| `/interview` | Full mock interview: question → you answer → AI grades it |
| `/learn <topic>` | On-demand lesson for any topic |
| `/resume` | Pastes your resume for scoring + improvement tips |
| `/profile` | Set up your target role, current level, and skills |
| `/q A/B/C/D` | Answer the current quiz question |
| `/publish` | Force-publishes dashboard data |
| `/nextweek <preference>` | Customise next week's learning plan |
| `/pause` / `/resume` | Pause or resume daily reminders |

---

## Dashboard

Static GitHub Pages site reading `data.json`:

**URL:** `https://harshit975shukla.github.io/skillcoach-dashboard`

**Sections:**
- Profile strip (name, role, level, reminder time, status)
- Metric cards: completed tasks, streak, open tasks, practice time, mock answers, resume score
- 30-day activity heatmap
- Skill breakdown bars (animated fill)
- Open tasks + recently completed
- Mock interview history with scores
- Resume review panel

**Lottie animations:**
- Fire glow on streak card (when streak > 0)
- Green pulse on completed card
- Blue bouncing dots on loading state

---

## Environment Variables

Set as GitHub Actions secrets and Vercel environment variables:

| Variable | Used in | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | All scripts | Bot token from @BotFather |
| `CHAT_ID` | All scripts | Your personal Telegram chat ID |
| `GITHUB_TOKEN` | All scripts | PAT with `repo` scope for reading/writing `data.json` |
| `GROQ_API_KEY` | All scripts | Groq free tier API key |
| `GEMINI_API_KEY` | All scripts | Google Gemini API key |

---

## GitHub Actions Workflows

All three workflows pass both API keys:

```yaml
env:
  TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
  CHAT_ID: ${{ secrets.CHAT_ID }}
  GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
  GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
```

`ubuntu-latest` runners include `ffmpeg` pre-installed — no extra install step needed.

---

## Pre-written Lesson Topics

`lesson_content.py` contains fully authored lessons (zero API cost) for:

| Topic | Concepts covered |
|-------|-----------------|
| EC2 | Instance types, AMIs & launch, Auto Scaling, EBS & storage |
| S3 | Buckets & objects, storage classes, security & access, advanced features |
| RDS | Managed databases, Multi-AZ, Read Replicas, performance & cost |
| VPC | Subnets & CIDR, Internet & NAT gateways, security groups & NACLs, VPC peering |
| IAM | Users groups roles, policies, security best practices, cross-account |
| Lambda | Functions & triggers, execution model, integrations, cold starts |

For all other topics (Kubernetes, Terraform, Docker, CI/CD, Prometheus, GenAI), lessons are generated by the AI stack.

---

## Local Setup

```bash
# Clone
git clone https://github.com/Harshit975shukla/skillcoach-bot
cd skillcoach-bot

# Install deps
pip install -r requirements.txt

# Copy env
cp .env.example .env
# Fill in TELEGRAM_BOT_TOKEN, CHAT_ID, GITHUB_TOKEN, GROQ_API_KEY, GEMINI_API_KEY

# Run bot locally (polling mode)
python bot.py

# Test morning lesson manually
python morning_lesson.py
```

---

## Tech Stack

- **Python 3.11** — all scripts
- **GitHub Actions** — scheduling (cron) and workflow_dispatch triggers
- **Vercel** — serverless webhook handler (`api/webhook.py`)
- **Telegram Bot API** — messaging, photo, and video delivery
- **mermaid.ink** — Mermaid diagram rendering to JPEG
- **ffmpeg** — Ken Burns zoom animation, MP4 encoding
- **Groq API** — primary LLM (openai/gpt-oss-120b)
- **Gemini API** — fallback LLM (gemini-3.6-flash)
- **GitHub Pages** — static dashboard hosting
- **Lottie Web** — dashboard animations
