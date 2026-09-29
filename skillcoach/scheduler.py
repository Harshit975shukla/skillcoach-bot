"""On-time triggering for the fixed IST schedule slots.

GitHub's own `schedule:` events are best effort and have started this repository's runs hours late.
A daily Vercel cron (hour precision on Hobby) calls /cron/<kind> in the hour before a slot. That
dispatches the worker with the slot's date and a not-before instant, and the worker sleeps until the
exact slot. GitHub schedules stay as a backup; per-learner schedule keys make duplicates no-ops.
"""

import hmac
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from skillcoach.clients import HTTP, Budget, ExternalError
from skillcoach.timeutil import IST

log = logging.getLogger("skillcoach.scheduler")


@dataclass(frozen=True)
class Slot:
    at: time
    weekdays: frozenset[int]
    workflow: str
    inputs: tuple[tuple[str, str], ...] = ()


SLOTS = {
    "lesson": Slot(time(9, 0), frozenset(range(5)), "morning_lesson.yml"),
    "quiz": Slot(time(18, 0), frozenset(range(5)), "evening_quiz.yml"),
    "weekly": Slot(time(9, 0), frozenset({5}), "weekend.yml", (("kind", "weekly"),)),
    "review": Slot(time(10, 0), frozenset({6}), "weekend.yml", (("kind", "review"),)),
}
# Runs created slightly before a slot still belong to it; GitHub never starts schedules early.
EARLY_TOLERANCE = timedelta(minutes=15)
# The worker refuses longer waits; Vercel Hobby fires 31-90 minutes before each configured slot.
MAX_LEAD = timedelta(minutes=100)
MIN_SECRET = 32
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def utcnow() -> datetime:
    return datetime.now(UTC)


def slot_instant(kind: str, day: date) -> datetime:
    return datetime.combine(day, SLOTS[kind].at, IST)


def slot_date(kind: str, at: datetime) -> date:
    """IST date of the latest `kind` slot at or before `at`.

    A delayed run therefore keeps its own slot's date instead of taking the next day's key; if that
    day has passed, the scheduler treats it as a stale no-op.
    """
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("Schedule timestamps must include a timezone.")
    local = at.astimezone(IST) + EARLY_TOLERANCE
    day = local.date()
    for _ in range(8):
        if day.weekday() in SLOTS[kind].weekdays and slot_instant(kind, day) <= local:
            return day
        day -= timedelta(days=1)
    raise ValueError(f"No {kind} slot in the previous week.")


def upcoming(kind: str, now: datetime):
    """Today's IST slot if a trigger now should dispatch it, else (None, reason)."""
    day = now.astimezone(IST).date()
    if day.weekday() not in SLOTS[kind].weekdays:
        return None, "not_a_slot_day"
    due = slot_instant(kind, day)
    if due - now > MAX_LEAD:
        return None, "too_early"
    return due, None


@dataclass(frozen=True)
class TriggerSettings:
    secret: str
    repo: str
    token: str

    @classmethod
    def from_env(cls):
        return cls(
            os.getenv("CRON_SECRET", ""),
            os.getenv("SCHEDULER_REPO", "").strip(),
            os.getenv("SCHEDULER_GITHUB_TOKEN", "") or os.getenv("GITHUB_TOKEN", ""),
        )


def trigger(kind: str, authorization: str, *, settings=None, http=None, now=None):
    """Authenticate a cron call and dispatch today's slot. Touches no private learner state."""
    if kind not in SLOTS:
        return {"error": "unknown_schedule"}, 404
    settings = settings or TriggerSettings.from_env()
    if len(settings.secret) < MIN_SECRET:
        log.error("cron_secret_unconfigured")
        return {"error": "not_configured"}, 503
    if not hmac.compare_digest(f"Bearer {settings.secret}".encode(), authorization.encode()):
        return {"error": "unauthorized"}, 401
    if not settings.token or not REPOSITORY.fullmatch(settings.repo):
        log.error("scheduler_dispatch_unconfigured")
        return {"error": "not_configured"}, 503
    now = now or utcnow()
    due, reason = upcoming(kind, now)
    if due is None:
        return {"status": "skipped", "kind": kind, "reason": reason}, 200
    slot = SLOTS[kind]
    inputs = {
        **dict(slot.inputs),
        "date": due.date().isoformat(),
        "not_before": due.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    try:
        (http or HTTP()).call(
            "POST",
            f"https://api.github.com/repos/{settings.repo}/actions/workflows/{slot.workflow}/dispatches",
            budget=Budget(15),
            allow=(200, 204),
            headers={
                "Authorization": f"Bearer {settings.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"ref": "main", "inputs": inputs},
        )
    except ExternalError as exc:
        # A duplicate dispatch after an uncertain failure is harmless: schedule keys are idempotent.
        log.error("scheduler_dispatch_failed kind=%s code=%s", kind, exc.code)
        return {"error": "dispatch_failed", "code": exc.code}, 502
    log.info("scheduler_dispatched kind=%s date=%s", kind, inputs["date"])
    return {"status": "dispatched", "kind": kind, **inputs}, 202
