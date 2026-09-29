"""Read-only, allowlisted curriculum and learner-delivery views for the owner."""

import re
from datetime import datetime, timedelta

from skillcoach.admin_auth import AdminDenied
from skillcoach.catalog import TOPICS, find_topic
from skillcoach.journey import approved_plan, safe_learning_view
from skillcoach.lesson_delivery import lesson_id
from skillcoach.models import State
from skillcoach.scheduler import SLOTS, slot_instant
from skillcoach.timeutil import IST

PAGE_SIZE = 20
KINDS = {"lesson": "Lesson", "quiz": "Daily quiz", "weekly": "Weekly assessment", "review": "Weekly review"}
DELIVERY_NOTICE = (
    "Transport records show Telegram accepted a send, not that a learner read, watched or understood it. "
    "Private message text, questions, answers and documents are excluded. Historical records may predate "
    "delivery tracking; missing evidence is not proof of delivery."
)


def materials(config):
    from skillcoach import course_library, resources
    from skillcoach.labs import COST, LAB_CATALOG_VERSION, LABS, REVIEWED, ROUTE_LABELS, lab_steps

    labs = []
    for lab in LABS.values():
        routes = []
        for route in lab.routes:
            steps, cleanup, _ = lab_steps(lab, route, "YOUR_LAB_TOKEN", config.labs_template_repo)
            routes.append({"label": ROUTE_LABELS[route], "steps": steps, "cleanup": cleanup})
        labs.append(
            {
                "id": lab.id,
                "title": lab.title,
                "goal": lab.goal,
                "minutes": lab.minutes,
                "references": lab.references,
                "routes": routes,
            }
        )
    return {
        "courses": course_library.index(),
        "resources": resources.library_view(),
        "labs": {
            "version": LAB_CATALOG_VERSION,
            "review": REVIEWED,
            "enabled": config.labs_enabled,
            "cost": COST,
            "items": labs,
        },
    }


def catalog_topic(record):
    ident = record.get("topic_id")
    value = ident if isinstance(ident, str) and ident in TOPICS else record.get("topic", "")
    entry = find_topic(value) if isinstance(value, str) else None
    return {"id": entry[0], "title": entry[2]} if entry else {"id": None, "title": "Private/custom topic"}


def upcoming_view(state, membership, now, *, labs_enabled):
    """Forecast from the same IST slots and approved plan used by the worker, never generate a plan."""
    learning = safe_learning_view(state, now, labs_enabled=labs_enabled)
    if not learning["shared"]:
        return {"status": "Learner consent is required to view learning details.", "slots": []}
    if membership != "active":
        return {"status": "Access is inactive; no scheduled coaching will be sent.", "slots": []}
    if state.paused:
        return {"status": "Notifications are paused; there is no automatic next delivery.", "slots": []}
    plan = approved_plan(state)
    if not plan:
        return {"status": "Waiting for the learner to approve a plan.", "slots": []}
    local = now.astimezone(IST)
    pending = next((day for day in plan.sessions if not day.lesson_key), None)
    slots = []
    for kind, slot in SLOTS.items():
        for offset in range(15):
            day = local.date() + timedelta(days=offset)
            due = slot_instant(kind, day)
            if day.weekday() not in slot.weekdays or due < local:
                continue
            topic = None
            if kind == "lesson":
                if pending is None:
                    break
                if pending.date and pending.date > day:
                    continue
                if any(session.date == day and session.lesson_key for session in plan.sessions):
                    continue
                topic = {"id": pending.topic_id, "title": TOPICS[pending.topic_id][1]}
                detail = "Next unprepared topic in the approved plan. Timing depends on worker execution."
            elif kind == "quiz":
                today = next(
                    (session for session in plan.sessions if session.date == day and session.lesson_key), None
                )
                if today is not None:
                    topic = {"id": today.topic_id, "title": TOPICS[today.topic_id][1]}
                else:
                    lesson = next((item for item in slots if item["kind"] == "lesson"), None)
                    if lesson and datetime.fromisoformat(lesson["at"]).date() == day:
                        topic = lesson["topic"]
                detail = "Conditional: a lesson for that day must finish delivery first."
            elif kind == "weekly":
                detail = "Conditional: requires delivered lessons; questions are generated at run time."
            else:
                detail = "Reviews practice; a new plan still requires learner approval."
            slots.append(
                {"kind": kind, "title": KINDS[kind], "at": due.isoformat(), "topic": topic, "detail": detail}
            )
            break
    slots.sort(key=lambda item: item["at"])
    status = "Forecast only, not queued work or a promise of delivery."
    if learning["labs"]["gate_blocked"]:
        status += " Required labs are blocking the next plan, not existing lessons or quizzes."
    if pending is None:
        status += " All lessons in this plan are prepared; unsent parts may still need recovery."
    return {"status": status, "slots": slots}


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(IST).isoformat() if parsed.tzinfo is not None else None


