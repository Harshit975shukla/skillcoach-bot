import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from skillcoach import scheduler
from skillcoach.cli import main, schedule_key
from skillcoach.clients import HTTP, Budget
from skillcoach.scheduler import MAX_LEAD, SLOTS, slot_date, slot_instant, trigger
from skillcoach.timeutil import IST
from skillcoach.web import create_app

SECRET = "s" * 40
AUTH = {"Authorization": f"Bearer {SECRET}"}


class Response:
    def __init__(self, status, body=b""):
        self.status_code = status
        self.body = body
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        if self.body:
            yield self.body


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def utc(text):
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.mark.parametrize(
    ("kind", "at", "expected"),
    [
        # On-time and same-day late runs keep today's slot.
        ("lesson", "2026-09-29T03:30:00", date(2026, 9, 29)),
        ("lesson", "2026-09-29T10:00:00", date(2026, 9, 29)),
        # The Monday 18:00 quiz created at 01:15 IST Tuesday is Monday's (stale), never Tuesday's.
        ("quiz", "2026-09-28T19:45:00", date(2026, 9, 28)),
        ("quiz", "2026-09-28T12:20:00", date(2026, 9, 28)),
        ("quiz", "2026-09-28T12:00:00", date(2026, 9, 25)),
        # A Friday quiz created early Saturday stays Friday's; a Monday-morning lesson run before 09:00 is Friday's.
        ("quiz", "2026-10-02T19:00:00", date(2026, 10, 2)),
        ("lesson", "2026-09-28T02:00:00", date(2026, 9, 25)),
        # Weekend runs delayed past midnight keep their weekend slot instead of failing on the weekday check.
        ("weekly", "2026-10-03T19:30:00", date(2026, 10, 3)),
        ("review", "2026-10-04T04:30:00", date(2026, 10, 4)),
        ("review", "2026-10-05T01:00:00", date(2026, 10, 4)),
    ],
)
def test_slot_date_maps_late_runs_to_their_own_slot(kind, at, expected):
    assert slot_date(kind, utc(at)) == expected
    schedule_key(kind, expected)


def test_slot_date_requires_timezone():
    with pytest.raises(ValueError):
        slot_date("lesson", datetime(2026, 9, 29, 9))


def test_late_quiz_run_after_midnight_does_not_consume_the_next_quiz(harness, monkeypatch):
    h = harness
    monkeypatch.setattr("skillcoach.cli.Runtime.from_env", lambda: h.runtime)
    h.clock.now = datetime(2026, 9, 29, 1, 15, tzinfo=IST)
    assert main(["schedule", "quiz", "--at", "2026-09-28T19:45:00+00:00", "--no-media"]) == 0
    keys = set(h.repo.jobs)
    assert any(key.endswith("schedule:quiz:2026-09-28") for key in keys)
    assert not any("2026-09-29" in key for key in keys)
    assert not h.telegram.messages
    # The explicit date path used by the on-time trigger is unchanged.
    h.clock.now = datetime(2026, 9, 29, 18, tzinfo=IST)
    seen = []
    monkeypatch.setattr("skillcoach.cli.schedule", lambda runtime, kind, day, media: seen.append((kind, day)))
    assert main(["schedule", "quiz", "--date", "2026-09-29", "--no-media"]) == 0
    assert seen == [("quiz", date(2026, 9, 29))]


def configured(monkeypatch, *, token="dispatch-token", repo="owner/skillcoach-bot", now=None, session=None):
    monkeypatch.setenv("CRON_SECRET", SECRET)
    monkeypatch.setenv("SCHEDULER_REPO", repo)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("SCHEDULER_GITHUB_TOKEN", token)
    if now:
        monkeypatch.setattr(scheduler, "utcnow", lambda: now)
    session = session or Session(Response(204))
    monkeypatch.setattr(scheduler, "HTTP", lambda: HTTP(session))
    return session


def test_cron_endpoint_fails_closed_and_needs_no_private_state(monkeypatch):
    # No runtime or DATABASE_URL: the trigger must never open learner storage.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = create_app().test_client()
    monkeypatch.delenv("CRON_SECRET", raising=False)
    assert client.get("/cron/lesson", headers=AUTH).status_code == 503
    monkeypatch.setenv("CRON_SECRET", "short")
    assert client.get("/cron/lesson", headers={"Authorization": "Bearer short"}).status_code == 503
    session = configured(monkeypatch, now=utc("2026-09-29T02:10:00"))
    assert client.get("/cron/lesson").status_code == 401
    assert client.get("/cron/lesson", headers={"Authorization": "Bearer " + "x" * 40}).status_code == 401
    assert client.get("/cron/lesson", headers={"Authorization": SECRET}).status_code == 401
    assert client.get("/cron/unknown", headers=AUTH).status_code == 404
    assert client.post("/cron/lesson", headers=AUTH).status_code == 405
    monkeypatch.delenv("SCHEDULER_GITHUB_TOKEN")
    assert client.get("/cron/lesson", headers=AUTH).status_code == 503
    monkeypatch.setenv("GITHUB_TOKEN", "fallback-token")
    monkeypatch.setenv("SCHEDULER_REPO", "not a repo")
    assert client.get("/cron/lesson", headers=AUTH).status_code == 503
    assert session.calls == []


