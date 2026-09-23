"""Run by GitHub Actions every day at 9 AM IST."""
import json
import base64
import os
import requests
import pytz
from datetime import datetime

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
IST = pytz.timezone("Asia/Kolkata")

headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
url = "https://api.github.com/repos/Harshit975shukla/skillcoach-dashboard/contents/docs/data.json"

resp = requests.get(url, headers=headers, timeout=15)
resp.raise_for_status()
data = json.loads(base64.b64decode(resp.json()["content"]).decode())

tasks = data.get("open_tasks", [])
stats = data.get("statistics", {})
streak = stats.get("streak", 0)
streak_line = f"🔥 Streak: *{streak} days* — keep it going!" if streak > 0 else "💤 No streak yet — start one today!"

msg = (
    "🌅 *Good Morning, Harshit!*\n\n"
    f"📋 *{len(tasks)} tasks* waiting for you\n"
    f"{streak_line}\n\n"
    "*Today's recommended tasks:*\n"
)
for t in tasks[:3]:
    msg += f"  • `{t['id']}` {t.get('title', '')[:50]}\n"

msg += "\n💪 Consistent practice beats cramming — let's go!\nUse /tasks • /complete to check off done"

requests.post(
    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
    json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"},
    timeout=10,
)
print(f"Reminder sent at {datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}")
