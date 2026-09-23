import os
import json
import base64
import logging
import requests
from datetime import datetime, time
import pytz
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = "Harshit975shukla/skillcoach-dashboard"
GITHUB_FILE_PATH = "docs/data.json"
DASHBOARD_URL = "https://harshit975shukla.github.io/skillcoach-dashboard"
IST = pytz.timezone("Asia/Kolkata")
AUTHORIZED_CHAT_ID = int(os.environ.get("CHAT_ID", "0"))


# ── GitHub helpers ──────────────────────────────────────────────────────────

def _gh_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


def get_data():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    resp = requests.get(url, headers=_gh_headers(), timeout=15)
    resp.raise_for_status()
    raw = resp.json()
    content = base64.b64decode(raw["content"]).decode("utf-8")
    return json.loads(content), raw["sha"]


def push_data(data, sha, message="Bot: progress update"):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    encoded = base64.b64encode(json.dumps(data, indent=2).encode()).decode()
    resp = requests.put(
        url,
        headers=_gh_headers(),
        json={"message": message, "content": encoded, "sha": sha},
        timeout=20,
    )
    resp.raise_for_status()


def _is_authorized(update: Update) -> bool:
    if AUTHORIZED_CHAT_ID == 0:
        return True
    return update.effective_chat.id == AUTHORIZED_CHAT_ID


# ── Commands ────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        "👋 *SkillCoach Bot* — your interview prep mentor!\n\n"
        f"🔑 Your Chat ID: `{chat_id}`\n"
        "_(Save this — you'll need it in Render env vars)_\n\n"
        "Commands:\n"
        "🗂 /tasks — Open tasks\n"
        "🎯 /skills — Skill progress\n"
        "📊 /stats — Your stats\n"
        "✅ /complete task\\_001 — Mark task done\n"
        "📄 /resume — Resume feedback\n"
        "🔄 /publish — Sync dashboard\n"
        "❓ /help — Full help\n\n"
        f"📊 Dashboard: {DASHBOARD_URL}",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *SkillCoach Commands*\n\n"
        "/start — Welcome\n"
        "/tasks — Show all open tasks\n"
        "/skills — Skill breakdown with progress bars\n"
        "/stats — Overall completion stats\n"
        "/complete `<task_id>` — Mark a task as done (e.g. /complete task\\_001)\n"
        "/resume — Resume score and issues\n"
        "/publish — Push data.json to GitHub Pages\n"
        "/today — Tasks due today\n"
        "/streak — Current streak info\n\n"
        "💡 Tip: Daily reminders are sent at 9:00 AM IST automatically.",
        parse_mode="Markdown",
    )


