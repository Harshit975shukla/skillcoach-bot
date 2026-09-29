"""Compact lesson delivery, the full-reference view and controlled lesson feedback.

A lesson arrives as a short mission, one architecture video, the required exercises and a closing
interview prompt. The complete reference stays one tap away in chat and on the private lesson page.
"""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from skillcoach.formatting import md_blocks

LESSON_ID = re.compile(r"[0-9a-f]{20}")
REPORT_REASONS = {
    "wrong": "Something is wrong",
    "outdated": "Outdated",
    "confusing": "Confusing",
    "hard": "Too hard",
    "easy": "Too easy",
}
RATINGS = {"up": "Useful", "down": "Not useful"}


def lesson_id(key: str) -> str:
    from skillcoach.service import stable_id

    return stable_id("lesson:" + key)


def find_lesson(state, ident: str):
    if not LESSON_ID.fullmatch(ident or ""):
        return None, None
    for key, record in state.lessons.items():
        if record.get("id", lesson_id(key)) == ident:
            return key, record
    return None, None


def page_url(base: str | None, ident: str) -> str | None:
    if not base:
        return None
    parts = urlsplit(base)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "lesson"] + [("lesson", ident)]
    return urlunsplit(parts._replace(query=urlencode(query)))


def open_buttons(dashboard_url: str | None, ident: str):
    rows = []
    url = page_url(dashboard_url, ident)
    if url:
        rows.append([{"text": "Open lesson page", "web_app": {"url": url}}])
    rows.append([{"text": "Read the full lesson here", "callback_data": f"lr:{ident}"}])
    return rows


def feedback_buttons(ident: str):
    return [
        [
            {"text": "👍 Useful", "callback_data": f"lf:{ident}:up"},
            {"text": "👎 Not useful", "callback_data": f"lf:{ident}:down"},
        ],
        [{"text": "Report a problem", "callback_data": f"lf:{ident}:report"}],
    ]


def review_note(lesson) -> str:
    if lesson.reviewed_at.startswith("AI-generated"):
        if lesson.reviewed_at.startswith("AI-generated offline"):
            return lesson.reviewed_at
        return (
            "AI-generated from official documentation prompts and automatically checked; not human-reviewed."
        )
    return "Reviewed lesson · " + lesson.reviewed_at


def mission(lesson, day, guide=None, reading=None, session=None, plan=None) -> str:
    lines = [f"**📘 {lesson.title}**", day.strftime("%A %d %b %Y")]
    if plan is not None and guide is not None:
        practice = plan.minutes - reading
        lines.append(f"⏱ {plan.minutes} min: about {reading} min reading, {practice} min hands-on practice")
    if session is not None:
        lines.append(f"**Today's goal:** {session.objective}")
    lines.append("")
    if guide is not None:
        lines.append(guide.explanation)
    else:
        lines += [f"**Why it matters**\n{lesson.why}", "", f"**What it is**\n{lesson.what}", ""]
        lines.append("**Four concepts:** " + " · ".join(c.name for c in lesson.concepts))
    lines += [
        "",
        "**Cost and safety** (read before you start)\n" + lesson.safety,
        "",
        review_note(lesson),
        "The full lesson has all four concepts, the end-to-end flow and references.",
    ]
    return "\n".join(lines)


def exercise_detail(task, session=None) -> str:
    detail = f"**Goal:** {task.goal}\n" + "\n".join(f"{i}. {step}" for i, step in enumerate(task.steps, 1))
    if session is not None:
        detail = (
            f"Approved objective: {session.objective}\nApproved practice: {session.practice}\n\n" + detail
        )
    return detail


def display_name(name: str) -> str:
    """Authored names carry their original estimate ("Task 1 (20 min): ..."); pacing may change it."""
    return re.sub(r"^Task \d+ \(\d+ min\):\s*", "", name) or name


def exercises(lesson, tasks, ids, practice=None) -> str:
    total = practice if practice is not None else sum(t.minutes for t in tasks)
    parts = [
        f"**🛠 Today's exercises** · about {total} min, required",
        "Do them in order. Record each one with its command when you finish; add minutes if you like, "
        "for example `/complete <id> 12`.",
    ]
    for index, (task, ident) in enumerate(zip(tasks, ids), 1):
        steps = "\n".join(f"{i}. {step}" for i, step in enumerate(task.steps, 1))
        parts.append(
            f"**{index}. {display_name(task.name)}** · about {task.minutes} min\n**Goal:** {task.goal}\n{steps}\n"
            f"Record it: `/complete {ident}`"
        )
    return "\n\n".join(parts)


