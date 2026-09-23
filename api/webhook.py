import json
import os
import base64
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from flask import Flask, request as flask_req

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GITHUB_REPO = "Harshit975shukla/skillcoach-dashboard"
GITHUB_FILE_PATH = "docs/data.json"
DASHBOARD_URL = "https://harshit975shukla.github.io/skillcoach-dashboard"
IST = timezone(timedelta(hours=5, minutes=30))
AUTHORIZED_CHAT_ID = int(os.environ.get("CHAT_ID") or "0")

COACH_PROFILE = """
Student: Harshit Shukla
Target role: Cloud DevOps & AI Engineer (Senior level)
Core skills: AWS, Kubernetes, Terraform, CI/CD, Python, GenAI/LLMOps, Observability
Interview focus: System design, cloud architecture, incident handling, AI/ML infrastructure
Current resume score: 85/100
"""


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _json_req(url, method="GET", data=None, headers=None):
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        url, data=body, method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode())


def send_msg(chat_id, text, parse_mode=None):
    payload = {"chat_id": chat_id, "text": text[:4000]}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        _json_req(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            method="POST", data=payload,
        )
    except Exception:
        pass


def _gh_headers():
    return {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}


def get_data():
    raw = _json_req(
        f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}",
        headers=_gh_headers(),
    )
    return json.loads(base64.b64decode(raw["content"]).decode()), raw["sha"]


def push_data(data, sha, message="Bot: progress update"):
    encoded = base64.b64encode(json.dumps(data, indent=2).encode()).decode()
    _json_req(
        f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}",
        method="PUT",
        data={"message": message, "content": encoded, "sha": sha},
        headers=_gh_headers(),
    )


# ── AI coaching engine ────────────────────────────────────────────────────────

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent"

def ask_gemini(prompt):
    if not GEMINI_API_KEY:
        return "AI coaching not set up yet. Add GEMINI_API_KEY in Vercel env vars."
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 700},
    }
    try:
        resp = _json_req(f"{GEMINI_URL}?key={GEMINI_API_KEY}", method="POST", data=body)
        return resp["candidates"][0]["content"]["parts"][0]["text"].strip()
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:300]
        return f"AI error {e.code}: {detail}"
    except Exception as e:
        return f"AI error: {e}"


def coach_answer(question):
    prompt = f"""You are SkillCoach, an expert interview mentor for Cloud DevOps and AI Engineering roles.

Student profile:
{COACH_PROFILE}

Question from student: {question}

Give a sharp, interview-ready answer. Include:
- Direct answer (2-3 sentences)
- Key points to mention in an interview
- One real-world example if relevant
- One follow-up tip

Keep total response under 400 words. Use plain text, no markdown symbols."""
    return ask_gemini(prompt)


def mock_question(topic):
    prompt = f"""You are a Senior Engineering interviewer at a top tech company.

Generate ONE tough interview question about: {topic}

Context: Candidate is targeting a Cloud DevOps / AI Engineer senior role.
{COACH_PROFILE}

Format your response EXACTLY like this:
QUESTION: [the interview question]

WHAT THEY LOOK FOR: [2-3 key things the interviewer wants to hear]

SAMPLE STRONG ANSWER: [a concise model answer, 150-200 words]

PRO TIP: [one tactical tip to stand out]

Use plain text, no markdown symbols."""
    return ask_gemini(prompt)


def learn_topic(topic):
    prompt = f"""You are SkillCoach preparing Harshit for a Cloud DevOps & AI Engineer interview.

Create a focused study guide for: {topic}

Include:
1. CORE CONCEPTS (top 5 things to know cold)
2. COMMON INTERVIEW QUESTIONS on this topic (3 questions)
3. HANDS-ON TASKS to practice (2 tasks)
4. KEY TERMS to use in answers

Keep it practical and interview-focused. Under 350 words. Plain text only."""
    return ask_gemini(prompt)


def resume_coach(aspect):
    prompt = f"""You are a resume expert for Cloud DevOps and AI Engineering roles.

Review request: {aspect}

Student profile:
{COACH_PROFILE}
Current resume score: 85/100
Known issues: Too long (1034 words), missing portfolio link, one oversized bullet

Give specific, actionable advice for improving this aspect of the resume.
Under 300 words. Plain text."""
    return ask_gemini(prompt)


