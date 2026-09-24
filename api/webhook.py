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


# ── Quiz/test answer handler ──────────────────────────────────────────────────

def _fmt_q(q, idx, total, label="Q"):
    return (
        f"{label}{idx}/{total}\n\n"
        f"{q['question']}\n\n"
        f"A) {q['options']['A']}\n"
        f"B) {q['options']['B']}\n"
        f"C) {q['options']['C']}\n"
        f"D) {q['options']['D']}\n\n"
        f"Reply: /q A   /q B   /q C   /q D"
    )


def _handle_answer(chat_id, data, sha, state, answer, kind):
    questions = state["questions"]
    idx = state["current_q"]
    q = questions[idx]
    correct = q["answer"].upper()
    is_correct = answer == correct

    if is_correct:
        state["score"] = state.get("score", 0) + 1
        fb = f"Correct! ({answer})\n\n{q['explanation']}"
    else:
        fb = f"Wrong. You said {answer}, correct is {correct}\n\n{q['explanation']}"

    send_msg(chat_id, ("✅ " if is_correct else "❌ ") + fb)

    state["current_q"] = idx + 1
    state.setdefault("answers", []).append({"q": idx, "given": answer, "correct": correct, "ok": is_correct})

    total = len(questions)
    next_idx = idx + 1

    if next_idx >= total:
        score = state["score"]
        pct = round((score / total) * 100)
        if kind == "quiz":
            state["active"] = False
            data["quiz_state"] = state
            push_data(data, sha, "Quiz complete")
            emoji = "🔥" if pct >= 80 else ("👍" if pct >= 60 else "📖")
            send_msg(chat_id,
                f"{emoji} Quiz done! {score}/{total} ({pct}%)\n\n"
                f"{'Solid!' if pct >= 80 else 'Keep going!'}\n\n"
                f"Any doubts on today's topic?\nUse /ask <your question>")
        else:
            state["active"] = False
            state["completed"] = True
            data["test_state"] = state
            wk = state.get("week", 1)
            scores = data.get("weekly_scores", {})
            scores[f"week_{wk}"] = pct
            data["weekly_scores"] = scores
            push_data(data, sha, f"Week {wk} test complete: {pct}%")
            emoji = "🏆" if pct >= 80 else ("👍" if pct >= 60 else "📚")
            send_msg(chat_id,
                f"{emoji} Test done! {score}/{total} ({pct}%)\n\n"
                f"{'Excellent work!' if pct >= 80 else 'Good effort!' if pct >= 60 else 'More practice needed!'}\n\n"
                f"Sunday: I'll send next week's plan at 10 AM.\n"
                f"Want to customize it? /nextweek <your preference>")
    else:
        nq = questions[next_idx]
        if kind == "quiz":
            data["quiz_state"] = state
            push_data(data, sha, f"Quiz q{next_idx}")
            send_msg(chat_id, _fmt_q(nq, next_idx + 1, total))
        else:
            data["test_state"] = state
            push_data(data, sha, f"Test q{next_idx}")
            send_msg(chat_id,
                f"Test Q{next_idx + 1}/{total} — {nq.get('topic', '')}\n\n"
                f"{nq['question']}\n\n"
                f"A) {nq['options']['A']}\n"
                f"B) {nq['options']['B']}\n"
                f"C) {nq['options']['C']}\n"
                f"D) {nq['options']['D']}\n\n"
                f"Reply: /q A   /q B   /q C   /q D")


# ── Profile management ────────────────────────────────────────────────────────

def _parse_resume_with_gemini(resume_text):
    prompt = "\n".join([
        "Extract key information from this resume. Return ONLY valid JSON, no markdown, no explanation.",
        "",
        "Resume text:",
        resume_text[:3000],
        "",
        "Return exactly this JSON structure:",
        '{"name":"","current_role":"","years_experience":0,"tech_skills":[],"cloud_skills":[],"target_role_guess":""}',
    ])
    result = ask_gemini(prompt)
    try:
        start = result.find("{")
        end = result.rfind("}") + 1
        return json.loads(result[start:end])
    except Exception:
        return {}


def _parse_jd_with_gemini(jd_text):
    prompt = "\n".join([
        "Extract key requirements from this job description. Return ONLY valid JSON, no markdown.",
        "",
        "JD:",
        jd_text[:3000],
        "",
        "Return exactly this JSON:",
        '{"job_title":"","company_type":"","required_skills":[],"nice_to_have":[],"seniority":"","key_focus_areas":[]}',
    ])
    result = ask_gemini(prompt)
    try:
        start = result.find("{")
        end = result.rfind("}") + 1
        return json.loads(result[start:end])
    except Exception:
        return {}


