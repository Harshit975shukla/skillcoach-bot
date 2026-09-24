"""Runs at 6 PM IST Mon-Fri. Generates quiz and sends first question."""
import json
import base64
import os
import requests
from datetime import datetime, date
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


def nvidia(system, prompt, max_tokens=1500):
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
        timeout=90,
    )
    if r.status_code != 200:
        raise Exception(f"NVIDIA {r.status_code}: {r.text[:300]}")
    try:
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        content_parts = []
        for line in r.text.splitlines():
            if line.startswith("data: ") and "[DONE]" not in line:
                try:
                    chunk = json.loads(line[6:])
                    delta = chunk["choices"][0].get("delta", {}).get("content", "")
                    if delta:
                        content_parts.append(delta)
                except Exception:
                    pass
        if content_parts:
            return "".join(content_parts).strip()
        raise Exception(f"Parse failed ({e}). Response: {r.text[:400]}")


def send(text):
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                  json={"chat_id": CHAT_ID, "text": text[:4000]}, timeout=10)


def fmt_question(q, index, total, prefix="Q"):
    return (
        f"{prefix}{index}/{total}\n\n"
        f"{q['question']}\n\n"
        f"A) {q['options']['A']}\n"
        f"B) {q['options']['B']}\n"
        f"C) {q['options']['C']}\n"
        f"D) {q['options']['D']}\n\n"
        f"Reply: /q A   /q B   /q C   /q D"
    )


def main():
    data, sha = get_data()
    today_str = date.today().isoformat()

    curriculum = data.get("curriculum", {})
    topic = curriculum.get("daily_lessons", {}).get(today_str) or curriculum.get("last_topic", "AWS Core")

    result = nvidia(
        "You are a Cloud DevOps technical interviewer. Return only valid JSON, no markdown.",
        f"""Generate 5 MCQ questions on: {topic}
Target: Senior Cloud DevOps / AI Engineer interview preparation for Harshit Shukla.

Difficulty mix: 2 straightforward, 2 scenario-based, 1 tricky/advanced.
Make scenario questions start with "You need to..." or "Your team is..."

Return ONLY this JSON (no text before or after):
{{
  "questions": [
    {{
      "question": "Question text ending with ?",
      "options": {{"A": "option text", "B": "option text", "C": "option text", "D": "option text"}},
      "answer": "A",
      "explanation": "A is correct because... B is wrong because... (2-3 sentences, cover all options)"
    }}
  ]
}}""",
        max_tokens=1800,
    )

    try:
        parsed = json.loads(result[result.find("{"):result.rfind("}") + 1])
        questions = parsed["questions"][:5]
        if len(questions) < 3:
            raise ValueError("Too few questions")
    except Exception as e:
        send(f"Evening check-in! I couldn't generate the quiz right now ({e}).\n\nPractice manually:\n/ask <question about {topic}>\n/mock {topic.split(':')[0]}")
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
    push_data(data, sha, f"Evening quiz: {topic}")

    send(
        f"Evening Check-in!\n\n"
        f"Topic: {topic}\n"
        f"5 questions — let's see what stuck!\n\n"
        f"Reply /q A, /q B, /q C, or /q D for each."
    )
    send(fmt_question(questions[0], 1, len(questions)))


if __name__ == "__main__":
    main()
