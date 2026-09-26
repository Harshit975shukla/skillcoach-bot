from datetime import datetime, timedelta, timezone

import pytest
from conftest import FakeAI, FakePublisher, FakeTelegram
from test_flows import PROFILE, question_set
from test_postgres import seed

from skillcoach.cli import queue_owner_quiz
from skillcoach.clients import Budget, ExternalError
from skillcoach.models import Profile
from skillcoach.runtime import Runtime
from skillcoach.timeutil import IST


def test_owner_quiz_due_time_requires_future_timezone_and_respects_pause(harness):
    h = harness
    h.clock.now = datetime(2026, 9, 26, 13, tzinfo=IST)
    due = datetime(2026, 9, 26, 18, tzinfo=IST)
    result = queue_owner_quiz(h.runtime, due, "AWS EC2")
    assert result["created"] and result["owner_only"]
    job = h.repo.jobs[result["job"]]
    assert job["available_at"] == due
    assert due.astimezone(timezone.utc).hour == 12 and due.astimezone(timezone.utc).minute == 30
    assert not queue_owner_quiz(h.runtime, due, "AWS EC2")["created"]
    assert len(h.repo.jobs) == 1
    with pytest.raises(ValueError, match="timezone"):
        queue_owner_quiz(h.runtime, due.replace(tzinfo=None), "AWS EC2")
    with pytest.raises(ValueError, match="future"):
        queue_owner_quiz(h.runtime, h.clock.now - timedelta(minutes=1), "AWS EC2")
    h.repo.state.paused = True
    with pytest.raises(ValueError, match="paused"):
        queue_owner_quiz(h.runtime, due + timedelta(days=1), "AWS EC2")
    assert len(h.repo.jobs) == 1


def test_oneoff_workflow_inputs_are_optional_and_passed_as_quoted_values():
    from pathlib import Path

    workflow = Path(".github/workflows/coach-job.yml").read_text()
    caller = Path(".github/workflows/recovery.yml").read_text()
    assert 'queue-owner-quiz --at "$QUIZ_AT" --topic "$QUIZ_TOPIC"' in workflow
    assert "QUIZ_AT: ${{ inputs.quiz_at }}" in workflow
    assert "quiz_at: ${{ inputs.quiz_at || '' }}" in caller


def test_short_webhook_budget_defers_unsent_work_without_failure_notice(harness):
    h = harness
    h.repo.enqueue("brief", {"type": "telegram", "text": "/help"})
    assert h.runtime.process_one(Budget(20))
    assert not h.runtime.deliver_one(Budget(3), media=False)
    assert all(item["status"] == "pending" for item in h.repo.outbox.values())
    assert not h.telegram.messages
    h.runtime.recover(media=False)
    assert h.telegram.messages
    assert not any("delivery-error" in key for key in h.repo.outbox)


@pytest.mark.postgres
def test_recovered_delivery_suppresses_its_pending_error_notice(pg_repo, config):
    runtime = Runtime(config, pg_repo, FakeAI(), FakeTelegram(), FakePublisher())
    runtime.telegram.fail = True
    pg_repo.enqueue("recover-delivery", {"type": "telegram", "text": "/help"})
    assert runtime.process_one(Budget(20))
    assert runtime.deliver_one(Budget(20), media=False)
    runtime.telegram.fail = False
    with pg_repo.connection() as conn:
        conn.execute("UPDATE outbox SET available_at=now() WHERE id='recover-delivery:0'")
    assert runtime.deliver_one(Budget(20), media=False)
    with pg_repo.connection() as conn:
        assert (
            conn.execute("SELECT status FROM outbox WHERE id='recover-delivery:0:delivery-error'").fetchone()[
                "status"
            ]
            == "suppressed"
        )


def test_requested_quiz_works_without_profile_but_requires_delivered_topic(harness):
    h = harness
    h.clock.now = datetime(2026, 9, 26, 18, tzinfo=IST)
    h.repo.state.lessons["ec2"] = {
        "topic": "AWS EC2",
        "date": "2026-09-26",
        "delivered_at": h.clock.now.isoformat(),
    }
    h.ai.responses.append(question_set(5))
    h.repo.enqueue(
        "requested", {"type": "schedule", "kind": "quiz", "date": "2026-09-26", "requested_topic": "AWS EC2"}
    )
    h.runtime.recover(media=False)
    assert h.repo.state.profile is None
    assessment = next(iter(h.repo.state.assessments.values()))
    assert len(assessment.questions) == 5 and assessment.kind == "daily"
    assert h.repo.jobs["requested"]["status"] == "done"