# ── Command handlers ──────────────────────────────────────────────────────────

def process_command(chat_id, text):
    parts = text.strip().split(None, 1)
    cmd = parts[0].split("@")[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/start":
        send_msg(chat_id,
            "👋 SkillCoach Bot — your AI interview mentor!\n\n"
            f"🔑 Chat ID: {chat_id}\n\n"
            "COMMANDS:\n"
            "/tasks — Open tasks\n"
            "/skills — Skill progress\n"
            "/stats — Your stats\n"
            "/dashboard — Your tracker link\n\n"
            "AI COACHING:\n"
            "/ask <question> — Ask anything\n"
            "/mock <topic> — Mock interview question\n"
            "/learn <topic> — Study guide for a topic\n"
            "/tip — Get a coaching tip\n\n"
            "TRACKING:\n"
            "/complete task_001 — Mark task done\n"
            "/resume — Resume feedback\n"
            "/publish — Sync dashboard")

    elif cmd == "/help":
        send_msg(chat_id,
            "📖 All Commands\n\n"
            "--- COACHING ---\n"
            "/ask <question> — AI coaching on any topic\n"
            "/mock <topic> — Mock interview Q&A\n"
            "/learn <topic> — Study guide\n"
            "/tip — Daily interview tip\n\n"
            "--- TRACKING ---\n"
            "/tasks — Open tasks\n"
            "/today — Due today\n"
            "/skills — Progress bars\n"
            "/stats — Completion stats\n"
            "/streak — Current streak\n"
            "/complete <id> — Mark task done\n"
            "/resume — Resume feedback\n"
            "/dashboard — Tracker link\n"
            "/publish — Sync dashboard\n\n"
            "Topics: aws, kubernetes, terraform, cicd, genai, observability, python, cloud-design")

    elif cmd == "/dashboard":
        try:
            data, _ = get_data()
            s = data.get("statistics", {})
            send_msg(chat_id,
                f"📊 Your SkillCoach Dashboard\n\n"
                f"Link: {DASHBOARD_URL}\n\n"
                f"Quick stats:\n"
                f"Completed: {s.get('completed_tasks', 0)} tasks\n"
                f"Pending: {s.get('pending_tasks', s.get('total_tasks', 0))} tasks\n"
                f"Streak: {s.get('streak', 0)} days\n"
                f"Rate: {s.get('completion_rate', 0)}%")
        except Exception:
            send_msg(chat_id, f"📊 Dashboard: {DASHBOARD_URL}")

    elif cmd == "/ask":
        if not arg:
            send_msg(chat_id, "Usage: /ask <your question>\n\nExample:\n/ask How do I explain Kubernetes RBAC in an interview?\n/ask What is the difference between ECS and EKS?")
            return
        send_msg(chat_id, "🤔 Thinking...")
        answer = coach_answer(arg)
        send_msg(chat_id, f"🎓 SkillCoach Answer\n\n{answer}")

    elif cmd == "/mock":
        topic = arg or "Cloud DevOps"
        send_msg(chat_id, f"🎤 Generating mock interview question for: {topic}...")
        result = mock_question(topic)
        send_msg(chat_id, f"🎤 Mock Interview\n\n{result}")

    elif cmd == "/learn":
        if not arg:
            send_msg(chat_id,
                "Usage: /learn <topic>\n\n"
                "Available topics:\n"
                "aws, kubernetes, terraform, cicd, genai,\n"
                "observability, python, cloud-design, senior-behavioral")
            return
        send_msg(chat_id, f"📚 Building study guide for: {arg}...")
        guide = learn_topic(arg)
        send_msg(chat_id, f"📚 Study Guide: {arg.upper()}\n\n{guide}")

    elif cmd == "/tip":
        prompt = f"""Give Harshit one sharp, specific interview tip for a Cloud DevOps / AI Engineer role.
Make it something most candidates don't do. Under 150 words. Plain text."""
        tip = ask_gemini(prompt)
        send_msg(chat_id, f"💡 Today's Tip\n\n{tip}")

    elif cmd == "/tasks":
        try:
            data, _ = get_data()
            tasks = data.get("open_tasks", [])
            if not tasks:
                send_msg(chat_id, "✅ No open tasks — great job!\n\nDashboard: " + DASHBOARD_URL); return
            msg = f"📋 Open Tasks — {len(tasks)} remaining\n\n"
            for t in tasks[:12]:
                e = "🔴" if t.get("difficulty") == "hard" else "🟡"
                msg += f"{e} {t['id']}: {t.get('title','')[:55]}\n   Topic: {t.get('skill','')}\n\n"
            if len(tasks) > 12:
                msg += f"...and {len(tasks)-12} more\n\n"
            msg += f"Dashboard: {DASHBOARD_URL}"
            send_msg(chat_id, msg)
        except Exception as e:
            send_msg(chat_id, f"❌ Error: {e}")

    elif cmd == "/today":
        try:
            data, _ = get_data()
            today = datetime.now(IST).strftime("%Y-%m-%d")
            tasks = [t for t in data.get("open_tasks", []) if t.get("assigned_date", "") <= today]
            if not tasks:
                send_msg(chat_id, "🎉 No tasks due today! Use /ask to practice interview questions."); return
            msg = f"📅 Due Today ({today})\n\n"
            for t in tasks[:10]:
                msg += f"• {t['id']}: {t.get('title','')[:55]}\n"
            msg += f"\nTip: use /mock {tasks[0].get('skill','')} to practice!"
            send_msg(chat_id, msg)
        except Exception as e:
            send_msg(chat_id, f"❌ Error: {e}")

    elif cmd == "/skills":
        try:
            data, _ = get_data()
            skills = data.get("skills_breakdown", {})
            msg = "🎯 Skills Progress\n\n"
            for skill, info in skills.items():
                total = info.get("total", 0)
                done = info.get("completed", 0)
                pct = int((done / total) * 100) if total else 0
                bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
                msg += f"{skill}: [{bar}] {done}/{total}\n"
            msg += f"\nDashboard: {DASHBOARD_URL}"
            msg += "\nTip: use /learn <skill> to study any topic"
            send_msg(chat_id, msg)
        except Exception as e:
            send_msg(chat_id, f"❌ Error: {e}")

    elif cmd == "/stats":
        try:
            data, _ = get_data()
            s = data.get("statistics", {})
            send_msg(chat_id,
                f"📊 Your Progress\n\n"
                f"Completed: {s.get('completed_tasks', 0)} tasks\n"
                f"Pending: {s.get('pending_tasks', s.get('total_tasks', 0))} tasks\n"
                f"Streak: {s.get('streak', 0)} days\n"
                f"Rate: {s.get('completion_rate', 0)}%\n\n"
                f"Dashboard: {DASHBOARD_URL}")
        except Exception as e:
            send_msg(chat_id, f"❌ Error: {e}")

    elif cmd == "/streak":
        try:
            data, _ = get_data()
            streak = data.get("statistics", {}).get("streak", 0)
            e = "🔥" if streak >= 3 else ("😐" if streak >= 1 else "💤")
            send_msg(chat_id, f"{e} Streak: {streak} days\n\nComplete tasks daily to build it!\n/today to see what's due")
        except Exception as e:
            send_msg(chat_id, f"❌ Error: {e}")

    elif cmd == "/complete":
        arg_parts = arg.split()
        if not arg_parts:
            send_msg(chat_id, "Usage: /complete task_001\nUse /tasks to see IDs."); return
        task_id = arg_parts[0].strip()
        try:
            data, sha = get_data()
            open_tasks = data.get("open_tasks", [])
            completed_tasks = data.get("completed_tasks", [])
            task = next((t for t in open_tasks if t.get("id") == task_id), None)
            if not task:
                ids = ", ".join(t["id"] for t in open_tasks[:5])
                send_msg(chat_id, f"❌ Task {task_id} not found.\nFirst 5 IDs: {ids}"); return

            open_tasks.remove(task)
            task["completed_at"] = datetime.now(IST).isoformat()
            completed_tasks.append(task)

            stats = data.get("statistics", {})
            stats["completed_tasks"] = stats.get("completed_tasks", 0) + 1
            stats["pending_tasks"] = len(open_tasks)
            total = stats.get("total_tasks", len(open_tasks) + len(completed_tasks))
            stats["total_tasks"] = total
            stats["completion_rate"] = round((stats["completed_tasks"] / total) * 100, 1) if total else 0

            today_str = datetime.now(IST).strftime("%Y-%m-%d")
            timeline = data.get("activity_timeline", {})
            if today_str not in timeline:
                timeline[today_str] = {"completed": 0, "pending": 0}
            timeline[today_str]["completed"] = timeline[today_str].get("completed", 0) + 1
            timeline[today_str]["pending"] = len(open_tasks)

            skill = task.get("skill", "")
            skills = data.get("skills_breakdown", {})
            if skill in skills:
                skills[skill]["completed"] = skills[skill].get("completed", 0) + 1

            if timeline[today_str]["completed"] == 1:
                stats["streak"] = stats.get("streak", 0) + 1

            data.update({"open_tasks": open_tasks, "completed_tasks": completed_tasks,
                         "statistics": stats, "activity_timeline": timeline,
                         "skills_breakdown": skills,
                         "last_updated": datetime.now(IST).isoformat()})
            push_data(data, sha, f"Complete: {task_id}")
            send_msg(chat_id,
                f"✅ Task Done!\n\n"
                f"{task_id}: {task.get('title','')}\n\n"
                f"Progress: {stats['completed_tasks']}/{total} ({stats['completion_rate']}%)\n"
                f"Streak: {stats.get('streak', 0)} days\n\n"
                f"Dashboard: {DASHBOARD_URL}\n\n"
                f"Tip: try /mock {task.get('skill','aws')} to practice this topic!")
        except Exception as e:
            send_msg(chat_id, f"❌ Error: {e}")

    elif cmd == "/resume":
        arg_lower = arg.lower() if arg else ""
        if arg_lower:
            send_msg(chat_id, f"🔍 Analyzing resume aspect: {arg}...")
            advice = resume_coach(arg)
            send_msg(chat_id, f"📄 Resume Coach\n\n{advice}")
        else:
            try:
                data, _ = get_data()
                resume = data.get("resume_assessment", {})
                score = resume.get("score", "N/A")
                issues = resume.get("issues", [])
                strengths = resume.get("strengths", [])
                msg = f"📄 Resume Score: {score}/100\n\n"
                if strengths:
                    msg += "Strengths:\n" + "".join(f"  + {s}\n" for s in strengths[:4])
                if issues:
                    msg += "\nIssues to fix:\n" + "".join(f"  - {i}\n" for i in issues[:4])
                msg += "\nTip: /resume <aspect> for AI advice\nExample: /resume bullet points"
                send_msg(chat_id, msg)
            except Exception as e:
                send_msg(chat_id, f"❌ Error: {e}")

    elif cmd == "/publish":
        try:
            data, sha = get_data()
            data["last_synced"] = datetime.now(IST).isoformat()
            push_data(data, sha, "Dashboard sync via /publish")
            send_msg(chat_id, f"✅ Dashboard synced!\n\n{DASHBOARD_URL}\n\nUpdates in 1-2 mins.")
        except Exception as e:
            send_msg(chat_id, f"❌ Sync failed: {e}")

    else:
        send_msg(chat_id,
            f"Unknown command: {cmd}\n\n"
            "Try:\n"
            "/ask <any interview question>\n"
            "/mock kubernetes\n"
            "/learn aws\n"
            "/tasks\n"
            "/help")


# ── Flask routes ──────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def health():
    return "SkillCoach Bot is running.", 200


@app.route("/", methods=["POST"])
def webhook():
    try:
        update = flask_req.get_json(silent=True) or {}
        msg = update.get("message") or update.get("edited_message", {})
        chat_id = msg.get("chat", {}).get("id")
        text = msg.get("text", "")
        if chat_id and text.startswith("/"):
            if not AUTHORIZED_CHAT_ID or chat_id == AUTHORIZED_CHAT_ID:
                process_command(chat_id, text)
    except Exception:
        pass
    return "OK", 200
