import json
from dataclasses import replace

import pytest
from pydantic import Field
from test_http_and_edge_flows import Response, Session

from skillcoach import clients
from skillcoach.clients import AI, HTTP, Budget, ExternalError
from skillcoach.config import DEFAULT_GEMINI_MODELS, DEFAULT_GROQ_MODELS, Config, ConfigurationError
from skillcoach.models_base import Model
from skillcoach.runtime import WORKER_STEP_SECONDS, Runtime


class Reply(Model):
    items: list[str] = Field(min_length=1, max_length=2)


class Failure(Response):
    def __init__(self, status, body=None, headers=None):
        super().__init__(status, body if body is not None else {})
        self.headers = headers or {}


def groq_ok(body):
    return Response(200, {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(body)}}]})


def gemini_ok(body):
    return Response(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(body)}]}}]})


def daily_limit():
    return Failure(
        429,
        {"error": {"message": "private org text on tokens per day (TPD): Limit 200000", "type": "tokens"}},
        {"retry-after": "1800", "x-ratelimit-remaining-requests": "990", "x-ratelimit-remaining-tokens": "0"},
    )


def legacy_model():
    return Failure(404, {"error": {"status": "NOT_FOUND", "message": "private detail about models/x"}})


def ai(config, session, **changes):
    values = {"groq_key": "private-groq", "gemini_key": "private-gemini", **changes}
    return AI(replace(config, **values), HTTP(session))


def test_daily_limit_and_legacy_model_fall_through_to_a_current_model(config, caplog, monkeypatch):
    sleeps = []
    monkeypatch.setattr(clients.time, "sleep", sleeps.append)
    session = Session([daily_limit(), legacy_model(), gemini_ok({"items": ["ok"]})])
    result = ai(
        config, session, groq_model="openai/gpt-oss-120b", gemini_model="gemini-2.5-flash,gemini-3.8-flash"
    ).structured("private prompt", Reply, Budget())
    assert result.items == ["ok"] and not sleeps  # A 30-minute window is never slept on or retried.
    urls = [call[1] for call in session.calls]
    assert "groq.com" in urls[0] and "gemini-2.5-flash:" in urls[1] and "gemini-3.8-flash:" in urls[2]
    assert "limit=TPD" in caplog.text and "retry_after=1800" in caplog.text
    assert "remaining_tokens=0" in caplog.text and "status=NOT_FOUND" in caplog.text
    assert "model=gemini-2.5-flash code=http_404" in caplog.text
    assert "private" not in caplog.text


def test_short_provider_window_is_waited_once_within_budget(config, monkeypatch):
    sleeps = []
    monkeypatch.setattr(clients.time, "sleep", sleeps.append)
    session = Session([Failure(429, headers={"retry-after": "2"}), groq_ok({"items": ["ok"]})])
    assert ai(config, session, gemini_key="").structured("prompt", Reply, Budget(20)).items == ["ok"]
    assert sleeps == [2.0] and len(session.calls) == 2


def test_route_order_uses_extra_groq_models_only_after_gemini(config, monkeypatch):
    monkeypatch.setattr(clients.time, "sleep", lambda _: None)
    session = Session([daily_limit(), legacy_model(), legacy_model(), groq_ok({"items": ["last resort"]})])
    service = ai(config, session, groq_model="openai/gpt-oss-120b,openai/gpt-oss-20b", gemini_model="a,b")
    assert service.routes() == [
        ("groq", "openai/gpt-oss-120b"),
        ("gemini", "a"),
        ("gemini", "b"),
        ("groq", "openai/gpt-oss-20b"),
    ]
    assert service.structured("prompt", Reply, Budget()).items == ["last resort"]
    assert session.calls[3][2]["json"]["model"] == "openai/gpt-oss-20b"


def test_rejected_credentials_skip_the_rest_of_that_provider(config):
    session = Session([Failure(401), gemini_ok({"items": ["ok"]})])
    service = ai(config, session, groq_model="openai/gpt-oss-120b,openai/gpt-oss-20b", gemini_model="g")
    assert service.structured("prompt", Reply, Budget()).items == ["ok"]
    assert len(session.calls) == 2


