COMMANDS = {
    "start": "Welcome and help",
    "help": "All supported commands",
    "setup": "Resume + JD/diagnostic setup; /cancel keeps your profile",
    "onboard": "Guided setup: five diagnostics, optional documents, plan approval",
    "plan": "Review, approve or revise your current learning plan",
    "pace": "<15|30|45|60> set the time target while revising your plan",
    "level": "<beginner|intermediate|advanced> set difficulty while revising your plan",
    "request": "Your access status; new requests need admission enabled",
    "profile": "View profile, or /profile setup to replace it",
    "skip": "Skip JD and start five diagnostic questions",
    "assess": "Reassess skills with five diagnostic questions",
    "score": "Evidence-based readiness (unavailable until assessed)",
    "gaps": "Private skill gaps",
    "curriculum": "This week's personalized plan",
    "nextweek": "<preference> for the next unplanned week",
    "learn": "<topic> lesson, video and tracked exercises",
    "read": "<topic_id> read a stored lesson, without tracking",
    "ask": "<question> personalized coaching",
    "mock": "[topic] sample Q&A, not a graded interview",
    "interview": "[topic] question-first interview (or 'next' for another round)",
    "tip": "Interview practice tip",
    "q": "<A|B|C|D> answer the currently displayed question",
    "quizzes": "Daily catch-up until Sunday 23:59 IST",
    "quiz": "<id|date> resume saved answers",
    "tasks": "Open tasks and stable completion IDs",
    "today": "Tasks due today",
    "complete": "<task_id> [minutes] complete once; logged time only",
    "skills": "Completed task counts, not inferred mastery",
    "stats": "Task and interview progress",
    "streak": "Consecutive IST practice days",
    "resume": "Feedback on your actual stored resume",
    "updateresume": "Privately replace/add resume text; confirm keep plan or propose future changes",
    "updatejd": "Privately replace/add job description without resetting learning",
    "recoverlesson": "Recover unsent approved lesson parts",
    "labs": "Your labs and what is pending",
    "lab": "<id> free scenario, code lab or AWS steps",
    "submitlab": "<id> <link> verify a lab",
    "labcleanup": "<id> <link> confirm AWS cleanup",
    "labcarry": "Carry required labs (once per 28 days)",
    "pause": "Suppress scheduled coaching; manual commands still work",
    "unpause": "Enable future scheduled coaching (not /resume)",
    "cancel": "Cancel current flow and failed work, preserving completed history",
    "retry": "Retry failed operations and deliveries without regrading",
    "media": "<video|static>; animated video is the default",
    "voice": "<on|off> unavailable until a replacement narrator is approved",
    "topics": "[module_id] Cloud/DevOps syllabus",
    "resources": "[search] free links; --page 2 for more",
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
    return (
        text + "\n\nPrivacy: owner sees access status, activity counts, delivery health and lesson-rating totals. "
        "With setup consent: approved catalog topics, controlled learning reasons and assessment summaries. "
        "Not private documents, answers or feedback."
    )