async def cmd_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    await update.message.reply_text("Fetching tasks...")
    try:
        data, _ = get_data()
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to fetch data: {e}")
        return

    tasks = data.get("open_tasks", [])
    if not tasks:
        await update.message.reply_text("✅ No open tasks — great job!")
        return

    msg = f"📋 *Open Tasks* — {len(tasks)} remaining\n\n"
    for t in tasks[:15]:
        diff = t.get("difficulty", "medium")
        emoji = "🔴" if diff == "hard" else "🟡"
        skill = t.get("skill", "")
        est = t.get("estimated_time", "")
        task_id = t.get("id", "")
        title = t.get("title", "")[:55]
        msg += f"{emoji} `{task_id}` *{title}*\n"
        msg += f"   _{skill}_ · {est}\n\n"

    if len(tasks) > 15:
        msg += f"_...and {len(tasks) - 15} more. Check dashboard for full list._\n"

    msg += f"\n✅ Use `/complete task_id` to mark done"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    try:
        data, _ = get_data()
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")
        return

    today = datetime.now(IST).strftime("%Y-%m-%d")
    tasks = [t for t in data.get("open_tasks", []) if t.get("assigned_date", "") <= today]

    if not tasks:
        await update.message.reply_text("🎉 No tasks due today!")
        return

    msg = f"📅 *Tasks for Today ({today})*\n\n"
    for t in tasks[:10]:
        msg += f"• `{t['id']}` {t.get('title', '')[:50]}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_skills(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    try:
        data, _ = get_data()
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")
        return

    skills = data.get("skills_breakdown", {})
    if not skills:
        await update.message.reply_text("No skills data found.")
        return

    msg = "🎯 *Skills Breakdown*\n\n"
    for skill, info in skills.items():
        total = info.get("total", 0)
        done = info.get("completed", 0)
        pct = int((done / total) * 100) if total else 0
        filled = pct // 10
        bar = "█" * filled + "░" * (10 - filled)
        msg += f"*{skill}*\n`{bar}` {done}/{total} ({pct}%)\n\n"

    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    try:
        data, _ = get_data()
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")
        return

    s = data.get("statistics", {})
    msg = (
        "📊 *Your Progress*\n\n"
        f"✅ Completed: *{s.get('completed_tasks', 0)}*\n"
        f"📌 Pending: *{s.get('pending_tasks', s.get('total_tasks', 0))}*\n"
        f"🔥 Streak: *{s.get('streak', 0)} days*\n"
        f"📈 Rate: *{s.get('completion_rate', 0)}%*\n"
        f"⏱ Practice: *{s.get('practice_minutes', 0)} mins*\n"
        f"\n📊 [Dashboard]({DASHBOARD_URL})"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_streak(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    try:
        data, _ = get_data()
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")
        return

    s = data.get("statistics", {})
    streak = s.get("streak", 0)
    emoji = "🔥" if streak >= 3 else ("😐" if streak >= 1 else "💤")
    await update.message.reply_text(
        f"{emoji} *Current Streak: {streak} days*\n\n"
        f"Keep completing daily tasks to build your streak!\n"
        f"Use /complete to mark tasks done.",
        parse_mode="Markdown",
    )


async def cmd_complete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    if not ctx.args:
        await update.message.reply_text(
            "Usage: `/complete <task_id>`\nExample: `/complete task_001`\n\nUse /tasks to see task IDs.",
            parse_mode="Markdown",
        )
        return

    task_id = ctx.args[0].strip()
    await update.message.reply_text(f"Marking `{task_id}` as complete...", parse_mode="Markdown")

    try:
        data, sha = get_data()
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to fetch data: {e}")
        return

    open_tasks = data.get("open_tasks", [])
    completed_tasks = data.get("completed_tasks", [])

    task = next((t for t in open_tasks if t.get("id") == task_id), None)
    if not task:
        available = ", ".join(t["id"] for t in open_tasks[:5])
        await update.message.reply_text(
            f"❌ Task `{task_id}` not found.\n\nAvailable IDs (first 5): `{available}`\n\nUse /tasks to see all.",
            parse_mode="Markdown",
        )
        return

    # Move task to completed
    open_tasks.remove(task)
    task["completed_at"] = datetime.now(IST).isoformat()
    completed_tasks.append(task)

    # Update statistics
    stats = data.get("statistics", {})
    stats["completed_tasks"] = stats.get("completed_tasks", 0) + 1
    stats["pending_tasks"] = len(open_tasks)
    total = stats.get("total_tasks", len(open_tasks) + len(completed_tasks))
    stats["total_tasks"] = total
    stats["completion_rate"] = round((stats["completed_tasks"] / total) * 100, 1) if total else 0

    # Update activity timeline
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    timeline = data.get("activity_timeline", {})
    if today_str not in timeline:
        timeline[today_str] = {"completed": 0, "pending": 0}
    timeline[today_str]["completed"] = timeline[today_str].get("completed", 0) + 1
    timeline[today_str]["pending"] = len(open_tasks)

    # Update skills breakdown
    skill = task.get("skill", "")
    skills = data.get("skills_breakdown", {})
    if skill in skills:
        skills[skill]["completed"] = skills[skill].get("completed", 0) + 1

    # Update streak (simple: increment if completed at least one today)
    stats["streak"] = stats.get("streak", 0) + (1 if timeline[today_str]["completed"] == 1 else 0)

    data["open_tasks"] = open_tasks
    data["completed_tasks"] = completed_tasks
    data["statistics"] = stats
    data["activity_timeline"] = timeline
    data["skills_breakdown"] = skills
    data["last_updated"] = datetime.now(IST).isoformat()

    try:
        push_data(data, sha, f"Complete: {task_id} - {task.get('title', '')[:50]}")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to push to GitHub: {e}")
        return

    pct = stats["completion_rate"]
    done = stats["completed_tasks"]
    await update.message.reply_text(
        f"🎉 *Task Complete!*\n\n"
        f"`{task_id}` — {task.get('title', '')}\n\n"
        f"📊 Progress: *{done}/{total}* ({pct}%)\n"
        f"🔥 Streak: *{stats.get('streak', 0)} days*\n\n"
        f"Dashboard syncs in ~1-2 min 🚀",
        parse_mode="Markdown",
    )


async def cmd_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    try:
        data, _ = get_data()
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")
        return

    resume = data.get("resume_assessment", {})
    if not resume:
        await update.message.reply_text("No resume assessment data found.")
        return

    score = resume.get("score", "N/A")
    issues = resume.get("issues", [])
    strengths = resume.get("strengths", [])

    msg = f"📄 *Resume Assessment*\n\nScore: *{score}/100*\n\n"

    if strengths:
        msg += "✅ *Strengths:*\n"
        for s in strengths[:5]:
            msg += f"  • {s}\n"

    if issues:
        msg += "\n⚠️ *Issues to Fix:*\n"
        for issue in issues[:5]:
            msg += f"  • {issue}\n"

    msg += "\n💡 _Tip: Fix the issues above before your next interview submission._"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_publish(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    await update.message.reply_text("🔄 Syncing dashboard to GitHub Pages...")
    try:
        data, sha = get_data()
        data["last_synced"] = datetime.now(IST).isoformat()
        push_data(data, sha, "Dashboard sync via /publish")
        await update.message.reply_text(
            f"✅ *Synced!*\n\n"
            f"🔗 {DASHBOARD_URL}\n\n"
            f"_GitHub Pages may take 1–2 mins to reflect changes._",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Sync failed: {e}")


async def cmd_unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Unknown command. Use /help to see available commands.")


# ── Scheduled job ───────────────────────────────────────────────────────────

async def daily_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    if not AUTHORIZED_CHAT_ID:
        logging.warning("CHAT_ID not set — skipping daily reminder.")
        return
    try:
        data, _ = get_data()
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
        msg += (
            "\n💪 Consistent practice beats cramming — let's go!\n"
            "Use /tasks to see all • /complete to check off done"
        )
        await ctx.bot.send_message(AUTHORIZED_CHAT_ID, msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Daily reminder failed: {e}")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("tasks", cmd_tasks))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("skills", cmd_skills))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("streak", cmd_streak))
    app.add_handler(CommandHandler("complete", cmd_complete))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("publish", cmd_publish))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))

    # Daily reminder at 09:00 IST
    job_queue = app.job_queue
    ist_9am = time(hour=9, minute=0, tzinfo=IST)
    job_queue.run_daily(daily_reminder, time=ist_9am, name="daily_reminder")

    logging.info("SkillCoach bot started.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