def _gap_analysis_with_gemini(resume_info, jd_info):
    resume_skills = resume_info.get("tech_skills", []) + resume_info.get("cloud_skills", [])
    jd_required = jd_info.get("required_skills", [])
    prompt = "\n".join([
        "Analyze skill gap. Return ONLY valid JSON, no markdown.",
        "",
        "Resume skills: " + ", ".join(resume_skills),
        "JD required: " + ", ".join(jd_required),
        "Years exp: " + str(resume_info.get("years_experience", "?")),
        "Target role: " + jd_info.get("job_title", "Senior DevOps Engineer"),
        "Seniority needed: " + jd_info.get("seniority", "senior"),
        "",
        "Return:",
        '{"strong_skills":[],"gap_skills":[],"readiness_score":65,"target_role":"","summary":""}',
    ])
    result = ask_gemini(prompt)
    try:
        start = result.find("{")
        end = result.rfind("}") + 1
        return json.loads(result[start:end])
    except Exception:
        return {"strong_skills": resume_skills[:3], "gap_skills": jd_required[:3],
                "readiness_score": 50, "target_role": jd_info.get("job_title", ""), "summary": ""}


def _generate_diag_questions(resume_info):
    skills = resume_info.get("tech_skills", []) + resume_info.get("cloud_skills", [])
    prompt = "\n".join([
        "Generate 5 diagnostic questions to assess skill depth. Return ONLY valid JSON.",
        "",
        "Candidate skills: " + ", ".join(skills),
        "Target: " + resume_info.get("target_role_guess", "Senior DevOps Engineer"),
        "",
        "Each question tests real depth — answerable in 1-3 sentences.",
        'Return: {"questions":[{"skill":"AWS","question":"How do you handle cross-region S3 failover?"}]}',
    ])
    result = ask_gemini(prompt)
    try:
        start = result.find("{")
        end = result.rfind("}") + 1
        return json.loads(result[start:end]).get("questions", [])[:5]
    except Exception:
        return [{"skill": "General", "question": "Describe your most complex cloud project in 2-3 sentences."}]


def _rate_diag_answers(questions, answers):
    qa = "\n".join(
        f"Q ({q.get('skill','?')}): {q.get('question','')}\nA: {a}"
        for q, a in zip(questions, answers)
    )
    prompt = "\n".join([
        "Rate candidate skills from their Q&A answers. Return ONLY valid JSON.",
        "",
        qa,
        "",
        'Return: {"skill_ratings":{"AWS":3},"readiness_score":65,"strong_skills":[],"gap_skills":[],"summary":""}',
    ])
    result = ask_gemini(prompt)
    try:
        start = result.find("{")
        end = result.rfind("}") + 1
        return json.loads(result[start:end])
    except Exception:
        return {"skill_ratings": {}, "readiness_score": 50, "strong_skills": [], "gap_skills": [], "summary": ""}


