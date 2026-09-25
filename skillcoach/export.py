from datetime import datetime, timedelta

from skillcoach.models import State
from skillcoach.timeutil import IST, streak

TOPICS = {
    "ec2": "EC2",
    "vpc": "VPC",
    "iam": "IAM",
    "s3": "S3",
    "rds": "RDS",
    "lambda": "Lambda",
    "aws": "AWS",
    "kubernetes": "Kubernetes",
    "terraform": "Terraform",
    "docker": "Docker",
    "cicd": "CI/CD",
    "ci/cd": "CI/CD",
    "python": "Python",
    "observability": "Observability",
    "prometheus": "Observability",
    "genai": "AI fundamentals",
}


def public_skill(value: str) -> str:
    # Exact matches only: arbitrary user-derived labels never become public display strings.
    return TOPICS.get(value.casefold().strip(), "General practice")


def stats(state: State, now: datetime) -> dict:
    tasks = list(state.tasks.values())
    done = sum(t.status == "done" for t in tasks)
    graded = [i.feedback.score for i in state.interviews.values() if i.status == "completed" and i.feedback]
    return {
        "done": done,
        "streak": streak(state.activity, now.astimezone(IST).date()),
        "pending": sum(t.status == "pending" for t in tasks),
        "minutes_practiced": sum(t.actual_minutes for t in tasks if t.status == "done"),
        "answers_graded": len(graded),
        "avg_answer_score": round(sum(graded) / len(graded), 1) if graded else None,
        "completion_rate": round(100 * done / len(tasks), 1) if tasks else 0,
        "total": len(tasks),
    }


def skill_summary(state: State, *, public: bool = True) -> list[dict]:
    skills = {}
    for task in state.tasks.values():
        skill = public_skill(task.skill) if public else task.skill
        item = skills.setdefault(skill, {"skill": skill, "done": 0, "total": 0})
        item["total"] += 1
        item["done"] += int(task.status == "done")
    return sorted(skills.values(), key=lambda x: x["skill"])


def public_export(state: State, now: datetime) -> dict:
    today = now.astimezone(IST).date()
    tasks = sorted(state.tasks.values(), key=lambda t: (t.assigned_date, t.id))
    open_tasks, recent_done = [], []
    for index, task in enumerate(tasks, 1):
        if task.status == "pending":
            open_tasks.append(
                {
                    "id": index,
                    "title": "Private learning task",
                    "detail": "",
                    "skill": public_skill(task.skill),
                    "difficulty": "medium",
                    "est_minutes": task.estimated_minutes,
                    "overdue_days": max(0, (today - task.assigned_date).days),
                }
            )
        elif task.status == "done":
            recent_done.append(
                {
                    "title": "Private learning task",
                    "skill": public_skill(task.skill),
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                }
            )
    activity = []
    for offset in range(29, -1, -1):
        day = today - timedelta(days=offset)
        activity.append(
            {
                "date": day.isoformat(),
                "done": sum(
                    t.status == "done"
                    and t.completed_at is not None
                    and t.completed_at.astimezone(IST).date() == day
                    for t in tasks
                ),
                "pending": sum(t.status == "pending" and t.assigned_date == day for t in tasks),
                "skipped": sum(t.status == "skipped" and t.assigned_date == day for t in tasks),
            }
        )
    interviews = sorted(
        [i for i in state.interviews.values() if i.status == "completed" and i.feedback and i.completed_at],
        key=lambda i: i.completed_at,
        reverse=True,
    )
    return {
        "schema_version": 1,
        "profile": {
            "name": "Learner",
            "target_role": "Technical interview practice",
            "level": "Private",
            "reminder": "09:00 weekdays",
            "timezone": "Asia/Kolkata",
            "paused": state.paused,
        },
        "stats": stats(state, now),
        "activity": activity,
        "skills": skill_summary(state),
        "open_tasks": open_tasks,
        "recent_done": sorted(recent_done, key=lambda t: t["completed_at"] or "", reverse=True)[:10],
        "recent_answers": [
            {
                "score": i.feedback.score,
                "created_at": i.completed_at.isoformat(),
                "question": "Private interview practice",
                "feedback": "",
            }
            for i in interviews[:10]
        ],
        "resume": None,
        "generated_at": now.isoformat(),
    }
