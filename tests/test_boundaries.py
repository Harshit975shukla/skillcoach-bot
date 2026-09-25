import importlib
import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from lesson_content import LESSONS
from skillcoach.cli import schedule_key
from skillcoach.clients import AI, Budget, ExternalError, Publisher, chunks
from skillcoach.commands import COMMANDS, help_text
from skillcoach.config import Config, ConfigurationError
from skillcoach.export import public_export
from skillcoach.models import (
    Interview,
    InterviewFeedback,
    Lesson,
    OpenQuestion,
    Profile,
    Question,
    State,
    Task,
    WeekPlan,
)
from skillcoach.service import CoachingText
from skillcoach.timeutil import IST, streak, week_key
from skillcoach.web import create_app


def update(text="/help", ident=1):
    return {
        "update_id": ident,
        "message": {"from": {"id": 42}, "chat": {"id": 42, "type": "private"}, "text": text},
    }


def test_config_fail_closed(monkeypatch):
    for name in ("DATABASE_URL", "TELEGRAM_BOT_TOKEN", "OWNER_ID", "CHAT_ID", "TELEGRAM_WEBHOOK_SECRET"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConfigurationError):
        Config.from_env(webhook=True)
    monkeypatch.setenv("DATABASE_URL", "postgresql://private")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake")
    monkeypatch.setenv("OWNER_ID", "0")
    with pytest.raises(ConfigurationError):
        Config.from_env()
    monkeypatch.setenv("OWNER_ID", "42")
    with pytest.raises(ConfigurationError):
        Config.from_env(webhook=True)


