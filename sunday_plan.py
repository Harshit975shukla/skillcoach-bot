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


def nvidia(system, prompt, max_tokens=800):
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


def main():
    data, sha = get_data()
    today = date.today()
    next_monday = today + timedelta(days=1)

    curriculum = data.get("curriculum", {})
    test_state = data.get("test_state", {})
    weekly_scores = data.get("weekly_scores", {})
    preference = data.get("next_week_preference", "")
    week_num = curriculum.get("week_number", 1)

    # Calculate test score
    test_questions = test_state.get("questions", [])
    test_score = test_state.get("score", 0)
    test_total = len(test_questions) if test_questions else 10
    test_pct = round((test_score / test_total) * 100) if test_total else 0

    weekly_scores[f"week_{week_num}"] = test_pct
    data["weekly_scores"] = weekly_scores

    # This week's topics
    daily_lessons = curriculum.get("daily_lessons", {})
    this_monday = today - timedelta(days=6)
    week_topics = [daily_lessons[k] for k in sorted(daily_lessons)
                   if this_monday.isoformat() <= k <= today.isoformat()]

    topics_str = ", ".join(week_topics) if week_topics else "None completed yet"
    scores_str = ", ".join(f"W{k.split('_')[1]}: {v}%" for k, v in weekly_scores.items())

    # Generate review + next week plan (one NVIDIA call)
    result = nvidia(
        "You are SkillCoach, a Cloud DevOps interview mentor for Harshit Shukla. "
        "Be encouraging but honest. Plain text only.",
        f"""It's Sunday! Generate a week review and next week plan.

This week:
- Topics covered: {topics_str}
- Test score: {test_score}/{test_total} ({test_pct}%)
- All scores so far: {scores_str if scores_str else 'First week'}
- User's preference for next week: {preference if preference else 'None specified'}

Generate:

WEEK {week_num} SUMMARY
[2 sentences: honest assessment of the score and what it means]

WHAT WORKED
[1-2 specific things]

FOCUS FOR NEXT WEEK
[2-3 sentences: what to prioritize and why, based on score + progression]

NEXT WEEK TOPICS (Mon-Sat)
Mon: [Specific topic]
Tue: [Specific topic]
Wed: [Specific topic]
Thu: [Specific topic]
Fri: [Specific topic]
Sat: [Review / Mock interview practice]

MOTIVATION
[1 short motivating sentence for the week ahead]""",
        max_tokens=700,
    )

    send(f"Sunday Planning Time!\n\n{result}\n\nDashboard: {DASHBOARD}\n\nWant to change next week's topics? Reply /nextweek <what you want>\nE.g.: /nextweek focus more on Kubernetes and less on AWS")

    # Parse Mon-Sat plan from the result
    day_map = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5}
    new_plan = {}
    for line in result.split("\n"):
        for day, offset in day_map.items():
            if line.strip().startswith(f"{day}:"):
                topic = line.split(":", 1)[1].strip()
                if topic:
                    d = (next_monday + timedelta(days=offset)).isoformat()
                    new_plan[d] = topic

    # Fallback if parsing failed
    if len(new_plan) < 4:
        plan_json = nvidia(
            "Return only valid JSON, no markdown, no explanation.",
            f"""Generate a 6-day learning plan starting {next_monday.isoformat()}.
Previous: {topics_str}. Score: {test_pct}%. Preference: {preference if preference else 'continue progression'}.

JSON only:
{{
  "{next_monday.isoformat()}": "Topic",
  "{(next_monday+timedelta(days=1)).isoformat()}": "Topic",
  "{(next_monday+timedelta(days=2)).isoformat()}": "Topic",
  "{(next_monday+timedelta(days=3)).isoformat()}": "Topic",
  "{(next_monday+timedelta(days=4)).isoformat()}": "Topic",
  "{(next_monday+timedelta(days=5)).isoformat()}": "Weekly Review & Mock Practice"
}}""",
            max_tokens=350,
        )
        try:
            new_plan = json.loads(plan_json[plan_json.find("{"):plan_json.rfind("}") + 1])
        except Exception:
            pass

    # Update data
    curriculum.setdefault("week_plan", {}).update(new_plan)
    curriculum["week_number"] = week_num + 1
    data["curriculum"] = curriculum
    data["next_week_preference"] = ""
    data["last_updated"] = datetime.now(IST).isoformat()
    push_data(data, sha, f"Week {week_num + 1} plan published")
    print(f"Next week plan published: {new_plan}")


if __name__ == "__main__":
    main()
