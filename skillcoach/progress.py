"""Learner-facing progress from recorded evidence: study days, answers, lessons and practice.

Only counts what the learner actually did. Receiving a lesson is not mastery; nothing is inferred.
"""

from collections import defaultdict

from skillcoach.timeutil import WEEKLY_GOAL, monday, streak, study_day


def pct(part, whole):
    return round(100 * part / whole) if whole else None


QUIZ_KINDS = ("daily", "weekly")


def answered(state, kinds=QUIZ_KINDS):
    for session in state.assessments.values():
        if session.kind not in kinds:
            continue
        for index, answer in enumerate(session.answers):
            if index < len(session.questions):
                yield session, session.questions[index], answer


def understood_keys(state):
    j = state.journey
    if not j:
        return set()
    return {
        d.lesson_key for plan in j.plans.values() for d in plan.sessions if d.lesson_key and d.understood_at
    }


def focus_topics(entries):
    """(strongest, weakest) as (topic, correct, total); topics need two answers to count."""
    scores = defaultdict(lambda: [0, 0])
    for _, question, answer in entries:
        scores[question.topic][0] += int(answer.correct)
        scores[question.topic][1] += 1
    rated = [(right / total, total, topic, right) for topic, (right, total) in scores.items() if total >= 2]
    strong = max((r for r in rated if r[0] >= 0.8), default=None)
    weak = min((r for r in rated if r[0] < 0.8), default=None)
    return tuple((r[2], r[3], r[1]) if r else None for r in (strong, weak))


def summary(state, now):
    from skillcoach.review import review_summary

    today = study_day(now)
    start = monday(today)
    entries = list(answered(state))
    week = [e for e in entries if study_day(e[2].created_at) >= start]
    reviews = list(answered(state, ("review",)))
    tasks = list(state.tasks.values())
    delivered = {key for key, record in state.lessons.items() if record.get("delivered_at")}
    return {
        "study_days_week": len({d for d in state.activity if start <= d <= today}),
        "weekly_goal": WEEKLY_GOAL,
        "streak": streak(state.activity, today),
        "questions_answered": len(entries),
        "accuracy": pct(sum(e[2].correct for e in entries), len(entries)),
        "week_questions": len(week),
        "week_accuracy": pct(sum(e[2].correct for e in week), len(week)),
        "lessons_delivered": len(delivered),
        "lessons_understood": len(understood_keys(state) & delivered),
        "quizzes_completed": sum(
            s.status == "completed" and s.kind in QUIZ_KINDS for s in state.assessments.values()
        ),
        "reviews_answered": len(reviews),
        "review_accuracy": pct(sum(e[2].correct for e in reviews), len(reviews)),
        "review_due": review_summary(state, now)["due"],
        "exercises_done": sum(t.status == "done" for t in tasks),
        "exercises_skipped": sum(t.status == "skipped" for t in tasks),
        "exercises_open": sum(t.status == "pending" for t in tasks),
        "labs_verified": sum(a.status == "verified" for a in state.labs.values()),
    }


def recap_text(state, now):
    """Wins-first weekly recap covering Monday to the current study day."""
    today = study_day(now)
    start = monday(today)
    s = summary(state, now)
    entries = [e for e in answered(state) if study_day(e[2].created_at) >= start]
    lessons = {
        key
        for key, record in state.lessons.items()
        if record.get("delivered_at") and start.isoformat() <= (record.get("date") or "") <= today.isoformat()
    }
    reviews = [e for e in answered(state, ("review",)) if study_day(e[2].created_at) >= start]
    closed = [t for t in state.tasks.values() if t.completed_at and study_day(t.completed_at) >= start]
    done = sum(t.status == "done" for t in closed)
    skipped = sum(t.status == "skipped" for t in closed)
    labs = sum(
        a.status == "verified" and a.verified_at is not None and study_day(a.verified_at) >= start
        for a in state.labs.values()
    )
    strong, weak = focus_topics(entries)
    lines = [
        f"🗓 Your week · {start:%d %b} to {today:%d %b}",
        f"🔥 Study days: {s['study_days_week']} (goal {s['weekly_goal']}) · streak {s['streak']}",
    ]
    if lessons:
        lines.append(
            f"📘 Lessons: {len(lessons)} received · {len(understood_keys(state) & lessons)} marked understood"
        )
    if entries:
        lines.append(
            f"📝 Quiz questions: {len(entries)} answered · "
            f"{pct(sum(e[2].correct for e in entries), len(entries))}% correct"
        )
    else:
        lines.append(
            "📝 Quiz questions: none yet. Missed daily quizzes stay open until Sunday 23:59 IST: /quizzes"
        )
    if reviews:
        lines.append(f"🔁 Reviews: {len(reviews)} answered · {sum(e[2].correct for e in reviews)} remembered")
    if done or skipped:
        lines.append(f"🛠 Exercises: {done} done" + (f" · {skipped} skipped" if skipped else ""))
    if labs:
        lines.append(f"🧪 Labs verified: {labs}")
    if strong:
        lines.append(f"💪 Strongest: {strong[0]} ({strong[1]}/{strong[2]})")
    if weak:
        lines.append(f"🎯 Focus next: {weak[0]} ({weak[1]}/{weak[2]}). Re-read its lesson or ask with /ask.")
    if not (lessons or entries or reviews or done or labs or s["study_days_week"]):
        lines.append("A quiet week is fine. Start small next week: one lesson and its 5-question quiz.")
    lines.append("This counts practice you actually did. It is evidence, not proof of mastery.")
    return "\n".join(lines)


