COMMANDS = {
    "start": "Home screen with quick buttons",
    "menu": "Home: your next step and quick buttons",
    "help": "All commands",
    "today": "Today's lesson, quiz and one-tap exercises",
    "quizzes": "Quizzes to finish (open until Sunday 23:59 IST)",
    "quiz": "<id|date> resume a quiz; saved answers kept",
    "q": "<A|B|C|D> answer the current question",
    "progress": "Study days, streak, quiz accuracy and lessons",
    "ask": "<question> ask the AI tutor",
    "dashboard": "Open your private dashboard",
    "tasks": "Open exercises, newest first",
    "complete": "<task_id> [minutes] mark an exercise done",
    "learn": "<topic> full lesson with video and exercises",
    "read": "<topic_id> read a stored lesson (not tracked)",
    "topics": "[module_id] Cloud/DevOps syllabus",
    "resources": "[search] free courses and guides",
    "labs": "Your labs and what is open",
    "lab": "<id> free scenario, code lab or AWS steps",
    "submitlab": "<id> <link> verify a lab",
    "labcleanup": "<id> <link> confirm AWS cleanup",
    "labcarry": "How unfinished required labs carry forward",
    "interview": "[topic] question-first graded interview (or 'next')",
    "mock": "[topic] sample Q&A, not a graded interview",
    "tip": "Interview practice tip",
    "onboard": "Guided setup and plan approval",
    "plan": "Review, approve or change your learning plan",
    "pace": "<15|30|45|60> session minutes (while revising)",
    "level": "<beginner|intermediate|advanced> (while revising)",
    "nextweek": "<preference> for the next unplanned week",
    "curriculum": "This week's personalized plan",
    "recoverlesson": "Recover unsent approved lesson parts",
    "setup": "Resume + JD/diagnostic setup; /cancel keeps your profile",
    "profile": "View profile, or /profile setup to replace it",
    "skip": "Skip the JD and start five diagnostic questions",
    "assess": "Reassess skills with five diagnostic questions",
    "score": "Evidence-based readiness (unavailable until assessed)",
    "gaps": "Private skill gaps",
    "resume": "Feedback on your actual stored resume",
    "updateresume": "Privately replace your resume",
    "updatejd": "Privately replace your job description",
    "request": "Your access status",
    "skills": "Exercise counts per skill, not inferred mastery",
    "stats": "Detailed practice counts",
    "streak": "Your study streak",
    "pause": "Pause scheduled coaching; commands still work",
    "unpause": "Enable future scheduled coaching (not /resume)",
    "cancel": "Cancel the current flow and failed work; history kept",
    "retry": "Retry failed operations and deliveries without regrading",
    "media": "<video|static>; animated video is the default",
    "voice": "<on|off> unavailable until a narrator is approved",
    "publish": "Queue an anonymous dashboard summary",
    "status": "Private pending/retry queue counts",
}

GROUPS = (
    ("Every day", ("menu", "today", "quizzes", "quiz", "q", "progress", "ask", "dashboard")),
    (
        "Practice",
        (
            "tasks",
            "complete",
            "learn",
            "read",
            "topics",
            "resources",
            "labs",
            "lab",
            "submitlab",
            "labcleanup",
            "labcarry",
            "interview",
            "mock",
            "tip",
        ),
    ),
    (
        "Plan and profile",
        (
            "onboard",
            "plan",
            "pace",
            "level",
            "nextweek",
            "curriculum",
            "recoverlesson",
            "setup",
            "profile",
            "skip",
            "assess",
            "score",
            "gaps",
            "resume",
            "updateresume",
            "updatejd",
            "request",
        ),
    ),
    (
        "Progress and settings",
        (
            "skills",
            "stats",
            "streak",
            "pause",
            "unpause",
            "cancel",
            "retry",
            "media",
            "voice",
            "publish",
            "status",
            "start",
            "help",
        ),
    ),
)


def help_text(*, admin=True):
    from skillcoach.access import ADMIN_COMMANDS

    lines = ["SkillCoach - your private learning space. Tap /menu for quick buttons."]
    for title, names in GROUPS:
        lines.append("\n" + title.upper())
        lines += [f"/{name} - {COMMANDS[name]}" for name in names if admin or name != "publish"]
    if admin:
        lines.append("\nOWNER ACCESS MANAGEMENT")
        lines += [f"/{name} - {description}" for name, description in ADMIN_COMMANDS.items()]
    lines.append(
        "\nPrivacy: owner sees access status, activity counts, delivery health and lesson-rating totals. "
        "With setup consent: approved catalog topics, controlled learning reasons and assessment summaries. "
        "Not private documents, answers or feedback."
    )
    return "\n".join(lines)
