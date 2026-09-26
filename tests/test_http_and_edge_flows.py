import json
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest
import requests
from pydantic import ValidationError
from test_flows import PROFILE, READINESS, command, question_set

from skillcoach.clients import AI, HTTP, Budget, ExternalError, Telegram
from skillcoach.models import Answer, Assessment, Profile, Readiness
from skillcoach.timeutil import IST


class Response:
    def __init__(self, status, body):
        self.status_code = status
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        yield json.dumps(self.body).encode()


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_transient_http_retries_and_permanent_failures_are_explicit():
    session = Session([Response(503, {}), Response(200, {"ok": True})])
    status, body = HTTP(session).call("GET", "https://example.invalid", budget=Budget())
    assert status == 200 and body["ok"] and len(session.calls) == 2
    timeout = session.calls[0][2]["timeout"]
    assert timeout[0] <= 3 and timeout[1] <= 8
    session = Session([Response(401, {"private": "do not log"})])
    with pytest.raises(ExternalError, match="http_401"):
        HTTP(session).call("GET", "https://example.invalid", budget=Budget())
    assert len(session.calls) == 1
    session = Session([requests.Timeout("secret-bearing URL"), requests.Timeout("secret-bearing URL")])
    with pytest.raises(ExternalError, match="network_unavailable") as exc:
        HTTP(session).call("GET", "https://example.invalid", budget=Budget())
    assert "secret" not in str(exc.value)


def test_telegram_transport_and_api_ok_false_are_not_silent(config):
    telegram = Telegram(config, HTTP(Session([Response(200, {"ok": False})])))
    with pytest.raises(ExternalError, match="telegram_rejected"):
        telegram.send("private", Budget())
    session = Session([Response(500, {})])
    telegram = Telegram(config, HTTP(session))
    with pytest.raises(ExternalError):
        telegram.send("private", Budget())
    assert len(session.calls) == 1  # Do not blindly duplicate uncertain Telegram sends.


def test_actual_groq_then_gemini_dispatch_and_no_provider(config):
    config = replace(config, groq_key="fake-groq", gemini_key="fake-gemini")
    session = Session(
        [
            Response(401, {}),
            Response(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(READINESS)}]}}]}),
        ]
    )
    result = AI(config, HTTP(session)).structured("diagnostic", Readiness, Budget())
    assert result.readiness_score == 61
    assert "groq.com" in session.calls[0][1]
    assert "generativelanguage.googleapis.com" in session.calls[1][1]
    assert session.calls[0][2]["headers"]["Authorization"] == "Bearer fake-groq"
    assert "fake-gemini" not in session.calls[1][1]
    with pytest.raises(ExternalError):
        AI(replace(config, groq_key="", gemini_key="")).structured("diagnostic", Readiness, Budget())


@pytest.mark.parametrize("invalid", [None, -1, 101, True, "50", 5.5])
def test_invalid_readiness_never_becomes_fifty(invalid):
    with pytest.raises(ValidationError):
        Readiness.model_validate({**READINESS, "readiness_score": invalid})


def test_daily_exact_five_completes_and_invalid_answer_does_not_advance(harness):
    h = harness
    h.repo.state.profile = Profile(**PROFILE)
    h.repo.state.lessons["today"] = {"topic": "IAM", "date": "2026-09-25"}
    h.ai.responses.append(question_set(5))
    h.repo.enqueue("quiz", {"type": "schedule", "kind": "quiz", "date": "2026-09-25"})
    h.runtime.recover(media=False)
    command(h, "/q AB")
    session = next(iter(h.repo.state.assessments.values()))
    assert len(session.answers) == 0
    for _ in range(5):
        command(h, "/q B")
    session = next(iter(h.repo.state.assessments.values()))
    assert session.status == "completed" and len(session.answers) == 5


@pytest.mark.parametrize("count", [5, 9])
def test_weekly_wrong_count_remains_unavailable(harness, count):
    h = harness
    h.clock.now = datetime(2026, 9, 26, 9, tzinfo=IST)
    h.repo.state.profile = Profile(**PROFILE)
    h.ai.responses.append(question_set(count))
    h.repo.enqueue("weekly", {"type": "schedule", "kind": "weekly", "date": "2026-09-26"})
    h.runtime.recover(media=False)
    assert h.repo.jobs["weekly"]["status"] == "failed"
    assert not h.repo.state.assessments


@pytest.mark.parametrize(
    "status,week,expected",
    [
        ("active", "2026-W39", "unavailable"),
        ("completed", "2026-W38", "unavailable"),
        ("completed", "2026-W39", "Weekly assessment: 10/10"),
    ],
)
def test_review_only_scores_completed_current_week(harness, status, week, expected):
    h = harness
    h.clock.now = datetime(2026, 9, 27, 10, tzinfo=IST)
    h.repo.state.profile = Profile(**PROFILE)
    completed = datetime(2026, 9, 26 if week == "2026-W39" else 19, 10, tzinfo=IST)
    questions = question_set(10)["questions"]
    session = Assessment(
        id="weekly",
        kind="weekly",
        date=completed.date(),
        week=week,
        questions=questions,
        question_ids=[str(i) for i in range(10)],
        status=status,
        answers=[
            Answer(question_id=str(i), given="B", correct=True, created_at=completed)
            for i in range(10 if status == "completed" else 2)
        ],
        completed_at=completed if status == "completed" else None,
    )
    h.repo.state.assessments[session.id] = session
    monday = date(2026, 9, 28)
    h.ai.responses.append(
        {
            "days": {(monday + timedelta(days=i)).isoformat(): "IAM" for i in range(6)},
            "rationale": "Targeted revision",
        }
    )
    h.repo.enqueue("review", {"type": "schedule", "kind": "review", "date": "2026-09-27"})
    h.runtime.recover(media=False)
    assert expected in h.telegram.messages[-1][0]


def test_delayed_schedule_does_not_replay_or_increment_learning(harness):
    h = harness
    h.repo.state.profile = Profile(**PROFILE)
    h.repo.enqueue("yesterday", {"type": "schedule", "kind": "lesson", "date": "2026-09-24"})
    h.runtime.recover(media=False)
    assert not h.ai.calls and not h.telegram.messages and not h.repo.state.tasks


def test_generated_full_lesson_has_stable_tasks_and_video_default(harness):
    from lesson_content import LESSONS

    h = harness
    generated = json.loads(json.dumps(LESSONS["ec2"]))
    generated["title"] = "Python full practice"
    generated["reviewed_at"] = "AI-generated; not independently reviewed"
    h.ai.responses.append(generated)
    from skillcoach.storyboard import reviewed_architecture

    h.ai.responses.extend([reviewed_architecture("EC2").model_dump() for _ in range(5)])
    command(h, "/learn Python")
    assert len(h.repo.state.tasks) == 3
    assert len(h.ai.calls) == 6
    assert len([o for o in h.repo.outbox.values() if o["body"]["kind"] == "media"]) == 5
    assert all(t.skill == "python" for t in h.repo.state.tasks.values())
    command(h, "/learn Python")
    assert len(h.repo.state.tasks) == 3 and len(h.ai.calls) == 6
