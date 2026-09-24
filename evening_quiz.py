"""Runs at 6 PM IST Mon-Fri. Generates quiz and sends first question."""
import json
import base64
import os
import requests
from datetime import date
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


def gemini(prompt, max_tokens=1800):
    import time
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    for attempt in range(6):
        r = requests.post(f"{GEMINI_URL}?key={GEMINI_API_KEY}", json=body, timeout=90)
        if r.status_code == 200:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        if r.status_code in (429, 503) and attempt < 5:
            wait = 60 + 30 * attempt
            print(f"Gemini {r.status_code}, retrying in {wait}s (attempt {attempt+1}/6)")
            time.sleep(wait)
            continue
        raise Exception(f"Gemini {r.status_code}: {r.text[:300]}")
    raise Exception("Gemini failed after 6 attempts")


def send(text):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text[:4000]},
        timeout=10,
    )


def fmt_q(q, index, total):
    return (
        "Q" + str(index) + "/" + str(total) + "\n\n"
        + q["question"] + "\n\n"
        + "A) " + q["options"]["A"] + "\n"
        + "B) " + q["options"]["B"] + "\n"
        + "C) " + q["options"]["C"] + "\n"
        + "D) " + q["options"]["D"] + "\n\n"
        + "Reply: /q A   /q B   /q C   /q D"
    )


def main():
    data, sha = get_data()
    today_str = date.today().isoformat()

    curriculum = data.get("curriculum", {})
    topic = curriculum.get("daily_lessons", {}).get(today_str) or curriculum.get("last_topic", "AWS Core")

    profile = data.get("profile", {})
    profile_context = ""
    if profile.get("setup_complete") and profile.get("target_role"):
        profile_context = (
            "Target role: " + profile.get("target_role", "") + ". "
            + "Gap skills to focus on: " + ", ".join(profile.get("gap_skills", [])[:5]) + "."
        )

    prompt = "\n".join([
        "You are a Cloud DevOps technical interviewer. Return only valid JSON, no markdown.",
        "",
        "Generate 5 MCQ questions on: " + topic,
        *(["Context: " + profile_context] if profile_context else []),
        "Target: Senior Cloud DevOps / AI Engineer interview preparation.",
        "",
        "Difficulty: 2 straightforward, 2 scenario-based, 1 tricky.",
        "Scenario questions must start with 'You need to...' or 'Your team is...'",
        "",
        "Return ONLY this JSON (no text before or after, no markdown fences):",
        "{",
        '  "questions": [',
        "    {",
        '      "question": "Question ending with ?",',
        '      "options": {"A": "option", "B": "option", "C": "option", "D": "option"},',
        '      "answer": "A",',
        '      "explanation": "Why A is correct and others wrong. 2-3 sentences."',
        "    }",
        "  ]",
        "}",
    ])

    result = gemini(prompt, 1800)
    try:
        parsed = json.loads(result[result.find("{"):result.rfind("}") + 1])
        questions = parsed["questions"][:5]
        if len(questions) < 3:
            raise ValueError("Too few questions")
    except Exception as e:
        send(
            "Evening check-in! Quiz unavailable (" + str(e) + ").\n\n"
            "Practice with:\n"
            "/ask <question about " + topic + ">\n"
            "/mock " + topic.split(":")[0].strip()
        )
        return

    data["quiz_state"] = {
        "active": True,
        "date": today_str,
        "topic": topic,
        "questions": questions,
        "current_q": 0,
        "score": 0,
        "answers": [],
    }
    push_data(data, sha, "Evening quiz: " + topic)

    send(
        "Evening Check-in!\n\n"
        "Topic: " + topic + "\n"
        "5 questions - let's see what stuck!\n\n"
        "Reply /q A, /q B, /q C, or /q D for each."
    )
    send(fmt_q(questions[0], 1, len(questions)))


if __name__ == "__main__":
    main()