def handle_text_input(chat_id, text):
    """Handle non-command messages when a setup flow is active. Silently ignores otherwise."""
    try:
        data, sha = get_data()
        profile = data.get("profile", {})
        state = profile.get("setup_state", "idle")

        if state == "awaiting_resume":
            if len(text.strip()) < 80:
                send_msg(chat_id, "That looks too short. Paste your full resume text (experience, skills, education).")
                return
            send_msg(chat_id, "Got your resume! Analyzing skills...")
            resume_info = _parse_resume_with_gemini(text)
            profile["resume_text"] = text[:5000]
            profile["resume_info"] = resume_info
            profile["setup_state"] = "awaiting_jd"
            data["profile"] = profile
            push_data(data, sha, "Profile: resume stored")
            skills = resume_info.get("tech_skills", []) + resume_info.get("cloud_skills", [])
            send_msg(chat_id,
                "Resume analyzed!\n\n"
                "Skills found: " + (", ".join(skills[:8]) if skills else "None detected") + "\n"
                "Experience: " + str(resume_info.get("years_experience", "?")) + " years\n\n"
                "Do you have a Job Description to target?\n"
                "Paste it now, or send /skip to do a diagnostic assessment instead."
            )

        elif state == "awaiting_jd":
            if len(text.strip()) < 50:
                send_msg(chat_id, "Too short for a JD. Paste the full description, or send /skip.")
                return
            send_msg(chat_id, "Analyzing job requirements and identifying skill gaps...")
            resume_info = profile.get("resume_info", {})
            jd_info = _parse_jd_with_gemini(text)
            gap = _gap_analysis_with_gemini(resume_info, jd_info)
            profile["jd_text"] = text[:5000]
            profile["jd_info"] = jd_info
            profile["target_role"] = gap.get("target_role", jd_info.get("job_title", ""))
            profile["strong_skills"] = gap.get("strong_skills", [])
            profile["gap_skills"] = gap.get("gap_skills", [])
            profile["readiness_score"] = gap.get("readiness_score", 0)
            profile["setup_state"] = "idle"
            profile["setup_complete"] = True
            data["profile"] = profile
            push_data(data, sha, "Profile: gap analysis complete")
            score = gap.get("readiness_score", 0)
            emoji = "Great progress!" if score >= 80 else ("Keep going!" if score >= 60 else "Room to grow!")
            send_msg(chat_id,
                "Setup Complete!\n\n"
                "Target: " + gap.get("target_role", "") + "\n"
                "Readiness: " + str(score) + "%\n\n"
                "Strong skills: " + ", ".join(gap.get("strong_skills", [])[:5]) + "\n"
                "Gaps to fill: " + ", ".join(gap.get("gap_skills", [])[:5]) + "\n\n"
                + gap.get("summary", "") + "\n\n"
                + emoji + " Daily lessons will now focus on your gaps.\n"
                "Use /score to track progress. Use /gaps for the full list."
            )

        elif state.startswith("awaiting_diag_"):
            idx = int(state.split("_")[-1])
            questions = profile.get("diag_questions", [])
            answers = profile.get("diag_answers", [])
            answers.append(text.strip())
            profile["diag_answers"] = answers
            next_idx = idx + 1

            if next_idx >= len(questions):
                send_msg(chat_id, "All questions done! Rating your skills...")
                ratings = _rate_diag_answers(questions, answers)
                profile["skill_ratings"] = ratings.get("skill_ratings", {})
                profile["readiness_score"] = ratings.get("readiness_score", 50)
                profile["strong_skills"] = ratings.get("strong_skills", [])
                profile["gap_skills"] = ratings.get("gap_skills", [])
                profile["target_role"] = profile.get("resume_info", {}).get("target_role_guess", "Senior DevOps Engineer")
                profile["setup_state"] = "idle"
                profile["setup_complete"] = True
                data["profile"] = profile
                push_data(data, sha, "Profile: diagnostic complete")
                score = ratings.get("readiness_score", 50)
                skill_ratings = ratings.get("skill_ratings", {})
                bars = "\n".join(
                    "  " + k + ": " + ("█" * v + "░" * (5 - v)) + " " + str(v) + "/5"
                    for k, v in skill_ratings.items()
                ) if skill_ratings else "  (not enough data)"
                send_msg(chat_id,
                    "Assessment Complete!\n\n"
                    "Readiness: " + str(score) + "%\n\n"
                    "Skill Ratings:\n" + bars + "\n\n"
                    "Strong: " + ", ".join(ratings.get("strong_skills", [])) + "\n"
                    "Focus on: " + ", ".join(ratings.get("gap_skills", [])) + "\n\n"
                    + ratings.get("summary", "") + "\n\n"
                    "Daily lessons will now target your gaps.\n"
                    "Use /score to track progress."
                )
            else:
                profile["setup_state"] = "awaiting_diag_" + str(next_idx)
                data["profile"] = profile
                push_data(data, sha, "Profile: diag q" + str(next_idx))
                nq = questions[next_idx]
                send_msg(chat_id,
                    "Question " + str(next_idx + 1) + "/" + str(len(questions)) + " — " + nq.get("skill", "") + "\n\n"
                    + nq.get("question", "") + "\n\n"
                    "Answer briefly (1-3 sentences):"
                )
        # If state is idle, ignore non-command messages silently

    except Exception as e:
        print("Text input error:", e)


# ── Command handlers ──────────────────────────────────────────────────────────

