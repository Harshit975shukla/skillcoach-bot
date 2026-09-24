"""Runs at 9 AM IST Mon-Fri. Generates and sends daily lesson."""
import json
import base64
import os
import requests
from datetime import datetime, date, timedelta
import pytz

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

IST = pytz.timezone("Asia/Kolkata")
REPO = "Harshit975shukla/skillcoach-dashboard"
FILE = "docs/data.json"
GH = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
DASHBOARD = "https://harshit975shukla.github.io/skillcoach-dashboard"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent"


def get_data():
    r = requests.get(f"https://api.github.com/repos/{REPO}/contents/{FILE}", headers=GH, timeout=15)
    raw = r.json()
    return json.loads(base64.b64decode(raw["content"]).decode()), raw["sha"]


def push_data(data, sha, msg):
    content = base64.b64encode(json.dumps(data, indent=2).encode()).decode()
    requests.put(
        f"https://api.github.com/repos/{REPO}/contents/{FILE}",
        headers=GH,
        json={"message": msg, "content": content, "sha": sha},
        timeout=20,
    )


def gemini(prompt, max_tokens=900):
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    r = requests.post(f"{GEMINI_URL}?key={GEMINI_API_KEY}", json=body, timeout=90)
    if r.status_code != 200:
        raise Exception(f"Gemini {r.status_code}: {r.text[:300]}")
    return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def send(text):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text[:4000]},
        timeout=10,
    )


def generate_week_plan(data, sha, start_date):
    curriculum = data.get("curriculum", {})
    done_topics = list(curriculum.get("daily_lessons", {}).values())
    scores = data.get("weekly_scores", {})
    pref = data.get("next_week_preference", "")
    days = [(start_date + timedelta(days=i)).isoformat() for i in range(6)]

    lines = [
        "You are a Cloud DevOps curriculum planner. Return only valid JSON, no markdown.",
        "",
        "Create a 6-day Cloud DevOps learning plan for Harshit Shukla targeting Senior Cloud DevOps & AI Engineer.",
        "Topics already covered: " + (", ".join(done_topics) if done_topics else "None - first week"),
        "Past test scores: " + (json.dumps(scores) if scores else "No tests yet"),
        "User preference: " + (pref if pref else "Follow logical progression"),
        "",
        "Progression guide:",
        "- No topics done: Start with AWS Core (EC2, VPC, IAM, S3, RDS)",
        "- AWS done: Move to Containers + Kubernetes",
        "- K8s done: Terraform + CI/CD",
        "- CI/CD done: Observability + SRE",
        "- All done: GenAI/LLMOps + System Design",
        "- Score < 60% on a topic: include a revision day for it",
        "",
        "Return ONLY a JSON object (no extra text):",
        "{",
        '  "' + days[0] + '": "Specific Topic: Sub-topic",',
        '  "' + days[1] + '": "Specific Topic: Sub-topic",',
        '  "' + days[2] + '": "Specific Topic: Sub-topic",',
        '  "' + days[3] + '": "Specific Topic: Sub-topic",',
        '  "' + days[4] + '": "Specific Topic: Sub-topic",',
        '  "' + days[5] + '": "Weekly Review: Practice Questions"',
        "}",
    ]
    prompt = "\n".join(lines)

    result = gemini(prompt, 400)
    try:
        plan = json.loads(result[result.find("{"):result.rfind("}") + 1])
    except Exception:
        topics = [
            "AWS EC2: Instance Types & Auto Scaling",
            "AWS VPC: Networking & Security Groups",
            "AWS IAM: Roles, Policies & Best Practices",
            "AWS S3: Storage Classes & Lifecycle",
            "AWS RDS: Multi-AZ & Read Replicas",
            "AWS Review: Practice Questions",
        ]
        plan = dict(zip(days, topics))

    curr = data.get("curriculum", {})
    curr.setdefault("week_plan", {}).update(plan)
    curr["week_number"] = curr.get("week_number", 0) + 1
    data["curriculum"] = curr
    data["next_week_preference"] = ""
    push_data(data, sha, "Week " + str(curr["week_number"]) + " plan generated")
    return plan


def main():
    data, sha = get_data()
    today = date.today()
    today_str = today.isoformat()
    day_name = datetime.now(IST).strftime("%A")

    curriculum = data.get("curriculum", {})
    week_plan = curriculum.get("week_plan", {})
    topic = week_plan.get(today_str)

    if not topic:
        send("Generating your learning plan for this week...")
        monday = today - timedelta(days=today.weekday())
        generate_week_plan(data, sha, monday)
        data, sha = get_data()
        topic = data.get("curriculum", {}).get("week_plan", {}).get(today_str)

    if not topic:
        send("No topic found for today (" + today_str + "). Use /learn <topic> to study manually.")
        return

    lines = [
        "You are SkillCoach, an expert Cloud DevOps & AI Engineer interview coach for Harshit Shukla.",
        "Be specific, practical, and interview-focused. Use plain text only.",
        "",
        "Generate a focused morning lesson for " + day_name + ", " + today_str + ".",
        "Topic: " + topic,
        "",
        "Format exactly like this (plain text, no markdown symbols):",
        "",
        "GOOD MORNING, HARSHIT! Day: " + day_name,
        "Today's Topic: " + topic,
        "",
        "WHAT YOU NEED TO KNOW",
        "(3 core concepts, interview-focused, 2-3 sentences each)",
        "",
        "1. [Concept Name]",
        "[Explanation - what it is, when to use it, why it matters in interviews]",
        "",
        "2. [Concept Name]",
        "[Explanation]",
        "",
        "3. [Concept Name]",
        "[Explanation]",
        "",
        "TODAY'S TASKS",
        "(3 tasks - specific, completable in 20-30 mins each)",
        "",
        "Task 1: [Action-oriented task name]",
        "How: [Step-by-step instructions]",
        "",
        "Task 2: [Practice or reading task]",
        "How: [Instructions]",
        "",
        "Task 3: [Interview prep task]",
        "How: [Instructions]",
        "",
        "INTERVIEW TIP",
        "[One sharp, specific tip for answering " + topic + " questions]",
    ]
    prompt = "\n".join(lines)

    lesson = gemini(prompt, 950)
    send(lesson)
    send(
        "Evening quiz at 6 PM IST on " + topic + "!\n\n"
        "Try now:\n"
        "/ask <any question about today's topic>\n"
        "/learn " + topic.split(":")[0].strip() + "\n"
        "/dashboard\n"
        + DASHBOARD
    )

    curr = data.get("curriculum", {})
    curr.setdefault("daily_lessons", {})[today_str] = topic
    curr["last_topic"] = topic
    data["curriculum"] = curr
    data["last_updated"] = datetime.now(IST).isoformat()
    push_data(data, sha, "Morning lesson: " + topic)
    print("Lesson sent:", topic)


if __name__ == "__main__":
    main()