def test_worker_budget_repairs_invalid_json_once_with_safe_hints(config, caplog):
    session = Session([groq_ok({"items": ["private-a", "b", "c"]}), groq_ok({"items": ["a", "b"]})])
    service = ai(config, session, gemini_key="", groq_model="openai/gpt-oss-120b")
    assert service.structured("prompt", Reply, Budget(WORKER_STEP_SECONDS)).items == ["a", "b"]
    repaired = session.calls[1][2]["json"]["messages"][1]["content"]
    assert "YOUR PREVIOUS RESPONSE WAS REJECTED BY VALIDATION" in repaired
    assert "items: List should have at most 2 items" in repaired
    assert "validation=too_long repair=false" in caplog.text
    assert "private" not in caplog.text


def test_semantic_validator_failures_are_repaired_and_bounded(config):
    session = Session([groq_ok({"items": ["x"]}), groq_ok({"items": ["x"]}), groq_ok({"items": ["y"]})])
    service = ai(config, session, gemini_key="", groq_model="m1,m2")

    def validate(result):
        if result.items != ["y"]:
            raise ValueError("Use exactly the approved item")

    assert service.structured("prompt", Reply, Budget(WORKER_STEP_SECONDS), validate).items == ["y"]
    assert "Use exactly the approved item" in session.calls[1][2]["json"]["messages"][1]["content"]
    assert [call[2]["json"]["model"] for call in session.calls] == ["m1", "m1", "m2"]


def test_request_budgets_never_spend_time_on_repairs(config):
    session = Session([groq_ok({"items": ["a", "b", "c"]})])
    with pytest.raises(ExternalError, match="ai_unavailable_or_invalid"):
        ai(config, session, gemini_key="", groq_model="only").structured("prompt", Reply, Budget(20))
    assert len(session.calls) == 1


def test_gemini_requests_json_and_ignores_thought_parts(config):
    body = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "private reasoning", "thought": True}, {"text": '{"items": ["ok"]}'}]
                }
            }
        ]
    }
    session = Session([Response(200, body)])
    service = ai(config, session, groq_key="", gemini_model="gemini-3.8-flash")
    assert service.structured("prompt", Reply, Budget()).items == ["ok"]
    generation = session.calls[0][2]["json"]["generationConfig"]
    assert generation == {"maxOutputTokens": 16384, "responseMimeType": "application/json"}


def test_model_chain_configuration(monkeypatch):
    for name, value in {
        "DATABASE_URL": "postgresql://test-only",
        "TELEGRAM_BOT_TOKEN": "fake",
        "OWNER_ID": "42",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.setenv("GEMINI_MODEL", "")
    config = Config.from_env()
    assert config.groq_model == DEFAULT_GROQ_MODELS and config.gemini_model == DEFAULT_GEMINI_MODELS
    assert DEFAULT_GEMINI_MODELS.split(",")[0] == "gemini-3.8-flash"
    monkeypatch.setenv("GROQ_MODEL", " openai/gpt-oss-120b , openai/gpt-oss-20b ,openai/gpt-oss-120b")
    assert AI(replace(Config.from_env(), groq_key="k")).routes() == [
        ("groq", "openai/gpt-oss-120b"),
        ("groq", "openai/gpt-oss-20b"),
    ]
    for bad in ("a b", "a,b,c,d,e", ",,", "x" * 101):
        monkeypatch.setenv("GROQ_MODEL", bad)
        with pytest.raises(ConfigurationError):
            Config.from_env()


class LeaseProbe:
    owner_id = None

    def __init__(self):
        self.leases = []

    def acquire(self, name, seconds):
        self.leases.append((name, seconds))
        return None


def test_worker_lease_outlives_the_background_budget(config):
    repo = LeaseProbe()
    runtime = Runtime(config, repository=repo, ai=object(), telegram=object(), publisher=object())
    assert runtime.process_one(Budget(20)) is False
    assert runtime.process_one(Budget(WORKER_STEP_SECONDS)) is False
    assert repo.leases[0] == ("domain", 60)
    assert repo.leases[1][1] >= WORKER_STEP_SECONDS + 39


def test_recover_gives_each_step_the_worker_budget(config, monkeypatch):
    runtime = Runtime(config, repository=LeaseProbe(), ai=object(), telegram=object(), publisher=object())
    seen = []

    class NoSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    runtime.repo.session = NoSession
    monkeypatch.setattr(runtime, "process_one", lambda budget: seen.append(budget.remaining()) or False)
    monkeypatch.setattr(runtime, "deliver_one", lambda *args, **kwargs: False)
    runtime.recover(media=False)
    assert len(seen) == 1 and seen[0] > WORKER_STEP_SECONDS - 5
