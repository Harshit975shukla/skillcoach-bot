"""Owner-only adoption and retention analytics. Counts and dates only: never questions, answers,
documents, free text or message content."""

import logging
import re
from collections import Counter, defaultdict
from datetime import date, timedelta

from skillcoach.timeutil import IST, study_day

log = logging.getLogger(__name__)
WINDOW_DAYS = 7
IDLE_AT_RISK = 2
USAGE_EVENTS = ("dashboard_open", "lesson_page", "course_page")
FEATURES = {
    "button:ex": "Exercise buttons in chat",
    "exercise": "Exercise taps on the dashboard",
    "button:qnow": "Quiz me now",
    "button:quiz": "Catch-up quiz buttons",
    "/quizzes": "Catch-up quiz list",
    "button:review": "Spaced review",
    "/review": "Spaced review",
    "button:practice": "Practise my mistakes",
    "button:explain": "Explain it differently",
    "button:helpplan": "Explain it differently",
    "button:understand": "I understand",
    "button:lf": "Lesson feedback",
    "/menu": "Home menu",
    "button:home": "Home menu",
    "/today": "Today view",
    "/progress": "Progress view",
    "/ask": "AI tutor",
    "button:nudge": "Re-engagement replies",
    "/dashboard": "Dashboard link",
    "dashboard_open": "Dashboard opens",
    "lesson_page": "Lesson page opens",
    "course_page": "Library lesson opens",
    "/labs": "Labs",
    "button:lab": "Labs",
    "button:ls": "Lab scenarios",
    "/interview": "Interview practice",
    "/cert": "Certification practice",
    "button:cert": "Certification practice",
    "/capstone": "Capstone projects",
    "/submitcapstone": "Capstone submissions",
    "/portfolio": "Public portfolio",
}
COMMAND = re.compile(r"\s*(/[a-z]+)")


def action_of(payload):
    """A feature key from a job payload, never including arguments or typed text."""
    if payload.get("type") == "exercise":
        return "exercise"
    if payload.get("type") != "telegram":
        return None
    callback = payload.get("callback")
    if isinstance(callback, str):
        return "button:" + callback.split(":", 1)[0]
    match = COMMAND.match(payload.get("text") or "")
    return match.group(1).lower() if match else None


def weekday_gap(last, today):
    """Mon-Sat days strictly between the last study day and today; Sundays are rest days."""
    if last is None:
        return None
    day, gap = last + timedelta(days=1), 0
    while day < today:
        gap += day.weekday() != 6
        day += timedelta(days=1)
    return gap


def since_resume(state, last):
    """Count missed days from the later of `last` and the day coaching resumed after a pause."""
    if state.resumed_at is None:
        return last
    anchor = study_day(state.resumed_at) - timedelta(days=1)
    return anchor if last is None else max(last, anchor)


