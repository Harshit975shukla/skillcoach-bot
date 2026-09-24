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
NVIDIA_API_KEY = os.environ["NVIDIA_API_KEY"]

IST = pytz.timezone("Asia/Kolkata")
REPO = "Harshit975shukla/skillcoach-dashboard"
FILE = "docs/data.json"
GH = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
DASHBOARD = "https://harshit975shukla.github.io/skillcoach-dashboard"


def get_data():
    r = requests.get(f"https://api.github.com/repos/{REPO}/contents/{FILE}", headers=GH, timeout=15)
    raw = r.json()
    return json.loads(base64.b64decode(raw["content"]).decode()), raw["sha"]


def push_data(data, sha, msg):
    content = base64.b64encode(json.dumps(data, indent=2).encode()).decode()
    requests.put(f"https://api.github.com/repos/{REPO}/contents/{FILE}",
                 headers=GH, json={"message": msg, "content": content, "sha": sha}, timeout=20)


def nvidia(system, prompt, max_tokens=900):
    r = requests.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": "meta/llama-3.1-405b-instruct",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.7,
            "stream": False,
        },
        timeout=90,
    )
    return r.json()["choices"][0]["message"]["content"].strip()


def send(text):
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                  json={"chat_id": CHAT_ID, "text": text[:4000]}, timeout=10)


def generate_week_plan(data, sha, start_date):
    """Generate a 6-day plan (Mon-Sat) using NVIDIA."""
    curriculum = data.get("curriculum", {})
    done_topics = list(curriculum.get("daily_lessons", {}).values())
    scores = data.get("weekly_scores", {})
    pref = data.get("next_week_preference", "")

    days = [(start_date + timedelta(days=i)).isoformat() for i in range(6)]

    prompt = f"""Create a 6-day Cloud DevOps learning plan for Harshit Shukla.
Target role: Senior Cloud DevOps & AI Engineer

Topics already covered: {', '.join(done_topics) if done_topics else 'None - this is the start'}
Past test scores: {json.dumps(scores) if scores else 'No tests yet'}
User preference: {pref if pref else 'Follow logical progression for interview prep'}

Progression guide:
- If no topics done: Start with AWS Core (EC2, VPC, IAM, S3, RDS)
- If AWS done: Move to Containers + Kubernetes
- If K8s done: Terraform + CI/CD
- If CI/CD done: Observability + SRE
- If all done: GenAI/LLMOps + System Design
- If score < 60% on a topic, include a revision day for that topic

Return ONLY a JSON object mapping dates to specific topics:
{{
  "{days[0]}": "Specific Topic: Sub-topic",
  "{days[1]}": "Specific Topic: Sub-topic",
  "{days[2]}": "Specific Topic: Sub-topic",
  "{days[3]}": "Specific Topic: Sub-topic",
  "{days[4]}": "Specific Topic: Sub-topic",
  "{days[5]}": "Weekly Review: Practice Questions"
}}

Be specific (e.g. "AWS EC2: Instance Types & Auto Scaling Groups", not just "EC2")."""

    result = nvidia("You are a Cloud DevOps curriculum planner. Return only valid JSON.", prompt, 400)
    try:
        plan = json.loads(result[result.find("{"):result.rfind("}") + 1])
    except Exception:
        topics = [
            "AWS EC2: Instance Types & Auto Scaling", "AWS VPC: Networking & Security Groups",
            "AWS IAM: Roles, Policies & Best Practices", "AWS S3: Storage Classes & Lifecycle",
            "AWS RDS: Multi-AZ & Read Replicas", "AWS Review: Practice Questions"
        ]
        plan = dict(zip(days, topics))

    curr = data.get("curriculum", {})
    curr.setdefault("week_plan", {}).update(plan)
    curr["week_number"] = curr.get("week_number", 0) + 1
    data["curriculum"] = curr
    data["next_week_preference"] = ""
    push_data(data, sha, f"Generate week {curr['week_number']} plan")
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
        send("📅 Generating your learning plan...")
        # Find this week's Monday
        monday = today - timedelta(days=today.weekday())
        plan = generate_week_plan(data, sha, monday)
        data, sha = get_data()
        topic = data.get("curriculum", {}).get("week_plan", {}).get(today_str)

    if not topic:
        send(f"⚠️ No topic found for today ({today_str}). Use /learn <topic> to study manually.")
        return

    # Generate lesson
    lesson = nvidia(
        "You are SkillCoach, an expert Cloud DevOps & AI Engineer interview coach for Harshit Shukla. "
        "Be specific, practical, and interview-focused. Use plain text only.",
        f"""Generate a focused morning lesson for {day_name}, {today_str}.
Topic: {topic}

Format exactly like this (plain text, no markdown symbols):

GOOD MORNING, HARSHIT! Day: {day_name}
Today's Topic: {topic}

WHAT YOU NEED TO KNOW
(3 core concepts — interview-focused, 2-3 sentences each)

1. [Concept Name]
[Explanation — what it is, when you use it, why it matters]

2. [Concept Name]
[Explanation]

3. [Concept Name]
[Explanation]

TODAY'S TASKS
(3 tasks — specific, completable in 20-30 mins each)

Task 1: [Action-oriented task name]
How: [Step-by-step — be specific, e.g. "Go to AWS Console > EC2 > Launch instance..."]

Task 2: [Practice/reading task]
How: [Instructions]

Task 3: [Interview prep task — e.g., write out your answer to a specific Q]
How: [Instructions]

INTERVIEW TIP
[One sharp, specific tip for answering {topic} questions in interviews]""",
        max_tokens=950,
    )

    send(lesson)
    send(
        f"Evening quiz at 6 PM IST on {topic}!\n\n"
        f"Commands:\n"
        f"/ask <question> — ask anything now\n"
        f"/learn {topic.split(':')[0].strip()} — deeper dive\n"
        f"/dashboard — check your progress\n"
        f"{DASHBOARD}"
    )

    # Update curriculum state
    curr = data.get("curriculum", {})
    curr.setdefault("daily_lessons", {})[today_str] = topic
    curr["last_topic"] = topic
    data["curriculum"] = curr
    data["last_updated"] = datetime.now(IST).isoformat()
    push_data(data, sha, f"Morning lesson: {topic}")
    print(f"Lesson sent: {topic}")


if __name__ == "__main__":
    main()
