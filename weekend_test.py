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
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

IST = pytz.timezone("Asia/Kolkata")
REPO = "Harshit975shukla/skillcoach-dashboard"
FILE = "docs/data.json"
GH = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
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


def gemini(prompt, max_tokens=2500):
    import time
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    for attempt in range(4):
        r = requests.post(f"{GEMINI_URL}?key={GEMINI_API_KEY}", json=body, timeout=120)
        if r.status_code == 200:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        if r.status_code == 503 and attempt < 3:
            time.sleep(15 * (attempt + 1))
            continue
        raise Exception(f"Gemini {r.status_code}: {r.text[:300]}")
    raise Exception("Gemini failed after 4 attempts")


def send(text):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text[:4000]},
        timeout=10,
    )


def main():
    data, sha = get_data()
    today = date.today()
    today_str = today.isoformat()

    test_state = data.get("test_state", {})
    if test_state.get("date") == today_str and test_state.get("completed"):
        send(
            "You already completed this week's test!\n"
            "Score: " + str(test_state.get("score", 0)) + "/" + str(len(test_state.get("questions", []))) + "\n\n"
            "See you Sunday for next week's plan!"
        )
        return

    curriculum = data.get("curriculum", {})
    daily_lessons = curriculum.get("daily_lessons", {})
    this_monday = today - timedelta(days=today.weekday())
    week_topics = []
    for i in range(5):
        d = (this_monday + timedelta(days=i)).isoformat()
        if d in daily_lessons:
            week_topics.append(d + ": " + daily_lessons[d])

    if not week_topics:
        send("No lessons completed this week yet. Study Mon-Fri first!\n\nTry: /learn aws or /ask <question>")
        return

    topics_str = "\n".join(week_topics)
    week_num = curriculum.get("week_number", 1)

    prompt = "\n".join([
        "You are a Cloud DevOps technical interviewer conducting a weekly test. Return only valid JSON.",
        "",
        "Generate 10 MCQ questions covering these topics:",
        topics_str,
        "",
        "Rules:",
        "- Distribute questions proportionally across all topics",
        "- Difficulty: 3 easy, 4 medium, 3 hard",
        "- Include scenario-based questions",
        "- No repeated concepts",
        "",
        "Return ONLY this JSON (no markdown, no extra text):",
        "{",
        '  "questions": [',
        "    {",
        '      "topic": "short topic label",',
        '      "question": "Question text?",',
        '      "options": {"A": "...", "B": "...", "C": "...", "D": "..."},',
        '      "answer": "B",',
        '      "explanation": "B is correct because... Others are wrong because..."',
        "    }",
        "  ]",
        "}",
    ])

    result = gemini(prompt, 3000)
    try:
        parsed = json.loads(result[result.find("{"):result.rfind("}") + 1])
        questions = parsed["questions"][:10]
        if len(questions) < 5:
            raise ValueError("Too few questions")
    except Exception as e:
        send("Could not generate test (" + str(e) + ").\n\nPractice: /mock aws or /ask <question>")
        return

    data["test_state"] = {
        "active": True,
        "date": today_str,
        "week": week_num,
        "topics": list(daily_lessons.values()),
        "questions": questions,
        "current_q": 0,
        "score": 0,
        "answers": [],
        "completed": False,
    }
    push_data(data, sha, "Week " + str(week_num) + " test started")

    send(
        "Weekly Test - Week " + str(week_num) + "\n\n"
        "Covering: " + ", ".join(set(q["topic"] for q in questions)) + "\n"
        + str(len(questions)) + " questions, one at a time.\n\n"
        "Reply /q A, /q B, /q C, or /q D\nLet's go!"
    )

    q = questions[0]
    send(
        "Test Q1/" + str(len(questions)) + " - " + q["topic"] + "\n\n"
        + q["question"] + "\n\n"
        + "A) " + q["options"]["A"] + "\n"
        + "B) " + q["options"]["B"] + "\n"
        + "C) " + q["options"]["C"] + "\n"
        + "D) " + q["options"]["D"] + "\n\n"
        + "Reply: /q A   /q B   /q C   /q D"
    )


if __name__ == "__main__":
    main()
