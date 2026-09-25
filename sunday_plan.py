"""Runs at 10 AM IST Sunday. Reviews week, generates next week's plan."""
import json
import base64
import os
import requests
from datetime import datetime, date, timedelta
import pytz

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

IST = pytz.timezone("Asia/Kolkata")
REPO = "Harshit975shukla/skillcoach-dashboard"
FILE = "docs/data.json"
GH = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
DASHBOARD = "https://harshit975shukla.github.io/skillcoach-dashboard"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
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


def _groq_call(prompt, max_tokens):
    import time
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    body = {"model": "openai/gpt-oss-120b", "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens}
    for attempt in range(3):
        r = requests.post(GROQ_URL, json=body, headers=headers, timeout=60)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        if r.status_code in (429, 503) and attempt < 2:
            time.sleep(30 + 15 * attempt)
            continue
        raise Exception(f"Groq {r.status_code}: {r.text[:200]}")
    raise Exception("Groq failed")


def _gemini_call(prompt, max_tokens):
    import time
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": max_tokens}}
    for attempt in range(4):
        r = requests.post(f"{GEMINI_URL}?key={GEMINI_API_KEY}", json=body, timeout=90)
        if r.status_code == 200:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        if r.status_code in (429, 503) and attempt < 3:
            time.sleep(60 + 30 * attempt)
            continue
        raise Exception(f"Gemini {r.status_code}: {r.text[:200]}")
    raise Exception("Gemini failed")


def ai(prompt, max_tokens=800):
    """Try Groq first (14,400 RPD free). Fall back to Gemini on failure."""
    if GROQ_API_KEY:
        try:
            return _groq_call(prompt, max_tokens)
        except Exception as e:
            print(f"Groq unavailable ({e}), falling back to Gemini")
    if GEMINI_API_KEY:
        return _gemini_call(prompt, max_tokens)
    raise Exception("No AI API key configured")


def send(text):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text[:4000]},
        timeout=10,
    )


def main():
    data, sha = get_data()
    today = date.today()
    next_monday = today + timedelta(days=1)

    curriculum = data.get("curriculum", {})
    test_state = data.get("test_state", {})
    weekly_scores = data.get("weekly_scores", {})
    preference = data.get("next_week_preference", "")
    week_num = curriculum.get("week_number", 1)

    test_questions = test_state.get("questions", [])
    test_score = test_state.get("score", 0)
    test_total = len(test_questions) if test_questions else 10
    test_pct = round((test_score / test_total) * 100) if test_total else 0

    weekly_scores["week_" + str(week_num)] = test_pct
    data["weekly_scores"] = weekly_scores

    daily_lessons = curriculum.get("daily_lessons", {})
    this_monday = today - timedelta(days=6)
    week_topics = [
        daily_lessons[k]
        for k in sorted(daily_lessons)
        if this_monday.isoformat() <= k <= today.isoformat()
    ]
    topics_str = ", ".join(week_topics) if week_topics else "None completed yet"
    scores_str = ", ".join("W" + k.split("_")[1] + ": " + str(v) + "%" for k, v in weekly_scores.items())

    review_prompt = "\n".join([
        "You are SkillCoach, a Cloud DevOps interview mentor for Harshit Shukla. Be encouraging but honest. Plain text only.",
        "",
        "It's Sunday! Generate a week review and next week plan.",
        "",
        "This week:",
        "- Topics covered: " + topics_str,
        "- Test score: " + str(test_score) + "/" + str(test_total) + " (" + str(test_pct) + "%)",
        "- All scores so far: " + (scores_str if scores_str else "First week"),
        "- User's preference for next week: " + (preference if preference else "None specified"),
        "",
        "Generate:",
        "",
        "WEEK " + str(week_num) + " SUMMARY",
        "[2 sentences: honest assessment of the score and what it means]",
        "",
        "WHAT WORKED",
        "[1-2 specific things]",
        "",
        "FOCUS FOR NEXT WEEK",
        "[2-3 sentences: what to prioritize and why]",
        "",
        "NEXT WEEK TOPICS (Mon-Sat)",
        "Mon: [Specific topic]",
        "Tue: [Specific topic]",
        "Wed: [Specific topic]",
        "Thu: [Specific topic]",
        "Fri: [Specific topic]",
        "Sat: [Review / Mock interview practice]",
        "",
        "MOTIVATION",
        "[1 short motivating sentence for the week ahead]",
    ])

    result = ai(review_prompt, 700)

    send(
        "Sunday Planning Time!\n\n"
        + result + "\n\n"
        + "Dashboard: " + DASHBOARD + "\n\n"
        + "Want to change next week's topics? Reply:\n"
        + "/nextweek <what you want>\n"
        + "E.g.: /nextweek focus more on Kubernetes"
    )

    # Parse Mon-Sat plan from result
    day_map = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5}
    new_plan = {}
    for line in result.split("\n"):
        for day, offset in day_map.items():
            if line.strip().startswith(day + ":"):
                topic = line.split(":", 1)[1].strip()
                if topic:
                    d = (next_monday + timedelta(days=offset)).isoformat()
                    new_plan[d] = topic

    # Fallback JSON plan if parsing failed
    if len(new_plan) < 4:
        days = [(next_monday + timedelta(days=i)).isoformat() for i in range(6)]
        fallback_prompt = "\n".join([
            "Return only valid JSON, no markdown, no explanation.",
            "",
            "Generate a 6-day Cloud DevOps learning plan starting " + next_monday.isoformat() + ".",
            "Previous: " + topics_str + ". Score: " + str(test_pct) + "%.",
            "Preference: " + (preference if preference else "continue logical progression"),
            "",
            "JSON only:",
            "{",
            '  "' + days[0] + '": "Topic",',
            '  "' + days[1] + '": "Topic",',
            '  "' + days[2] + '": "Topic",',
            '  "' + days[3] + '": "Topic",',
            '  "' + days[4] + '": "Topic",',
            '  "' + days[5] + '": "Weekly Review & Mock Practice"',
            "}",
        ])
        try:
            plan_result = ai(fallback_prompt, 350)
            new_plan = json.loads(plan_result[plan_result.find("{"):plan_result.rfind("}") + 1])
        except Exception:
            pass

    curriculum.setdefault("week_plan", {}).update(new_plan)
    curriculum["week_number"] = week_num + 1
    data["curriculum"] = curriculum
    data["next_week_preference"] = ""
    data["last_updated"] = datetime.now(IST).isoformat()
    push_data(data, sha, "Week " + str(week_num + 1) + " plan published")
    print("Next week plan published:", new_plan)


if __name__ == "__main__":
    main()