def process_command(chat_id, text):
    parts = text.strip().split(None, 1)
    cmd = parts[0].split("@")[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/start":
        send_msg(chat_id,
            "SkillCoach Bot — AI interview mentor!\n\n"
            f"Chat ID: {chat_id}\n\n"
            "PROFILE SETUP (start here):\n"
            "/setup — Add your resume + JD for a personalized plan\n"
            "/score — Your readiness score & skill ratings\n"
            "/gaps  — Skills you need to fill for your target role\n"
            "/assess — Redo diagnostic Q&A to update ratings\n\n"
            "DAILY LEARNING:\n"
            "9 AM — Morning lesson (Mon-Fri)\n"
            "6 PM — Evening quiz (Mon-Fri)\n"
            "Sat  — Weekly test\n"
            "Sun  — Next week's plan\n\n"
            "AI COACHING:\n"
            "/ask <question> — Ask anything\n"
            "/mock <topic> — Mock interview Q\n"
            "/learn <topic> — Study guide\n"
            "/tip — Today's tip\n\n"
            "QUIZ:\n"
            "/q A (or B/C/D) — Answer quiz/test question\n\n"
            "PLANNING:\n"
            "/curriculum — This week's schedule\n"
            "/nextweek <preference> — Customize next week\n\n"
            "TRACKING:\n"
            "/tasks  /skills  /stats  /dashboard\n"
            "/complete <task_id>")

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

    elif cmd == "/q":
        if not arg:
            send_msg(chat_id, "Usage: /q A  (or B, C, D)\n\nWait for the quiz at 6 PM IST or test on Saturday 9 AM IST.")
            return
        answer = arg.strip().upper()[:1]
        if answer not in ["A", "B", "C", "D"]:
            send_msg(chat_id, "Please reply /q A, /q B, /q C, or /q D")
            return
        try:
            data, sha = get_data()
            quiz = data.get("quiz_state", {})
            test = data.get("test_state", {})
            if quiz.get("active") and quiz.get("current_q", 0) < len(quiz.get("questions", [])):
                _handle_answer(chat_id, data, sha, quiz, answer, "quiz")
            elif test.get("active") and not test.get("completed") and test.get("current_q", 0) < len(test.get("questions", [])):
                _handle_answer(chat_id, data, sha, test, answer, "test")
            else:
                send_msg(chat_id, "No active quiz right now.\n\nQuiz: daily at 6 PM IST\nTest: Saturday 9 AM IST\n\nOr practice with /ask or /mock")
        except Exception as e:
            send_msg(chat_id, f"❌ Error: {e}")

    elif cmd == "/nextweek":
        if not arg:
            send_msg(chat_id, "Usage: /nextweek <your preference>\n\nExample:\n/nextweek focus more on Kubernetes\n/nextweek I want to start Terraform\n/nextweek review AWS again, my score was low")
            return
        try:
            data, sha = get_data()
            data["next_week_preference"] = arg
            push_data(data, sha, "Next week preference saved")
            send_msg(chat_id, f"Saved! Sunday's plan will incorporate: {arg}\n\nSee you Sunday morning for your personalized week plan!")
        except Exception as e:
            send_msg(chat_id, f"❌ Error: {e}")

    elif cmd == "/setup":
        try:
            data, sha = get_data()
            profile = data.get("profile", {})
            if profile.get("setup_complete") and arg.lower() != "reset":
                score = profile.get("readiness_score", 0)
                send_msg(chat_id,
                    "Profile already set up!\n\n"
                    "Target: " + profile.get("target_role", "Not set") + "\n"
                    "Readiness: " + str(score) + "%\n\n"
                    "Commands:\n"
                    "/score — Full skill breakdown\n"
                    "/gaps  — Skills to fill\n"
                    "/assess — Redo diagnostic\n"
                    "/setup reset — Start fresh"
                )
            else:
                data["profile"] = {"setup_state": "awaiting_resume"}
                push_data(data, sha, "Profile: setup started")
                send_msg(chat_id,
                    "Let's build your personalized coaching plan!\n\n"
                    "Step 1 of 2: Paste your resume text below.\n\n"
                    "Copy your full resume (experience, skills, education) and paste it as a message. The more detail, the better."
                )
        except Exception as e:
            send_msg(chat_id, "Error: " + str(e))

    elif cmd == "/skip":
        try:
            data, sha = get_data()
            profile = data.get("profile", {})
            if profile.get("setup_state") != "awaiting_jd":
                send_msg(chat_id, "Nothing to skip. Use /setup to start your profile setup.")
                return
            send_msg(chat_id, "No JD — running a quick diagnostic instead. Generating questions based on your resume...")
            questions = _generate_diag_questions(profile.get("resume_info", {}))
            profile["diag_questions"] = questions
            profile["diag_answers"] = []
            profile["setup_state"] = "awaiting_diag_0"
            data["profile"] = profile
            push_data(data, sha, "Profile: diagnostic started")
            q = questions[0]
            send_msg(chat_id,
                "Question 1/" + str(len(questions)) + " — " + q.get("skill", "") + "\n\n"
                + q.get("question", "") + "\n\n"
                "Answer briefly (1-3 sentences):"
            )
        except Exception as e:
            send_msg(chat_id, "Error: " + str(e))

    elif cmd == "/assess":
        try:
            data, sha = get_data()
            profile = data.get("profile", {})
            if not profile.get("resume_info"):
                send_msg(chat_id, "No resume on file. Run /setup first to add your resume.")
                return
            send_msg(chat_id, "Starting diagnostic — 5 questions on your claimed skills...")
            questions = _generate_diag_questions(profile.get("resume_info", {}))
            profile["diag_questions"] = questions
            profile["diag_answers"] = []
            profile["setup_state"] = "awaiting_diag_0"
            data["profile"] = profile
            push_data(data, sha, "Profile: reassessment started")
            q = questions[0]
            send_msg(chat_id,
                "Question 1/" + str(len(questions)) + " — " + q.get("skill", "") + "\n\n"
                + q.get("question", "") + "\n\n"
                "Answer briefly (1-3 sentences):"
            )
        except Exception as e:
            send_msg(chat_id, "Error: " + str(e))

    elif cmd == "/score":
        try:
            data, _ = get_data()
            profile = data.get("profile", {})
            if not profile.get("setup_complete"):
                send_msg(chat_id, "No profile yet. Run /setup to get started!")
                return
            score = profile.get("readiness_score", 0)
            icon = "Strong" if score >= 80 else ("Good" if score >= 60 else "Building")
            skill_ratings = profile.get("skill_ratings", {})
            bars = "\n".join(
                "  " + k + ": " + ("█" * v + "░" * (5 - v)) + " " + str(v) + "/5"
                for k, v in skill_ratings.items()
            ) if skill_ratings else "  (run /assess to get skill ratings)"
            send_msg(chat_id,
                "Job Readiness — " + icon + "\n\n"
                "Target: " + profile.get("target_role", "Not set") + "\n"
                "Score: " + str(score) + "%\n\n"
                "Skill Ratings:\n" + bars + "\n\n"
                "Strong: " + (", ".join(profile.get("strong_skills", [])) or "None yet") + "\n"
                "Focus on: " + (", ".join(profile.get("gap_skills", [])) or "None identified") + "\n\n"
                "Daily lessons target your gaps automatically.\n"
                "Use /assess to update ratings anytime."
            )
        except Exception as e:
            send_msg(chat_id, "Error: " + str(e))

    elif cmd == "/gaps":
        try:
            data, _ = get_data()
            profile = data.get("profile", {})
            if not profile.get("setup_complete"):
                send_msg(chat_id, "No profile yet. Run /setup first!")
                return
            gap_skills = profile.get("gap_skills", [])
            strong_skills = profile.get("strong_skills", [])
            jd_info = profile.get("jd_info", {})
            msg = "Gap Analysis — " + profile.get("target_role", "Target Role") + "\n\n"
            if gap_skills:
                msg += "SKILLS TO BUILD:\n"
                for i, s in enumerate(gap_skills, 1):
                    msg += "  " + str(i) + ". " + s + "\n"
            else:
                msg += "No gaps identified yet.\n"
            if strong_skills:
                msg += "\nYOUR STRENGTHS:\n"
                for s in strong_skills:
                    msg += "  + " + s + "\n"
            if jd_info.get("key_focus_areas"):
                msg += "\nJD KEY AREAS: " + ", ".join(jd_info["key_focus_areas"]) + "\n"
            msg += "\nStudy a gap: /learn <skill>\nPractice a gap: /mock <skill>"
            send_msg(chat_id, msg)
        except Exception as e:
            send_msg(chat_id, "Error: " + str(e))

    elif cmd == "/curriculum":
        try:
            data, _ = get_data()
            curriculum = data.get("curriculum", {})
            week_plan = curriculum.get("week_plan", {})
            week_num = curriculum.get("week_number", 1)
            weekly_scores = data.get("weekly_scores", {})
            today_str = datetime.now(IST).strftime("%Y-%m-%d")
            msg = f"📅 Week {week_num} Curriculum\n\n"
            if week_plan:
                for d in sorted(week_plan):
                    marker = "→" if d == today_str else ("✓" if d < today_str else " ")
                    msg += f"{marker} {d}: {week_plan[d]}\n"
            else:
                msg += "No plan yet — lesson tomorrow will generate it!\n"
            if weekly_scores:
                msg += "\nWeekly Test Scores:\n"
                for k, v in weekly_scores.items():
                    msg += f"  Week {k.split('_')[1]}: {v}%\n"
            msg += f"\nDashboard: {DASHBOARD_URL}"
            send_msg(chat_id, msg)
        except Exception as e:
            send_msg(chat_id, f"❌ Error: {e}")

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
        if chat_id and text:
            if not AUTHORIZED_CHAT_ID or chat_id == AUTHORIZED_CHAT_ID:
                if text.startswith("/"):
                    process_command(chat_id, text)
                else:
                    handle_text_input(chat_id, text)
    except Exception:
        pass
    return "OK", 200
