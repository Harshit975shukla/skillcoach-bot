"""Runs at 9 AM IST Saturday. Sends 10-question weekly test (one at a time)."""
import json
import base64
import os
import requests
from datetime import date, timedelta
import pytz

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
NVIDIA_API_KEY = os.environ["NVIDIA_API_KEY"]

IST = pytz.timezone("Asia/Kolkata")
REPO = "Harshit975shukla/skillcoach-dashboard"
FILE = "docs/data.json"
GH = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}


def get_data():
    r = requests.get(f"https://api.github.com/repos/{REPO}/contents/{FILE}", headers=GH, timeout=15)
    raw = r.json()
    return json.loads(base64.b64decode(raw["content"]).decode()), raw["sha"]


def push_data(data, sha, msg):
    content = base64.b64encode(json.dumps(data, indent=2).encode()).decode()
    requests.put(f"https://api.github.com/repos/{REPO}/contents/{FILE}",
                 headers=GH, json={"message": msg, "content": content, "sha": sha}, timeout=20)


def nvidia(system, prompt, max_tokens=2500):
    r = requests.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": "meta/llama-3.1-405b-instruct",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.8,
            "stream": False,
        },
        timeout=120,
    )
    return r.json()["choices"][0]["message"]["content"].strip()


def send(text):
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                  json={"chat_id": CHAT_ID, "text": text[:4000]}, timeout=10)


def main():
    data, sha = get_data()
    today = date.today()
    today_str = today.isoformat()

    test_state = data.get("test_state", {})
    if test_state.get("date") == today_str and test_state.get("completed"):
        send(f"You already completed this week's test!\nScore: {test_state.get('score', 0)}/{len(test_state.get('questions', []))}\n\nSee you Sunday for next week's plan!")
        return

    # Get this week's topics (Mon-Fri)
    curriculum = data.get("curriculum", {})
    daily_lessons = curriculum.get("daily_lessons", {})
    this_monday = today - timedelta(days=today.weekday())
    week_topics = []
    for i in range(5):
        d = (this_monday + timedelta(days=i)).isoformat()
        if d in daily_lessons:
            week_topics.append(f"{d}: {daily_lessons[d]}")

    if not week_topics:
        send("No lessons completed this week yet.\n\nThe test needs at least 1 completed lesson. Study Mon-Fri first!\n\nTry: /learn aws or /ask <question>")
        return

    topics_str = "\n".join(week_topics)
    week_num = curriculum.get("week_number", 1)

    result = nvidia(
        "You are a Cloud DevOps technical interviewer conducting a weekly test. Return only valid JSON.",
        f"""Generate 10 MCQ questions for a weekly test covering these topics:
{topics_str}

Rules:
- Distribute questions across all topics (proportionally)
- Difficulty: 3 easy, 4 medium, 3 hard
- Include scenario-based questions ("You need to...", "Your production system...")
- No repeated concepts

Return ONLY this JSON (no markdown, no extra text):
{{
  "questions": [
    {{
      "topic": "short topic label",
      "question": "Question text?",
      "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
      "answer": "B",
      "explanation": "B is correct because... The other options are wrong because..."
    }}
  ]
}}""",
        max_tokens=3000,
    )

    try:
        parsed = json.loads(result[result.find("{"):result.rfind("}") + 1])
        questions = parsed["questions"][:10]
        if len(questions) < 5:
            raise ValueError("Too few questions generated")
    except Exception as e:
        send(f"Could not generate test ({e}).\n\nPractice manually:\n/mock aws\n/ask <any question>")
        return

    data["test_state"] = {
        "active": True,
        "date": today_str,
        "week": week_num,
        "topics": [dl for dl in daily_lessons.values()],
        "questions": questions,
        "current_q": 0,
        "score": 0,
        "answers": [],
        "completed": False,
    }
    push_data(data, sha, f"Week {week_num} test started")

    send(
        f"Weekly Test — Week {week_num}\n\n"
        f"Covering: {', '.join(set(q['topic'] for q in questions))}\n"
        f"{len(questions)} questions, one at a time.\n\n"
        f"Reply /q A, /q B, /q C, or /q D\nLet's go!"
    )

    q = questions[0]
    send(
        f"Test Q1/{len(questions)} — {q['topic']}\n\n"
        f"{q['question']}\n\n"
        f"A) {q['options']['A']}\n"
        f"B) {q['options']['B']}\n"
        f"C) {q['options']['C']}\n"
        f"D) {q['options']['D']}\n\n"
        f"Reply: /q A   /q B   /q C   /q D"
    )


if __name__ == "__main__":
    main()