def test_requested_quiz_does_not_invent_questions_before_delivery(harness):
    h = harness
    h.clock.now = datetime(2026, 9, 26, 18, tzinfo=IST)
    h.repo.state.lessons["ec2"] = {"topic": "AWS EC2", "date": "2026-09-26", "delivered_at": None}
    h.repo.enqueue(
        "requested", {"type": "schedule", "kind": "quiz", "date": "2026-09-26", "requested_topic": "AWS EC2"}
    )
    h.runtime.recover(media=False)
    assert not h.ai.calls and not h.repo.state.assessments
    assert h.repo.jobs["requested"]["status"] == "failed"


def test_requested_quiz_preserves_active_weekly_assessment(harness):
    h = harness
    h.clock.now = datetime(2026, 9, 26, 18, tzinfo=IST)
    h.repo.state.profile = Profile(**PROFILE)
    h.ai.responses.append(question_set(10))
    h.repo.enqueue("weekly", {"type": "schedule", "kind": "weekly", "date": "2026-09-26"})
    h.runtime.recover(media=False)
    previous = h.repo.state.active_assessment
    h.repo.state.lessons["ec2"] = {
        "topic": "AWS EC2",
        "date": "2026-09-26",
        "delivered_at": h.clock.now.isoformat(),
    }
    h.repo.enqueue(
        "requested", {"type": "schedule", "kind": "quiz", "date": "2026-09-26", "requested_topic": "AWS EC2"}
    )
    h.runtime.recover(media=False)
    assert h.repo.state.active_assessment == previous
    assert h.repo.state.assessments[previous].status == "active"
    assert len(h.ai.calls) == 1 and h.repo.jobs["requested"]["status"] == "failed"


@pytest.mark.postgres
def test_future_quiz_cannot_be_claimed_early_and_duplicate_queue_keeps_due_time(pg_repo, config):
    due = datetime.now(timezone.utc) + timedelta(days=1)
    runtime = Runtime(
        config, pg_repo, FakeAI(), FakeTelegram(), FakePublisher(), lambda: due - timedelta(hours=2)
    )
    first = queue_owner_quiz(runtime, due, "AWS EC2")
    assert first["created"]
    assert not queue_owner_quiz(runtime, due + timedelta(minutes=10), "AWS IAM")["created"]
    token = pg_repo.acquire("domain", 60)
    try:
        assert pg_repo.next_job(token) is None
    finally:
        pg_repo.release("domain", token)
    with pg_repo.connection() as conn:
        row = conn.execute(
            "SELECT learner_id,available_at,payload FROM jobs WHERE id=%s", (first["job"],)
        ).fetchone()
        assert row["learner_id"] == "owner"
        assert row["available_at"] == due
        assert row["payload"]["requested_topic"] == "AWS EC2"
        assert conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 1


@pytest.mark.postgres
def test_due_requested_quiz_retry_does_not_duplicate_session(pg_repo, config):
    due = datetime.now(timezone.utc) + timedelta(days=1)
    ai = FakeAI()
    runtime = Runtime(config, pg_repo, ai, FakeTelegram(), FakePublisher(), lambda: due - timedelta(hours=2))
    day = due.astimezone(IST).date().isoformat()
    seed(
        pg_repo,
        lambda state: state.lessons.update(
            {"ec2": {"topic": "AWS EC2", "date": day, "delivered_at": due.isoformat()}}
        ),
    )
    result = queue_owner_quiz(runtime, due, "AWS EC2")
    with pg_repo.connection() as conn:
        conn.execute("UPDATE jobs SET available_at=now()-interval '1 second' WHERE id=%s", (result["job"],))
    runtime.clock = lambda: due + timedelta(minutes=1)
    ai.responses.extend([ExternalError("temporary_provider_failure"), question_set(5)])
    runtime.recover(media=False)
    assert not pg_repo.read()[1].assessments
    with pg_repo.connection() as conn:
        conn.execute("UPDATE jobs SET available_at=now() WHERE id=%s", (result["job"],))
    runtime.recover(media=False)
    assert len(pg_repo.read()[1].assessments) == 1
    runtime.recover(media=False)
    assert len(pg_repo.read()[1].assessments) == 1 and len(ai.calls) == 2