def test_cron_endpoint_dispatches_todays_slot_with_exact_not_before(monkeypatch):
    session = configured(monkeypatch, now=utc("2026-09-29T02:10:00"))
    response = create_app().test_client().get("/cron/lesson", headers=AUTH)
    assert response.status_code == 202
    assert response.get_json() == {
        "status": "dispatched",
        "kind": "lesson",
        "date": "2026-09-29",
        "not_before": "2026-09-29T03:30:00Z",
    }
    [(method, url, kwargs)] = session.calls
    assert method == "POST"
    assert (
        url
        == "https://api.github.com/repos/owner/skillcoach-bot/actions/workflows/morning_lesson.yml/dispatches"
    )
    assert kwargs["json"] == {
        "ref": "main",
        "inputs": {"date": "2026-09-29", "not_before": "2026-09-29T03:30:00Z"},
    }
    assert kwargs["headers"]["Authorization"] == "Bearer dispatch-token"
    assert "GITHUB_TOKEN" not in json.dumps(response.get_json())


@pytest.mark.parametrize(
    ("kind", "now", "workflow", "inputs"),
    [
        (
            "quiz",
            "2026-09-29T11:00:00",
            "evening_quiz.yml",
            {"date": "2026-09-29", "not_before": "2026-09-29T12:30:00Z"},
        ),
        (
            "weekly",
            "2026-10-03T02:59:00",
            "weekend.yml",
            {"kind": "weekly", "date": "2026-10-03", "not_before": "2026-10-03T03:30:00Z"},
        ),
        (
            "review",
            "2026-10-04T03:05:00",
            "weekend.yml",
            {"kind": "review", "date": "2026-10-04", "not_before": "2026-10-04T04:30:00Z"},
        ),
    ],
)
def test_each_slot_dispatches_its_workflow(monkeypatch, kind, now, workflow, inputs):
    session = configured(monkeypatch)
    body, status = trigger(kind, f"Bearer {SECRET}", now=utc(now))
    assert status == 202 and body["date"] == inputs["date"]
    [(_, url, kwargs)] = session.calls
    assert url.endswith(f"/actions/workflows/{workflow}/dispatches")
    assert kwargs["json"] == {"ref": "main", "inputs": inputs}


def test_non_slot_days_and_far_early_calls_do_not_dispatch(monkeypatch):
    session = configured(monkeypatch)
    assert (
        trigger("lesson", f"Bearer {SECRET}", now=utc("2026-10-03T02:10:00"))[0]["reason"] == "not_a_slot_day"
    )
    assert (
        trigger("weekly", f"Bearer {SECRET}", now=utc("2026-10-02T02:10:00"))[0]["reason"] == "not_a_slot_day"
    )
    assert trigger("lesson", f"Bearer {SECRET}", now=utc("2026-09-28T22:00:00"))[0]["reason"] == "too_early"
    assert session.calls == []
    # A call after the slot on the same day still dispatches; the worker then runs at once and dedupes.
    body, status = trigger("lesson", f"Bearer {SECRET}", now=utc("2026-09-29T05:00:00"))
    assert status == 202 and body["not_before"] == "2026-09-29T03:30:00Z"


def test_dispatch_failures_are_reported_without_secrets(monkeypatch):
    configured(monkeypatch, session=Session(Response(403, b'{"message":"Resource not accessible"}')))
    body, status = trigger("lesson", f"Bearer {SECRET}", now=utc("2026-09-29T02:10:00"))
    assert (status, body) == (502, {"error": "dispatch_failed", "code": "http_403"})
    assert "dispatch-token" not in json.dumps(body)


def test_http_client_accepts_empty_no_content_responses():
    status, body = HTTP(Session(Response(204))).call(
        "POST", "https://example.invalid", budget=Budget(), allow=(204,)
    )
    assert (status, body) == (204, None)


def test_vercel_crons_fire_in_the_hour_before_each_slot():
    crons = {c["path"]: c["schedule"] for c in json.loads(Path("vercel.json").read_text())["crons"]}
    assert set(crons) == {f"/cron/{kind}" for kind in SLOTS}
    for kind, slot in SLOTS.items():
        minute, hour, dom, month, dow = crons[f"/cron/{kind}"].split()
        # Hobby allows at most one run per day and fires anywhere within the configured hour.
        assert minute == "0" and hour.isdigit() and dom == month == "*"
        cron_days = set(range(1, 6)) if dow == "1-5" else {int(dow)}
        assert {(d + 1) % 7 for d in slot.weekdays} == cron_days
        for day in (date(2026, 9, 28) + timedelta(days=n) for n in range(7)):
            if day.weekday() not in slot.weekdays:
                continue
            due = slot_instant(kind, day).astimezone(UTC)
            earliest = datetime.combine(due.date(), datetime.min.time(), UTC).replace(hour=int(hour))
            latest = earliest + timedelta(minutes=59)
            assert due.date() == day and earliest.astimezone(IST).date() == day
            assert timedelta(0) < due - latest and due - earliest <= MAX_LEAD


def test_workflows_forward_not_before_and_wait_for_the_slot():
    worker = Path(".github/workflows/coach-job.yml").read_text()
    assert "timeout-minutes: ${{ inputs.not_before != '' && 125 || 20 }}" in worker
    wait = worker.index("name: Wait for the exact IST slot")
    assert worker.index("Install local renderers") < wait < worker.index("Execute explicit operation")
    assert "if: inputs.not_before != ''" in worker and "-gt 6000" in worker and 'sleep "$WAIT"' in worker
    assert int(re.search(r"-gt (\d+) \]", worker).group(1)) == MAX_LEAD.total_seconds()
    for name, jobs in (("morning_lesson.yml", 1), ("evening_quiz.yml", 1), ("weekend.yml", 2)):
        caller = Path(".github", "workflows", name).read_text()
        assert "      not_before:\n" in caller
        assert caller.count("not_before: ${{ inputs.not_before || '' }}") == jobs
    example = Path(".env.example").read_text()
    for key in ("CRON_SECRET=", "SCHEDULER_REPO=", "SCHEDULER_GITHUB_TOKEN="):
        assert key in example
