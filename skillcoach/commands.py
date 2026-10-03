COMMANDS = {
    "start": "Home screen",
    "menu": "Home: next step and quick buttons",
    "help": "All commands",
    "today": "Today's lesson, quiz and one-tap exercises",
    "quizzes": "Quizzes to finish (open until Sunday 23:59 IST)",
    "quiz": "<id|date> resume a quiz; saved answers kept",
    "q": "<A|B|C|D> answer the current question",
    "review": "Spaced review of questions you met before",
    "progress": "Study days, streak, quiz accuracy and lessons",
    "ask": "<question> ask the AI tutor",
    "cert": "[exam|off] AWS, CKA/CKAD, Terraform or LFCS prep",
    "capstone": "[id] portfolio projects verified on GitHub",
    "submitcapstone": "<id> <repo link> verify a capstone",
    "portfolio": "[on|off|name <name>] opt-in public page",
    "dashboard": "Open your private dashboard",
    "tasks": "Open exercises, newest first",
    "complete": "<task_id> [minutes] mark an exercise done",
    "learn": "<topic> full lesson with video and exercises",
    "read": "<topic_id> read a stored lesson",
    "topics": "[module_id] Cloud/DevOps syllabus",
    "resources": "[search] free courses",
    "labs": "Your labs and what is open",
    "lab": "<id> start a lab",
    "submitlab": "<id> <link> verify a lab",
    "labcleanup": "<id> <link> confirm AWS cleanup",
    "labcarry": "How unfinished required labs carry forward",
    "interview": "[topic] graded interview (or 'next')",
    "mock": "[topic] sample Q&A (not graded)",
    "tip": "Interview practice tip",
    "onboard": "Guided setup and plan approval",
    "plan": "Review or change your plan",
    "pace": "<15|30|45|60> session minutes (while revising)",
    "level": "<beginner|intermediate|advanced> (while revising)",
    "nextweek": "<preference> for the next unplanned week",
    "curriculum": "This week's personalized plan",
    "recoverlesson": "Recover unsent approved lesson parts",
    "setup": "Resume + JD setup; /cancel keeps your profile",
    "profile": "View profile, or /profile setup to replace it",
    "skip": "Skip the JD, start diagnostics",
    "assess": "Reassess with five diagnostics",
    "score": "Evidence-based readiness",
    "gaps": "Private skill gaps",
    "resume": "Feedback on your stored resume",
    "updateresume": "Privately replace your resume",
    "updatejd": "Privately replace your job description",
    "request": "Your access status",
    "skills": "Exercise counts per skill",
    "stats": "Detailed practice counts",
    "streak": "Your study streak",
    "pause": "Pause scheduled coaching",
    "unpause": "Resume scheduled coaching (not /resume)",
    "cancel": "Cancel the current flow; history kept",
    "retry": "Retry failed work without regrading",
    "media": "<video|static> lesson media",
    "voice": "<on|off> narration (when available)",
    "publish": "Queue an anonymous dashboard summary",
    "status": "Private pending/retry queue counts",
    "privacy": "Privacy policy and how to ask about your data",
}

GROUPS = (
    ("Every day", ("menu", "today", "review", "quizzes", "quiz", "q", "progress", "ask", "dashboard")),
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
            "cert",
            "capstone",
            "submitcapstone",
            "portfolio",
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
            "privacy",
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
        "\nPrivacy: the admin pages show the owner access, activity counts, delivery health and rating "
        "totals; with consent, catalog topics and assessment summaries, never your documents, answers or "
        "feedback. AI coaching uses Groq. Full policy: /privacy"
    )
    return "\n".join(lines)