def test_empty_owner_setting_keeps_legacy_chat_id_alias(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://private")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake")
    monkeypatch.setenv("OWNER_ID", "")
    monkeypatch.setenv("CHAT_ID", "42")
    assert Config.from_env().owner_id == 42
    monkeypatch.setenv("OWNER_ID", "84")
    assert Config.from_env().owner_id == 84


def test_webhook_auth_dedup_edits_callbacks_and_no_threads(harness):
    h = harness
    client = create_app(h.runtime).test_client()
    headers = {"X-Telegram-Bot-Api-Secret-Token": "a" * 32}
    assert client.post("/", json=update()).status_code == 403
    assert (
        client.post(
            "/", json=update(), headers={**headers, "X-Telegram-Bot-Api-Secret-Token": "bad"}
        ).status_code
        == 403
    )
    other = update()
    other["message"]["from"]["id"] = 99
    assert client.post("/", json=other, headers=headers).status_code == 403
    assert not h.repo.jobs
    edited = update()
    edited["edited_message"] = edited.pop("message")
    assert client.post("/", json=edited, headers=headers).status_code == 200
    assert not h.repo.jobs
    for _ in range(2):
        assert client.post("/", json=update(), headers=headers).status_code == 202
    assert len(h.repo.jobs) == 1
    callback = {
        "update_id": 3,
        "callback_query": {
            "id": "callback",
            "data": "q:old:old:A",
            "from": {"id": 42},
            "message": {"chat": {"id": 42, "type": "private"}},
        },
    }
    assert client.post("/", json=callback, headers=headers).status_code == 202
    assert h.telegram.acks == ["callback"]
    assert "Thread" not in Path("skillcoach/web.py").read_text()


@pytest.mark.parametrize("payload", [None, [], {}, {"update_id": True}, {"update_id": -1}])
def test_invalid_updates(harness, payload):
    client = create_app(harness.runtime).test_client()
    assert (
        client.post("/", json=payload, headers={"X-Telegram-Bot-Api-Secret-Token": "a" * 32}).status_code
        == 400
    )


def test_storage_failure_is_retryable_http(harness, monkeypatch):
    import psycopg

    def fail(*args):
        raise psycopg.OperationalError("private connection string must not be returned")

    monkeypatch.setattr(harness.repo, "enqueue", fail)
    response = (
        create_app(harness.runtime)
        .test_client()
        .post("/", json=update(), headers={"X-Telegram-Bot-Api-Secret-Token": "a" * 32})
    )
    assert response.status_code == 503
    assert "private connection" not in response.get_data(as_text=True)


def test_provider_dispatch_fallback_and_invalid_json(config, monkeypatch):
    ai = AI(replace(config, groq_key="fake", gemini_key="fake"))
    calls = []

    def groq(prompt, budget):
        calls.append("groq")
        return '{"text": 123}'

    def gemini(prompt, budget):
        calls.append("gemini")
        return '{"text":"valid answer"}'

    monkeypatch.setattr(ai, "ask_groq", groq)
    monkeypatch.setattr(ai, "ask_gemini", gemini)
    assert ai.structured("question", CoachingText, Budget()).text == "valid answer"
    assert calls == ["groq", "gemini"]
    monkeypatch.setattr(ai, "ask_gemini", lambda *args: "not json")
    with pytest.raises(ExternalError):
        ai.structured("question", CoachingText, Budget())


def test_question_shape_dates_and_utf16_chunks():
    with pytest.raises(ValidationError):
        Question(question="Q", options={"A": "a"}, answer="E", explanation="bad", topic="x")
    start = date(2026, 9, 28)
    plan = WeekPlan(days={start + timedelta(days=i): "IAM" for i in range(6)}, rationale="Revision")
    assert plan.validate_dates(start)
    with pytest.raises(ValueError):
        plan.validate_dates(start + timedelta(days=7))
    text = "\U0001f600" * 5000 + "end"
    parts = chunks(text)
    assert "".join(parts) == text
    assert all(len(part.encode("utf-16-le")) // 2 <= 3500 for part in parts)


def test_ist_boundaries_streak_and_schedule_selection():
    assert datetime(2026, 9, 25, 18, 30, tzinfo=timezone.utc).astimezone(IST).date() == date(2026, 9, 26)
    today = date(2026, 9, 25)
    assert streak([today, today, today - timedelta(days=1)], today) == 2
    assert streak([today - timedelta(days=2)], today) == 0
    assert streak([today - timedelta(days=1)], today) == 1
    assert week_key(date(2027, 1, 1)) == "2026-W53"
    assert schedule_key("lesson", today) == schedule_key("lesson", today)
    with pytest.raises(ValueError):
        schedule_key("weekly", date(2026, 9, 27))


def test_export_contract_and_recursive_privacy():
    now = datetime(2026, 9, 25, 18, tzinfo=IST)
    private = "PRIVATE-SENTINEL-SECRET"
    state = State(
        profile=Profile(
            name=private,
            current_role=private,
            target_role=private,
            level="advanced",
            years_experience=5,
            skills=[private],
            resume_text=private,
            jd_text=private,
        ),
        legacy_archive={"chat_id": 987654321, "answer_key": private},
    )
    state.tasks[private] = Task(
        id=private,
        origin=private,
        title=private,
        skill=private,
        detail=private,
        assigned_date=now.date(),
        estimated_minutes=30,
        actual_minutes=12,
    )
    state.interviews[private] = Interview(
        id=private,
        question=OpenQuestion(skill=private, question=private),
        answer=private,
        status="completed",
        completed_at=now,
        feedback=InterviewFeedback(
            score=8, accuracy=8, reasoning=8, communication=8, feedback=private, model_answer=private
        ),
    )
    document = public_export(state, now)
    encoded = json.dumps(document)
    assert private not in encoded and "987654321" not in encoded
    assert "answer_key" not in encoded and "chat_id" not in encoded
    assert document["resume"] is None
    assert document["stats"]["pending"] == 1 and document["stats"]["minutes_practiced"] == 0
    assert document["stats"]["avg_answer_score"] == 8
    assert set(document["profile"]) == {"name", "target_role", "level", "reminder", "timezone", "paused"}
    assert len(document["activity"]) == 30
    assert set(document["activity"][0]) == {"date", "done", "pending", "skipped"}
    assert set(document["skills"][0]) == {"skill", "done", "total"}
    assert isinstance(document["open_tasks"][0]["id"], int)
    assert set(document["open_tasks"][0]) == {
        "id",
        "title",
        "detail",
        "skill",
        "difficulty",
        "est_minutes",
        "overdue_days",
    }
    assert set(document["recent_answers"][0]) == {"score", "created_at", "question", "feedback"}


def test_publisher_conflict_does_not_refresh_and_overwrite(config):
    class FakeHTTP:
        def __init__(self):
            self.calls = []

        def call(self, method, url, **kwargs):
            self.calls.append(method)
            return 200, {"sha": "changed-by-other-writer", "content": ""}

    http = FakeHTTP()
    publisher = Publisher(replace(config, github_token="fake", dashboard_repo="owner/repo"), http)
    with pytest.raises(ExternalError, match="github_conflict"):
        publisher.publish({"schema_version": 1}, Budget(), {"sha": "original"})
    assert http.calls == ["GET"]


def test_authored_models_and_no_import_configuration():
    for lesson in LESSONS.values():
        result = Lesson.model_validate(lesson)
        assert len(result.concepts) == 4 and len(result.tasks) == 3
        assert result.reviewed_at == "2026-09-25"
        assert "cost" in result.safety.lower() or "prices" in result.safety.lower()
    for module in (
        "api.webhook",
        "bot",
        "morning_lesson",
        "evening_quiz",
        "weekend_test",
        "sunday_plan",
        "reminder",
    ):
        importlib.import_module(module)
    for name in COMMANDS:
        assert f"/{name} - " in help_text()


def test_production_schema_is_private_and_identifiers_are_validated():
    from skillcoach.storage import Repository

    assert Repository("postgresql://fake").schema == "skillcoach_private"
    with pytest.raises(ValueError, match="schema"):
        Repository("postgresql://fake", schema="public; DROP SCHEMA public")


def test_readiness_authenticates_before_reading_private_storage(harness, monkeypatch):
    client = create_app(harness.runtime).test_client()
    reads = []
    original = harness.repo.read

    def read():
        reads.append(True)
        return original()

    monkeypatch.setattr(harness.repo, "read", read)
    assert client.get("/health/ready").status_code == 403
    assert reads == []
    response = client.get(
        "/health/ready", headers={"X-Telegram-Bot-Api-Secret-Token": harness.runtime.config.webhook_secret}
    )
    assert response.status_code == 200 and response.json["private_storage"] is True
    assert len(reads) == 1 and "profile" not in response.json