def adoption(runtime):
    from pydantic import ValidationError

    from skillcoach.models import State
    from skillcoach.progress import summary
    from skillcoach.quizzes import catalogue
    from skillcoach.review import review_summary

    now = runtime.clock()
    today = study_day(now)
    since = now - timedelta(days=WINDOW_DAYS)
    with runtime.repo.connection() as conn:
        rows = conn.execute(
            "SELECT l.id,l.display_name,l.status,l.joined_at,c.body FROM learners l "
            "JOIN coach_state c ON c.learner_id=l.id ORDER BY l.joined_at,l.id LIMIT 100"
        ).fetchall()
        jobs = conn.execute(
            "SELECT learner_id,payload FROM jobs WHERE created_at>%s AND payload->>'type' IN ('telegram','exercise')",
            (since,),
        ).fetchall()
        usage = conn.execute(
            "SELECT learner_id,event,sum(count) AS n FROM usage_daily WHERE day>%s GROUP BY learner_id,event",
            (today - timedelta(days=WINDOW_DAYS),),
        ).fetchall()
    uses, users = Counter(), defaultdict(set)
    for job in jobs:
        label = FEATURES.get(action_of(job["payload"]) or "")
        if label:
            uses[label] += 1
            users[label].add(job["learner_id"])
    for row in usage:
        label = FEATURES[row["event"]]
        uses[label] += int(row["n"])
        users[label].add(row["learner_id"])

    funnel = Counter()
    stages = (
        ("joined", "Joined or requested access"),
        ("approved", "Approved"),
        ("onboarded", "Finished setup"),
        ("planned", "Plan started"),
        ("lesson", "First lesson received"),
        ("quiz", "First quiz answered"),
        ("habit", "3+ study days in first week"),
    )
    retention_rows, at_risk = [], []
    for row in rows:
        name = "You (owner)" if row["id"] == "owner" else row["display_name"] or "Learner"
        funnel["joined"] += 1
        if row["status"] != "active":
            continue
        funnel["approved"] += 1
        try:
            state = State.model_validate(row["body"])
        except ValidationError:
            continue
        j = state.journey
        if state.profile or (j and j.consent_at):
            funnel["onboarded"] += 1
        if (j and j.active_id) or (not j and state.profile):
            funnel["planned"] += 1
        delivered = sorted(
            r["date"] for r in state.lessons.values() if r.get("delivered_at") and r.get("date")
        )
        answered = [a for s in state.assessments.values() if s.kind in ("daily", "weekly") for a in s.answers]
        if delivered:
            funnel["lesson"] += 1
        if answered:
            funnel["quiz"] += 1
        activity = sorted(set(state.activity))
        joined = study_day(row["joined_at"])
        if delivered:
            start = min(joined, date.fromisoformat(delivered[0]))
            if sum(start <= d < start + timedelta(days=7) for d in activity) >= 3:
                funnel["habit"] += 1
        weeks = []
        for week in range(4):
            begin = joined + timedelta(days=7 * week)
            weeks.append(
                None if begin > today else any(begin <= d < begin + timedelta(days=7) for d in activity)
            )
        retention_rows.append({"id": row["id"], "name": name, "weeks": weeks})
        if state.paused:
            continue
        last = activity[-1] if activity else None
        gap = weekday_gap(since_resume(state, last or joined - timedelta(days=1)), today)
        progress = summary(state, now)
        open_quizzes = sum(q["can_resume"] and q["status"] != "completed" for q in catalogue(state, now))
        due = review_summary(state, now)["due"]
        if gap is not None and gap >= IDLE_AT_RISK:
            reasons = [f"No study for {gap} scheduled day{'s' if gap != 1 else ''}"]
            if open_quizzes:
                reasons.append(f"{open_quizzes} quiz{'zes' if open_quizzes > 1 else ''} open")
            if due:
                reasons.append(f"{due} review{'s' if due > 1 else ''} due")
            if j and j.stage in ("ready", "revision") and j.proposed_id:
                reasons.append("Plan proposal waiting")
            at_risk.append(
                {
                    "id": row["id"],
                    "name": name,
                    "idle_days": gap,
                    "last_study": last.isoformat() if last else None,
                    "streak": progress["streak"],
                    "reasons": reasons,
                }
            )
    rates = []
    for week in range(4):
        known = [r["weeks"][week] for r in retention_rows if r["weeks"][week] is not None]
        rates.append(round(100 * sum(known) / len(known)) if known else None)
    return {
        "window_days": WINDOW_DAYS,
        "funnel": [{"stage": label, "count": funnel[key]} for key, label in stages],
        "retention": {
            "weeks": ["Week 1", "Week 2", "Week 3", "Week 4"],
            "rates": rates,
            "learners": retention_rows,
        },
        "at_risk": sorted(at_risk, key=lambda item: -item["idle_days"]),
        "features": sorted(
            (
                {"feature": label, "uses": count, "learners": len(users[label])}
                for label, count in uses.items()
            ),
            key=lambda item: (-item["uses"], item["feature"]),
        ),
        "generated_at": now.astimezone(IST).isoformat(),
        "privacy": "Counts and dates only: no questions, answers, documents, typed text or message content. "
        "Opening something is not proof of reading or learning.",
    }


def record_usage(conn, learner_id, event, now):
    """Best effort: a savepoint keeps a failed count from breaking the caller's transaction."""
    import psycopg

    if event not in USAGE_EVENTS:
        raise ValueError("Unknown usage event")
    try:
        with conn.transaction():
            conn.execute(
                "INSERT INTO usage_daily(learner_id,day,event,count) VALUES (%s,%s,%s,1) "
                "ON CONFLICT (learner_id,day,event) DO UPDATE SET count=usage_daily.count+1",
                (learner_id, study_day(now), event),
            )
    except psycopg.Error as exc:
        log.warning("Usage count skipped: %s", type(exc).__name__)
