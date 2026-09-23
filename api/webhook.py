import json
import os
import base64
import requests
from datetime import datetime
import pytz
from http.server import BaseHTTPRequestHandler

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = "Harshit975shukla/skillcoach-dashboard"
GITHUB_FILE_PATH = "docs/data.json"
DASHBOARD_URL = "https://harshit975shukla.github.io/skillcoach-dashboard"
IST = pytz.timezone("Asia/Kolkata")
AUTHORIZED_CHAT_ID = int(os.environ.get("CHAT_ID", "0"))


def send_msg(chat_id, text):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        timeout=10,
    )


def _gh_headers():
    return {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}


def get_data():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    resp = requests.get(url, headers=_gh_headers(), timeout=15)
    resp.raise_for_status()
    raw = resp.json()
    return json.loads(base64.b64decode(raw["content"]).decode()), raw["sha"]


def push_data(data, sha, message="Bot: progress update"):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    encoded = base64.b64encode(json.dumps(data, indent=2).encode()).decode()
    requests.put(url, headers=_gh_headers(), json={"message": message, "content": encoded, "sha": sha}, timeout=20).raise_for_status()


def handle(chat_id, text):
    parts = text.strip().split()
    cmd = parts[0].split("@")[0].lower()
    args = parts[1:]

    if cmd == "/start":
        send_msg(chat_id,
            f"👋 *SkillCoach Bot* — your interview prep mentor\\!\n\n"
            f"🔑 Your Chat ID: `{chat_id}`\n"
            f"_(Add this as CHAT\\_ID in Vercel env vars)_\n\n"
            "Commands:\n"
            "🗂 /tasks — Open tasks\n"
            "🎯 /skills — Skill progress\n"
            "📊 /stats — Your stats\n"
            "✅ /complete task\\_001 — Mark task done\n"
            "📄 /resume — Resume feedback\n"
            f"🔄 /publish — Sync dashboard\n\n"
            f"📊 Dashboard: {DASHBOARD_URL}")

    elif cmd == "/help":
        send_msg(chat_id,
            "📖 *Commands*\n\n"
            "/tasks — All open tasks\n"
            "/today — Tasks due today\n"
            "/skills — Skill progress bars\n"
            "/stats — Completion stats\n"
            "/streak — Current streak\n"
            "/complete `<task_id>` — Mark done\n"
            "/resume — Resume feedback\n"
            "/publish — Sync dashboard")

    elif cmd == "/tasks":
        try:
            data, _ = get_data()
            tasks = data.get("open_tasks", [])
            if not tasks:
                send_msg(chat_id, "✅ No open tasks — great job!")
                return
            msg = f"📋 *Open Tasks* — {len(tasks)} remaining\n\n"
            for t in tasks[:15]:
                emoji = "🔴" if t.get("difficulty") == "hard" else "🟡"
                msg += f"{emoji} `{t['id']}` *{t.get('title','')[:50]}*\n   _{t.get('skill','')}_ · {t.get('estimated_time','')}\n\n"
            if len(tasks) > 15:
                msg += f"_...and {len(tasks)-15} more_\n"
            msg += "\nUse `/complete task_id` to mark done"
            send_msg(chat_id, msg)
        except Exception as e:
            send_msg(chat_id, f"❌ Error: {e}")

    elif cmd == "/today":
        try:
            data, _ = get_data()
            today = datetime.now(IST).strftime("%Y-%m-%d")
            tasks = [t for t in data.get("open_tasks", []) if t.get("assigned_date", "") <= today]
            if not tasks:
                send_msg(chat_id, "🎉 No tasks due today!")
                return
            msg = f"📅 *Due Today ({today})*\n\n"
            for t in tasks[:10]:
                msg += f"• `{t['id']}` {t.get('title','')[:50]}\n"
            send_msg(chat_id, msg)
        except Exception as e:
            send_msg(chat_id, f"❌ Error: {e}")

    elif cmd == "/skills":
        try:
            data, _ = get_data()
            skills = data.get("skills_breakdown", {})
            msg = "🎯 *Skills Breakdown*\n\n"
            for skill, info in skills.items():
                total = info.get("total", 0)
                done = info.get("completed", 0)
                pct = int((done / total) * 100) if total else 0
                bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
                msg += f"*{skill}*\n`{bar}` {done}/{total} ({pct}%)\n\n"
            send_msg(chat_id, msg)
        except Exception as e:
            send_msg(chat_id, f"❌ Error: {e}")

    elif cmd == "/stats":
        try:
            data, _ = get_data()
            s = data.get("statistics", {})
            send_msg(chat_id,
                f"📊 *Your Progress*\n\n"
                f"✅ Completed: *{s.get('completed_tasks', 0)}*\n"
                f"📌 Pending: *{s.get('pending_tasks', s.get('total_tasks', 0))}*\n"
                f"🔥 Streak: *{s.get('streak', 0)} days*\n"
                f"📈 Rate: *{s.get('completion_rate', 0)}%*\n"
                f"⏱ Practice: *{s.get('practice_minutes', 0)} mins*")
        except Exception as e:
            send_msg(chat_id, f"❌ Error: {e}")

    elif cmd == "/streak":
        try:
            data, _ = get_data()
            streak = data.get("statistics", {}).get("streak", 0)
            emoji = "🔥" if streak >= 3 else ("😐" if streak >= 1 else "💤")
            send_msg(chat_id, f"{emoji} *Streak: {streak} days*\n\nUse /complete daily to build it!")
        except Exception as e:
            send_msg(chat_id, f"❌ Error: {e}")

    elif cmd == "/complete":
        if not args:
            send_msg(chat_id, "Usage: `/complete task_001`\n\nUse /tasks to see task IDs.")
            return
        task_id = args[0].strip()
        try:
            data, sha = get_data()
            open_tasks = data.get("open_tasks", [])
            completed_tasks = data.get("completed_tasks", [])
            task = next((t for t in open_tasks if t.get("id") == task_id), None)
            if not task:
                ids = ", ".join(t["id"] for t in open_tasks[:5])
                send_msg(chat_id, f"❌ Task `{task_id}` not found.\n\nFirst 5 IDs: `{ids}`")
                return

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

            data.update({
                "open_tasks": open_tasks,
                "completed_tasks": completed_tasks,
                "statistics": stats,
                "activity_timeline": timeline,
                "skills_breakdown": skills,
                "last_updated": datetime.now(IST).isoformat(),
            })

            push_data(data, sha, f"Complete: {task_id}")
            send_msg(chat_id,
                f"🎉 *Task Complete!*\n\n"
                f"`{task_id}` — {task.get('title','')}\n\n"
                f"📊 Progress: *{stats['completed_tasks']}/{total}* ({stats['completion_rate']}%)\n"
                f"🔥 Streak: *{stats.get('streak', 0)} days*\n\n"
                f"Dashboard syncs in ~1 min 🚀")
        except Exception as e:
            send_msg(chat_id, f"❌ Error: {e}")

    elif cmd == "/resume":
        try:
            data, _ = get_data()
            resume = data.get("resume_assessment", {})
            score = resume.get("score", "N/A")
            issues = resume.get("issues", [])
            strengths = resume.get("strengths", [])
            msg = f"📄 *Resume Assessment*\n\nScore: *{score}/100*\n\n"
            if strengths:
                msg += "✅ *Strengths:*\n" + "".join(f"  • {s}\n" for s in strengths[:5])
            if issues:
                msg += "\n⚠️ *Issues to Fix:*\n" + "".join(f"  • {i}\n" for i in issues[:5])
            send_msg(chat_id, msg)
        except Exception as e:
            send_msg(chat_id, f"❌ Error: {e}")

    elif cmd == "/publish":
        try:
            data, sha = get_data()
            data["last_synced"] = datetime.now(IST).isoformat()
            push_data(data, sha, "Dashboard sync via /publish")
            send_msg(chat_id, f"✅ *Synced!*\n\n🔗 {DASHBOARD_URL}\n\n_GitHub Pages updates in 1–2 mins._")
        except Exception as e:
            send_msg(chat_id, f"❌ Sync failed: {e}")

    else:
        send_msg(chat_id, "Unknown command. Use /help")


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            update = json.loads(body)
            msg = update.get("message") or update.get("edited_message", {})
            chat_id = msg.get("chat", {}).get("id")
            text = msg.get("text", "")
            if chat_id and text.startswith("/"):
                if not AUTHORIZED_CHAT_ID or chat_id == AUTHORIZED_CHAT_ID:
                    handle(chat_id, text)
        except Exception:
            pass
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"SkillCoach Bot is running.")

    def log_message(self, *args):
        pass
