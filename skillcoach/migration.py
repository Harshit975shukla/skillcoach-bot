"""Explicit local-snapshot import. No production fetches or public-state fallback."""

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

from skillcoach.models import Profile, State, Task, WeekPlan
from skillcoach.service import stable_id
from skillcoach.timeutil import IST, monday


def load_snapshot(path: Path):
    if path.stat().st_size > 5_000_000:
        raise ValueError("Legacy snapshot exceeds the 5 MB import limit")
    snapshot = json.loads(path.read_text(encoding="utf-8-sig"))
    validate_snapshot(snapshot)
    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return snapshot, digest


def validate_snapshot(snapshot: dict):
    if not isinstance(snapshot, dict) or not snapshot:
        raise ValueError("Legacy snapshot must be a nonempty JSON object")
    if snapshot.get("schema_version") or ("stats" in snapshot and "activity" in snapshot):
        raise ValueError(
            "A public dashboard export is not a full private legacy snapshot and cannot restore history"
        )
    if not any(
        key in snapshot for key in ("profile", "open_tasks", "completed_tasks", "recent_done", "curriculum")
    ):
        raise ValueError("Not a recognized legacy coaching snapshot")
    if "profile" in snapshot and not isinstance(snapshot["profile"], dict):
        raise ValueError("profile must be an object")
    for group, item in legacy_tasks(snapshot):
        if not isinstance(item.get("title"), str):
            raise ValueError("Every imported task must have a text title")
        date.fromisoformat(item.get("assigned_date", ""))
        if group != "open_tasks" and not item.get("completed_at"):
            raise ValueError("Completed tasks require an actual completed_at timestamp")


def legacy_tasks(snapshot):
    seen = {}
    result = []
    for group in ("open_tasks", "completed_tasks", "recent_done"):
        if not isinstance(snapshot.get(group, []), list):
            raise ValueError(f"{group} must be an array")
        for item in snapshot.get(group, []):
            if not isinstance(item, dict):
                raise ValueError("Every imported task must be an object")
            ident = str(item.get("id", ""))
            if not ident:
                raise ValueError("Full legacy tasks require IDs; dashboard summaries cannot restore history")
            if ident in seen:
                previous_group, previous = seen[ident]
                if group == "recent_done" and previous_group == "completed_tasks" and previous == item:
                    continue
                raise ValueError(
                    "Conflicting or duplicate legacy task IDs; reconcile the snapshot explicitly"
                )
            seen[ident] = (group, item)
            result.append((group, item))
    return result


def import_snapshot(state: State, snapshot: dict, digest: str) -> State:
    validate_snapshot(snapshot)
    if digest in state.imports:
        return state
    if state.profile or state.tasks or state.assessments or state.plans or state.imports or state.draft:
        raise ValueError("Import requires empty private state; refusing to overwrite existing learning")
    result = state.model_copy(deep=True)
    profile = snapshot.get("profile", {})
    resume = profile.get("resume_info", {})
    if not isinstance(resume, dict):
        raise ValueError("resume_info must be an object")
    skills = profile.get("skills", resume.get("tech_skills", []) + resume.get("cloud_skills", []))
    level = profile.get("level", "unassessed")
    if profile.get("target_role") and profile.get("name", resume.get("name")):
        result.profile = Profile(
            name=profile.get("name", resume.get("name")),
            current_role=profile.get("current_role", resume.get("current_role")) or "Not supplied",
            target_role=profile["target_role"],
            level=level if level in ("beginner", "intermediate", "advanced") else "unassessed",
            years_experience=resume.get("years_experience", 0),
            skills=skills,
            resume_text=profile.get("resume_text", ""),
            jd_text=profile.get("jd_text", ""),
            # Old scores may have been fabricated or stale; keep as archival data, not current evidence.
            readiness=None,
            readiness_basis="unavailable",
        )
    elif profile:
        # Incomplete profiles remain archived, never represented as validated setup.
        result.profile = None
    if type(profile.get("paused", False)) is not bool:
        raise ValueError("paused must be a boolean")
    result.paused = profile.get("paused", False)
    for group, raw in legacy_tasks(snapshot):
        origin = f"legacy:{digest}:{raw['id']}"
        ident = stable_id(origin)
        completed = datetime.fromisoformat(raw["completed_at"]) if group != "open_tasks" else None
        if completed and completed.tzinfo is None:
            raise ValueError("completed_at must include its timezone")
        result.tasks[ident] = Task(
            id=ident,
            origin=origin,
            title=raw["title"],
            skill=raw.get("skill") or "general",
            detail=raw.get("detail", ""),
            assigned_date=date.fromisoformat(raw["assigned_date"]),
            estimated_minutes=raw.get("est_minutes", 20),
            actual_minutes=raw.get("actual_minutes", 0),
            status="done" if completed else "pending",
            completed_at=completed,
        )
        if completed and completed.astimezone(IST).date() not in result.activity:
            result.activity.append(completed.astimezone(IST).date())
    curriculum = snapshot.get("curriculum", {})
    if not isinstance(curriculum, dict):
        raise ValueError("curriculum must be an object")
    lessons = curriculum.get("daily_lessons", {})
    plans = curriculum.get("week_plan", {})
    if not isinstance(lessons, dict) or not isinstance(plans, dict):
        raise ValueError("daily_lessons and week_plan must be date-to-topic maps")
    for day, topic in lessons.items():
        date.fromisoformat(day)
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("Legacy lesson topics must be nonempty strings")
        result.lessons[f"legacy:{day}"] = {
            "topic": topic,
            "date": day,
            "source": "legacy",
            "delivery_verified": False,
        }
    weeks = {}
    for day, topic in plans.items():
        parsed = date.fromisoformat(day)
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("Legacy plan topics must be nonempty strings")
        weeks.setdefault(monday(parsed), {})[parsed] = topic
    for start, days in weeks.items():
        if len(days) == 6 and all(d.weekday() < 6 for d in days):
            result.plans[start.isoformat()] = WeekPlan(
                days=days,
                rationale="Imported legacy plan; future plans use current profile and error evidence.",
            ).validate_dates(start)
    result.legacy_archive["snapshot"] = snapshot
    result.imports.append(digest)
    return result


def dry_run(snapshot, digest):
    state = import_snapshot(State(), snapshot, digest)
    return {
        "digest": digest,
        "tasks": len(state.tasks),
        "validated_profile": state.profile is not None,
        "readiness": "unavailable until reassessed",
        "legacy_history": "preserved privately as untrusted archive; active flows not resumed",
        "usable_plans": len(state.plans),
        "legacy_lesson_records": len(state.lessons),
        "writes": False,
    }