def closing(lesson, topic) -> str:
    question = lesson.interview_question or (
        f"Walk me through a design that uses {topic}: the request or data path, how it fails, how you "
        "would detect and recover from that failure, and one cost trade-off."
    )
    return (
        "**🧹 Cleanup when you finish**\n"
        + "\n".join(f"- {step}" for step in lesson.cleanup)
        + "\n\n**🎤 Interview practice**\n"
        + question
        + "\n\nAnswer out loud or in writing in about two minutes, then compare with the answer checklist "
        "in the full lesson. For a graded round, use /interview.\n\n"
        "Optional free courses and guides: /resources (also on the lesson page).\n\n"
        "**How was today's lesson?** Your rating stores only the button you pick; the owner sees totals only."
    )


def full_reference(lesson, extension=(), *, topic="") -> str:
    from skillcoach.resources import related_text

    parts = [
        f"**📖 Full lesson: {lesson.title}**",
        f"**Why it matters**\n{lesson.why}",
        f"**What it is**\n{lesson.what}",
    ]
    parts += [f"**{i}. {c.name}**\n{c.body}" for i, c in enumerate(lesson.concepts, 1)]
    parts.append("**End to end**\n" + "\n".join(f"{i}. {step}" for i, step in enumerate(lesson.e2e, 1)))
    parts.append("**Key terms**\n" + "\n".join(f"- {term}" for term in lesson.key_terms))
    if extension:
        parts.append(
            "**Optional extension practice** (outside today's time target; not tracked)\n\n"
            + "\n\n".join(
                f"**{display_name(t.name)}**\n{t.goal}\n"
                + "\n".join(f"{i}. {s}" for i, s in enumerate(t.steps, 1))
                for t in extension
            )
        )
    if lesson.interview_points:
        parts.append(
            "**Interview answer checklist**\n" + "\n".join(f"- {point}" for point in lesson.interview_points)
        )
    parts.append(
        "**Official references**\n"
        + "\n".join(f"- {url}" for url in lesson.references)
        + "\n"
        + review_note(lesson)
    )
    return "\n\n".join(parts) + (related_text(topic) if topic else "")


def stored_lesson(repo, key, record):
    """Rebuild the lesson a learner received: authored content or the AI result cached for its job."""
    from lesson_content import get_lesson
    from skillcoach.catalog import find_topic
    from skillcoach.content_checks import finalize_lesson
    from skillcoach.models import Lesson

    if record.get("source") == "library":
        from skillcoach.course_library import get_package

        package = get_package(record["topic_id"], record["library_version"])
        return package.lesson if package else None
    if record.get("source") == "authored":
        authored = get_lesson(record.get("topic", ""))
        return Lesson.model_validate(authored) if authored else None
    job = record.get("job_id") or repo.lesson_job(key)
    body = repo.cached(job, "lesson") if job else None
    if body is None:
        return None
    entry = find_topic(record.get("topic", ""))
    return finalize_lesson(Lesson.model_validate(body), entry[1].reference if entry else None)


def lesson_tasks(state, key):
    prefix = key + ":"
    found = [t for t in state.tasks.values() if t.origin.startswith(prefix)]
    return sorted(found, key=lambda t: int(t.origin.rsplit(":", 1)[1]) if t.origin[-1:].isdigit() else 0)


def extension_tasks(lesson, tasks):
    tracked = {t.title for t in tasks}
    return [t for t in lesson.tasks if t.name not in tracked]


def reference_sections(lesson):
    sections = [
        {"heading": "Why it matters", "blocks": md_blocks(lesson.why)},
        {"heading": "What it is", "blocks": md_blocks(lesson.what)},
        *(
            {"heading": f"{i}. {c.name}", "blocks": md_blocks(c.body)}
            for i, c in enumerate(lesson.concepts, 1)
        ),
        {
            "heading": "End to end",
            "blocks": md_blocks("\n".join(f"{i}. {s}" for i, s in enumerate(lesson.e2e, 1))),
        },
        {"heading": "Key terms", "blocks": md_blocks("\n".join(f"- {t}" for t in lesson.key_terms))},
        {"heading": "Cost and safety", "blocks": md_blocks(lesson.safety)},
    ]
    notes = [{"heading": "Cleanup", "blocks": md_blocks("\n".join(f"- {s}" for s in lesson.cleanup))}]
    return sections, notes


