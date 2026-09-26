from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    return datetime.now(IST)


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
    active = set(dates)
    cursor = today if today in active else today - timedelta(days=1)
    count = 0
    while cursor in active:
        count += 1
        cursor -= timedelta(days=1)
    return count