def progress_text(state, now):
    s = summary(state, now)
    _, weak = focus_topics(list(answered(state)))
    lines = [
        "📈 Your progress",
        f"🔥 This week: {s['study_days_week']} of {s['weekly_goal']} study days · streak {s['streak']}",
        f"📘 Lessons: {s['lessons_delivered']} received · {s['lessons_understood']} marked understood",
        f"📝 Quiz questions: {s['questions_answered']} answered · {s['accuracy']}% correct"
        if s["questions_answered"]
        else "📝 Quiz questions: none answered yet",
        f"🔁 Reviews: {s['reviews_answered']} answered · {s['review_accuracy']}% remembered · {s['review_due']} due"
        if s["reviews_answered"]
        else f"🔁 Reviews due: {s['review_due']}. Missed quiz questions return after 1, 3, 7, 14 and 30 days.",
        f"🛠 Exercises: {s['exercises_done']} done · {s['exercises_open']} open",
        f"🧪 Labs verified: {s['labs_verified']}",
    ]
    if weak:
        lines.append(f"🎯 Focus: {weak[0]} ({weak[1]}/{weak[2]} correct)")
    lines.append(
        "Study days start at 04:00 IST. Sundays are rest days and one missed day a week is forgiven."
    )
    return "\n".join(lines)


def latest_lesson(state, today):
    items = sorted(
        (
            (key, record)
            for key, record in state.lessons.items()
            if record.get("date") and record["date"] <= today.isoformat()
        ),
        key=lambda item: (item[1]["date"], item[0]),
    )
    return items[-1] if items else (None, None)


def today_view(state, now):
    """The learner's current lesson, its quiz and exercises, and one next action."""
    from skillcoach.lesson_delivery import display_name, lesson_id, lesson_tasks
    from skillcoach.quizzes import catalogue, is_open
    from skillcoach.review import review_summary

    today = study_day(now)
    key, record = latest_lesson(state, today)
    lesson, exercises = None, []
    if key:
        lesson = {
            "id": record.get("id") or lesson_id(key),
            "topic": record.get("topic", "Lesson"),
            "date": record["date"],
            "delivered": bool(record.get("delivered_at")),
            "today": record["date"] == today.isoformat(),
            "understood": key in understood_keys(state),
        }
        exercises = [
            {
                "id": t.id,
                "title": display_name(t.title),
                "minutes": t.estimated_minutes,
                "status": t.status,
            }
            for t in lesson_tasks(state, key)
        ]
    quizzes = catalogue(state, now)
    quiz = next((q for q in quizzes if lesson and q["date"] == lesson["date"]), None)
    open_quizzes = [q for q in quizzes if q["can_resume"]]
    active = state.assessments.get(state.active_assessment) if state.active_assessment else None
    pending = [e for e in exercises if e["status"] == "pending"]
    review_due = review_summary(state, now)["due"]
    if (
        active
        and active.status == "active"
        and len(active.answers) < len(active.questions)
        and is_open(active, now)
    ):
        label = {"daily": "quiz", "weekly": "weekly assessment"}.get(active.kind, active.kind)
        action = {
            "kind": "quiz" if active.kind == "daily" else "resume",
            "text": f"Continue your {label} ({len(active.answers)}/{len(active.questions)} answered)",
            "callback": f"quiz:{active.id}" if active.kind == "daily" else f"resume:{active.id}",
            "start": f"quiz_{active.id}" if active.kind == "daily" else "resume",
        }
    elif review_due:
        action = {
            "kind": "review",
            "text": f"Warm up: {review_due} review question{'s' if review_due > 1 else ''} "
            f"(about {max(1, review_due // 2)} min)",
            "callback": "review:start",
            "start": "review",
        }
    elif lesson and lesson["delivered"] and quiz and quiz["can_resume"]:
        action = {
            "kind": "quiz",
            "text": f"Read “{lesson['topic']}”, then take its 5-question quiz"
            if not quiz["answered"]
            else f"Finish the quiz for “{lesson['topic']}” ({quiz['answered']}/{quiz['total']})",
            "callback": f"quiz:{quiz['id']}",
            "start": f"quiz_{quiz['id']}",
            "lesson": lesson["id"],
        }
    elif open_quizzes:
        count = len(open_quizzes)
        action = {
            "kind": "catch_up",
            "text": f"Catch up: {count} quiz{'zes' if count > 1 else ''} open until Sunday 23:59 IST",
            "callback": "home:quizzes",
            "start": f"quiz_{open_quizzes[0]['id']}",
        }
    elif pending:
        action = {
            "kind": "exercise",
            "text": f"Try an exercise: {pending[0]['title']} (about {pending[0]['minutes']} min)",
            "callback": "home:today",
            "start": None,
        }
    else:
        action = {
            "kind": "done",
            "text": "You're caught up. Explore the lesson library or ask the tutor anything.",
            "callback": "home:ask",
            "start": None,
        }
    return {
        "date": today.isoformat(),
        "lesson": lesson,
        "quiz": quiz,
        "catch_up": len(open_quizzes),
        "review_due": review_due,
        "exercises": exercises,
        "next": action,
    }
