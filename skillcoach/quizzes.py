"""Shared daily catch-up catalogue; never exposes questions or answer keys."""

import re
from datetime import datetime, time, timedelta

from skillcoach.timeutil import IST, monday

QUIZ_ID = re.compile(r"(?:[a-f0-9]{20}|\d{4}-\d{2}-\d{2})\Z")


def deadline(day, kind="daily"):
    end = monday(day) + timedelta(days=7) if kind == "daily" else day + timedelta(days=1)
    return datetime.combine(end, time(), IST)


def is_open(session, now):
    return session.date <= now.astimezone(IST).date() and now < deadline(session.date, session.kind)


def catalogue(state, now):
    today = now.astimezone(IST).date()
    lessons = {}
    for lesson in state.lessons.values():
        if lesson.get("delivered_at") and lesson.get("date") and lesson["date"] <= today.isoformat():
            lessons.setdefault(lesson["date"], []).append(lesson["topic"])
    entries = []
    assigned = set()
    for session in state.assessments.values():
        if session.kind != "daily":
            continue
        day = session.date.isoformat()
        assigned.add(day)
        completed = session.status == "completed"
        available = not completed and is_open(session, now)
        entries.append(
            {
                "id": session.id,
                "date": day,
                "title": ", ".join(dict.fromkeys(lessons.get(day) or [q.topic for q in session.questions])),
                "status": "completed"
                if completed
                else (
                    "in_progress"
                    if available and session.answers
                    else "not_started"
                    if available
                    else "expired"
                ),
                "answered": len(session.answers),
                "total": len(session.questions),
                "score": sum(a.correct for a in session.answers) if completed else None,
                "can_resume": available,
                "deadline": deadline(session.date).isoformat(),
            }
        )
    for day, topics in lessons.items():
        if day in assigned:
            continue
        parsed = datetime.strptime(day, "%Y-%m-%d").date()
        available = now < deadline(parsed)
        entries.append(
            {
                "id": day,
                "date": day,
                "title": ", ".join(dict.fromkeys(topics)),
                "status": "not_started" if available else "expired",
                "answered": 0,
                "total": 5,
                "score": None,
                "can_resume": available,
                "deadline": deadline(parsed).isoformat(),
            }
        )
    return sorted(entries, key=lambda item: (item["can_resume"], item["date"], item["id"]), reverse=True)
