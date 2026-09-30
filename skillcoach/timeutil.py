from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
# Late-night study belongs to the day the learner is finishing, not the next one.
STUDY_DAY_START = timedelta(hours=4)
WEEKLY_GOAL = 4
MILESTONES = (3, 7, 14, 30, 60, 100)


def now_ist() -> datetime:
    return datetime.now(IST)


def study_day(moment: datetime) -> date:
    return (moment.astimezone(IST) - STUDY_DAY_START).date()


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_key(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02}"


def requested_quiz_payload(current: datetime, due: datetime, topic: str):
    if due.tzinfo is None or due.utcoffset() is None:
        raise ValueError("Quiz due time must include a timezone.")
    due = due.astimezone(IST)
    current = current.astimezone(IST)
    if due <= current or (due - current).total_seconds() > 7 * 86400:
        raise ValueError("Quiz due time must be in the future, within seven days.")
    topic = topic.strip()
    if not topic or len(topic) > 300:
        raise ValueError("A topic of 1-300 characters is required.")
    return due, {
        "type": "schedule",
        "kind": "quiz",
        "date": due.date().isoformat(),
        "requested_topic": topic,
        "requested_due_at": due.isoformat(),
    }


def streak(dates: list[date], today: date) -> int:
    """Consecutive study days. Sundays are rest days and one missed day per ISO week is forgiven.

    Rest and forgiven days keep the streak alive but never add to it.
    """
    active = set(dates)
    if not active:
        return 0
    cursor = today if today in active else today - timedelta(days=1)
    earliest = min(active)
    count, forgiven = 0, set()
    while cursor >= earliest:
        if cursor in active:
            count += 1
        elif cursor.weekday() != 6:
            week = cursor.isocalendar()[:2]
            if week in forgiven:
                break
            forgiven.add(week)
        cursor -= timedelta(days=1)
    return count