def lesson_history(state, before):
    from skillcoach.course_library import VERSIONS

    records = sorted(
        state.lessons.items(),
        key=lambda item: (str(item[1].get("date", "")), lesson_id(item[0])),
        reverse=True,
    )
    if before is not None:
        position = next((i for i, (key, _) in enumerate(records) if lesson_id(key) == before), None)
        if position is None:
            raise AdminDenied("Lesson history changed. Refresh the learner view.")
        records = records[position + 1 :]
    lessons = []
    for key, record in records[:PAGE_SIZE]:
        topic = catalog_topic(record)
        date = record.get("date")
        date = date if isinstance(date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) else None
        source = record.get("source")
        tasks = [task for task in state.tasks.values() if task.origin.startswith(key + ":")]
        version = record.get("library_version")
        lessons.append(
            {
                "id": lesson_id(key),
                "topic": topic,
                "date": date,
                "prepared_at": _timestamp(record.get("prepared_at")),
                "delivered_at": _timestamp(record.get("delivered_at")),
                "source": source if source in ("library", "authored", "AI") else "legacy",
                "version": version if isinstance(version, str) and version in VERSIONS else None,
                "tasks_done": sum(task.status == "done" for task in tasks),
                "tasks_total": len(tasks),
            }
        )
    return lessons, lessons[-1]["id"] if len(records) > PAGE_SIZE else None


def delivery_view(row):
    counts = {key: row[key] for key in ("sent", "pending", "failed", "suppressed", "total")}
    if not counts["total"]:
        status = "No outgoing messages recorded"
    elif counts["sent"] == counts["total"]:
        status = "Sent to Telegram"
    elif counts["sent"]:
        status = "Partially sent"
    elif counts["failed"]:
        status = "Delivery failed"
    elif counts["pending"]:
        status = "Awaiting delivery"
    else:
        status = "Suppressed; not sent"
    return {
        "cursor": str(row["sequence"]),
        "title": KINDS.get(row["scheduled_kind"], "Bot response")
        if row["kind"] == "schedule"
        else "Bot response",
        "processing": row["job_status"],
        "status": status,
        "created_at": row["created_at"].isoformat(),
        "eligible_at": row["available_at"].isoformat(),
        "last_sent_at": row["last_sent_at"].isoformat() if row["last_sent_at"] else None,
        "messages": counts,
        "media_sent": row["media_sent"],
    }


def learner_detail(runtime, learner, lesson_before, delivery_before):
    if not isinstance(learner, str) or not re.fullmatch(r"owner|u_[a-z0-9]+", learner):
        raise AdminDenied("Choose a learner from the admin list.")
    if lesson_before is not None and (
        not isinstance(lesson_before, str) or not re.fullmatch(r"[0-9a-f]{20}", lesson_before)
    ):
        raise AdminDenied("Invalid lesson history cursor.")
    if delivery_before is not None and (
        not isinstance(delivery_before, str)
        or not re.fullmatch(r"[1-9][0-9]{0,18}", delivery_before)
        or int(delivery_before) > 9223372036854775807
    ):
        raise AdminDenied("Invalid delivery history cursor.")
    now = runtime.clock()
    with runtime.repo.connection(readonly=True) as conn:
        row = conn.execute(
            "SELECT l.status,c.body FROM learners l JOIN coach_state c ON c.learner_id=l.id WHERE l.id=%s",
            (learner,),
        ).fetchone()
        if row is None:
            raise AdminDenied("Learner is no longer available. Refresh the admin list.")
        state = State.model_validate(row["body"])
        learning = safe_learning_view(state, now, labs_enabled=runtime.config.labs_enabled)
        result = {
            "learner": learner,
            "learning": learning,
            "upcoming": upcoming_view(state, row["status"], now, labs_enabled=runtime.config.labs_enabled),
            "lessons": [],
            "lesson_next": None,
            "deliveries": [],
            "delivery_next": None,
            "notice": DELIVERY_NOTICE,
            "generated_at": now.isoformat(),
        }
        if not learning["shared"]:
            return result
        result["lessons"], result["lesson_next"] = lesson_history(state, lesson_before)
        rows = conn.execute(
            "WITH recent AS (SELECT id,sequence,status AS job_status,created_at,available_at,"
            "payload->>'type' AS kind,payload->>'kind' AS scheduled_kind FROM jobs "
            "WHERE learner_id=%s AND (%s::bigint IS NULL OR sequence<%s::bigint) "
            "ORDER BY sequence DESC LIMIT %s) "
            "SELECT j.*,count(o.id) AS total,count(o.id) FILTER (WHERE o.status='sent') AS sent,"
            "count(o.id) FILTER (WHERE o.status='pending') AS pending,"
            "count(o.id) FILTER (WHERE o.status='failed') AS failed,"
            "count(o.id) FILTER (WHERE o.status='suppressed') AS suppressed,"
            "count(o.id) FILTER (WHERE o.status='sent' AND o.body->>'kind'='media') AS media_sent,"
            "max(o.delivered_at) FILTER (WHERE o.status='sent') AS last_sent_at "
            "FROM recent j LEFT JOIN outbox o ON o.job_id=j.id AND o.learner_id=%s "
            "GROUP BY j.id,j.sequence,j.job_status,j.created_at,j.available_at,j.kind,j.scheduled_kind "
            "ORDER BY j.sequence DESC",
            (learner, delivery_before, delivery_before, PAGE_SIZE + 1, learner),
        ).fetchall()
        result["deliveries"] = [delivery_view(row) for row in rows[:PAGE_SIZE]]
        if len(rows) > PAGE_SIZE:
            result["delivery_next"] = str(rows[PAGE_SIZE - 1]["sequence"])
        return result
