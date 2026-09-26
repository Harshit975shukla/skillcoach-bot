COMMANDS = {
    "start": "Welcome and help",
    "help": "All supported commands",
    "setup": "Start resume + JD/diagnostic setup; /cancel keeps your existing profile",
    "profile": "View profile, or /profile setup to replace it",
    "skip": "Skip JD and start five diagnostic questions",
    "assess": "Reassess skills with five diagnostic questions",
    "score": "Evidence-based readiness (unavailable until assessed)",
    "gaps": "Private skill gaps",
    "curriculum": "This week's personalized plan",
    "nextweek": "<preference> for the next unplanned week",
    "learn": "<topic> full lesson with tracked tasks and animated diagrams",
    "ask": "<question> personalized coaching",
    "mock": "[topic] sample Q&A, not a graded interview",
    "interview": "[topic] question-first interview (or 'next' for another round)",
    "tip": "Interview practice tip",
    "q": "<A|B|C|D> answer the currently displayed question",
    "tasks": "Open tasks and stable completion IDs",
    "today": "Tasks due today",
    "complete": "<task_id> [actual_minutes] complete once; omitted minutes are not estimated as practice",
    "skills": "Completed task counts, not inferred mastery",
    "stats": "Task and interview progress",
    "streak": "Consecutive IST practice days",
    "resume": "Feedback on your actual stored resume",
    "pause": "Suppress scheduled coaching; manual commands still work",
    "unpause": "Enable future scheduled coaching (not /resume)",
    "cancel": "Cancel current flow and failed work, preserving completed history",
    "retry": "Retry failed operations and deliveries without regrading",
    "media": "<video|static>; animated video is the default",
    "voice": "<on|off> narration preference; voice stays unavailable until a replacement is approved",
    "topics": "[module_id] browse the versioned Cloud/DevOps syllabus",
    "publish": "Queue an anonymous dashboard summary",
    "dashboard": "Open your authenticated private learner dashboard",
    "status": "Private pending/retry queue counts",
}


def help_text(*, admin=True):
    from skillcoach.access import ADMIN_COMMANDS

    commands = {key: value for key, value in COMMANDS.items() if admin or key != "publish"}
    text = "SkillCoach - your private learning space\n\n" + "\n".join(
        f"/{name} - {desc}" for name, desc in commands.items()
    )
    if admin:
        text += "\n\nOWNER ACCESS MANAGEMENT\n" + "\n".join(
            f"/{name} - {description}" for name, description in ADMIN_COMMANDS.items()
        )
    return text