def page(repo, state, ident, now):
    from skillcoach.resources import related_view

    key, record = find_lesson(state, ident)
    if key is None:
        return None
    lesson = stored_lesson(repo, key, record)
    tasks = lesson_tasks(state, key)
    if lesson is None:
        return {
            "id": ident,
            "title": record.get("topic", "Lesson"),
            "date": record.get("date"),
            "available": False,
            "exercises": [exercise_view(t) for t in tasks],
            "resources": related_view(record.get("topic", "")) if record.get("topic") else [],
        }
    sections, notes = reference_sections(lesson)
    extension = extension_tasks(lesson, tasks)
    return {
        "id": ident,
        "title": lesson.title,
        "date": record.get("date"),
        "available": True,
        "review": review_note(lesson),
        "sections": sections,
        "exercises": [exercise_view(t) for t in tasks],
        "notes": notes,
        "extension": [
            {
                "title": display_name(t.name),
                "minutes": t.minutes,
                "blocks": md_blocks(
                    f"**Goal:** {t.goal}\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(t.steps, 1))
                ),
            }
            for t in extension
        ],
        "interview": {
            "question": md_blocks(lesson.interview_question or ""),
            "points": [md_blocks(point) for point in lesson.interview_points],
        }
        if lesson.interview_question
        else None,
        "references": [u for u in lesson.references if u.startswith("https://")],
        "resources": related_view(record.get("topic", "")) if record.get("topic") else [],
        "feedback": (record.get("feedback") or {}).get("rating"),
        "generated_at": now.isoformat(),
    }


def exercise_view(task):
    return {
        "id": task.id,
        "title": display_name(task.title),
        "minutes": task.estimated_minutes,
        "status": task.status,
        "blocks": md_blocks(task.detail),
    }


def recent_lessons(state, limit=10):
    items = sorted(state.lessons.items(), key=lambda item: (item[1].get("date", ""), item[0]), reverse=True)
    return [
        {
            "id": record.get("id", lesson_id(key)),
            "topic": record.get("topic", "Lesson"),
            "date": record.get("date"),
            "delivered": bool(record.get("delivered_at")),
        }
        for key, record in items[:limit]
    ]


class LessonActions:
    def __init__(self, service):
        self.s = service

    def read(self, ident):
        key, record = find_lesson(self.s.state, ident)
        if key is None:
            self.s.say("That lesson is not available any more. Use /tasks for your current practice.")
            return
        lesson = stored_lesson(self.s.repo, key, record)
        if lesson is None:
            self.s.say(
                "The full text of this older lesson was not kept. Its tracked exercises are in /tasks."
            )
            return
        tasks = lesson_tasks(self.s.state, key)
        self.s.say(
            full_reference(lesson, extension_tasks(lesson, tasks), topic=record.get("topic", "")), md=True
        )

    def feedback(self, ident, value, reason=None):
        key, record = find_lesson(self.s.state, ident)
        if key is None:
            self.s.say("That lesson is not available any more, so feedback was not recorded.")
            return
        feedback = dict(record.get("feedback") or {})
        at = self.s.now.isoformat()
        if value in RATINGS:
            feedback.update(rating=value, rated_at=at)
            self.s.say(
                f"Thanks, recorded “{RATINGS[value]}” for {record.get('topic', 'this lesson')}."
                + (" Tap Report a problem if something specific was off." if value == "down" else "")
            )
        elif value == "report" and reason is None:
            self.s.say(
                "What was the problem? Pick one; nothing else is stored.",
                buttons=[
                    [{"text": label, "callback_data": f"lf:{ident}:r:{code}"}]
                    for code, label in REPORT_REASONS.items()
                ],
            )
            return
        elif value == "r" and reason in REPORT_REASONS:
            reports = [r for r in feedback.get("reports", []) if r in REPORT_REASONS]
            if reason not in reports:
                reports.append(reason)
            feedback.update(reports=reports, reported_at=at)
            self.s.say(
                f"Thanks, reported “{REPORT_REASONS[reason]}”. Report totals guide which lessons get reviewed next."
            )
        else:
            self.s.say("Unsupported or expired button.")
            return
        record["feedback"] = feedback


def feedback_summary(states):
    """Counts only: ratings and controlled report reasons, never learner text."""
    ratings = {code: 0 for code in RATINGS}
    reports = {code: 0 for code in REPORT_REASONS}
    for state in states:
        for record in state.lessons.values():
            feedback = record.get("feedback") or {}
            if feedback.get("rating") in ratings:
                ratings[feedback["rating"]] += 1
            for reason in feedback.get("reports", []):
                if reason in reports:
                    reports[reason] += 1
    return {"ratings": ratings, "reports": reports}
