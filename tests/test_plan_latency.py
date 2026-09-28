from contextlib import contextmanager
from datetime import datetime, timedelta

import psycopg
import pytest
from conftest import FakeAI, FakePublisher, FakeTelegram
from psycopg.pq import TransactionStatus
from test_flows import READINESS, command
from test_journey import core_guide, proposal, setup, shared_journey

from skillcoach.clients import Budget, ExternalError
from skillcoach.runtime import Runtime
from skillcoach.timeutil import IST
from skillcoach.web import create_app


@pytest.mark.parametrize("grading_seconds,proposal_ready", [(2, True), (10, False)])
def test_fast_proposal_shares_original_budget_and_slow_grading_defers(
    harness, monkeypatch, grading_seconds, proposal_ready
):
    h = harness
    setup(h)
    for index in range(4):
        command(h, f"Actual answer {index}")
    h.ai.responses.extend([READINESS, proposal()])
    elapsed = [0.0]
    seen_budgets = []
    original = h.ai.structured

    def measured(prompt, model, budget, validate=None):
        seen_budgets.append(budget)
        elapsed[0] += grading_seconds if model.__name__ == "Readiness" else 2
        return original(prompt, model, budget, validate)

    monkeypatch.setattr("skillcoach.clients.time.monotonic", lambda: elapsed[0])
    monkeypatch.setattr(h.ai, "structured", measured)
    headers = {"X-Telegram-Bot-Api-Secret-Token": h.runtime.config.webhook_secret}
    payload = {
        "update_id": 91001,
        "message": {"from": {"id": 42}, "chat": {"id": 42, "type": "private"}, "text": "Fifth actual answer"},
    }
    client = create_app(h.runtime).test_client()
    assert client.post("/", json=payload, headers=headers).status_code == 202
    j = h.repo.state.journey
    assert len(j.diagnostic_answers) == 5 and len(h.repo.answer_keys) == 5
    assert (j.stage == "ready") == proposal_ready
    if proposal_ready:
        assert len(seen_budgets) == 2 and seen_budgets[0] is seen_budgets[1]
        assert seen_budgets[0].end == 20
        assert h.repo.jobs["telegram:91001:next"]["status"] == "done"
        messages = [text for text, _ in h.telegram.messages]
        assert next(
            i for i, text in enumerate(messages) if "five diagnostic answers are saved" in text
        ) < next(i for i, text in enumerate(messages) if "Proposed study week" in text)
    else:
        assert len(seen_budgets) == 1
        assert h.repo.jobs["telegram:91001:next"]["status"] == "pending"
        h.runtime.recover(media=False)
        assert h.repo.state.journey.stage == "ready"
    answers = h.repo.answer_keys.copy()
    calls = len(h.ai.calls)
    assert client.post("/", json=payload, headers=headers).status_code == 202
    assert h.repo.answer_keys == answers and len(h.ai.calls) == calls


def test_fast_path_never_processes_day_one_lesson_or_an_older_job(harness):
    h = harness
    h.repo.enqueue("telegram:91234:next", {"type": "journey", "journey_id": "test", "action": "lesson"})
    h.runtime.followup_proposal(91234, Budget())
    assert h.repo.jobs["telegram:91234:next"]["status"] == "pending"
    assert not h.ai.calls
    h.repo.jobs["telegram:91234:next"]["payload"]["action"] = "propose"
    h.repo.enqueue("earlier", {"type": "telegram", "text": "/cancel"})
    h.runtime.followup_proposal(91234, Budget())
    assert h.repo.jobs["earlier"]["status"] == "pending"
    assert not h.ai.calls


def test_proposal_failure_is_recoverable_without_regrading(harness):
    h = harness
    setup(h)
    for _ in range(4):
        command(h, "Actual answer")
    h.ai.responses.extend([READINESS, ExternalError("rate_limited")])
    response = (
        create_app(h.runtime)
        .test_client()
        .post(
            "/",
            json={
                "update_id": 91002,
                "message": {
                    "from": {"id": 42},
                    "chat": {"id": 42, "type": "private"},
                    "text": "Fifth answer",
                },
            },
            headers={"X-Telegram-Bot-Api-Secret-Token": h.runtime.config.webhook_secret},
        )
    )
    assert response.status_code == 202
    assert h.repo.state.journey.stage == "planning"
    assert len(h.repo.answer_keys) == 5
    assert h.repo.jobs["telegram:91002:next"]["status"] == "failed"
    h.ai.responses.append(proposal())
    command(h, "/retry")
    assert h.repo.state.journey.stage == "ready"
    assert len([call for call in h.ai.calls if call[1] == "Readiness"]) == 1


@pytest.mark.postgres
@pytest.mark.parametrize(
    "payload",
    [
        {"type": "journey", "action": "lesson", "journey_id": "test"},
        {"type": "telegram", "text": "/learn EC2"},
        {"type": "schedule", "kind": "lesson", "date": "2026-09-28"},
    ],
)
def test_media_preflight_recognizes_all_lesson_entrypoints_and_honors_eligibility(pg_repo, payload):
    assert not pg_repo.needs_media()
    pg_repo.enqueue("lesson", payload, available_at=datetime.now(IST) + timedelta(days=1))
    assert not pg_repo.needs_media()
    with pg_repo.connection() as conn:
        conn.execute("UPDATE jobs SET available_at=now() WHERE id='lesson'")
    assert pg_repo.needs_media()
    with pg_repo.connection() as conn:
        conn.execute("UPDATE jobs SET access_generation=access_generation+1 WHERE id='lesson'")
    assert not pg_repo.needs_media()
    with pg_repo.connection() as conn:
        conn.execute("UPDATE jobs SET access_generation=1,status='cancelled' WHERE id='lesson'")
    assert not pg_repo.needs_media()
    with pg_repo.connection() as conn:
        conn.execute("UPDATE jobs SET status='failed',attempts=5 WHERE id='lesson'")
    assert not pg_repo.needs_media()


@pytest.mark.postgres
def test_preflight_omits_revoked_learners_and_nonmedia_proposals(pg_repo, config):
    from test_multiuser import Bot

    bot = Bot(pg_repo, config)
    learner = bot.join(101)
    learner.enqueue("proposal", {"type": "journey", "action": "propose", "journey_id": "test"})
    assert not pg_repo.needs_media()
    learner.enqueue("lesson", {"type": "journey", "action": "lesson", "journey_id": "test"})
    assert pg_repo.needs_media()
    bot.input(config.owner_id, "/revoke " + learner.learner_id, drain=False)
    assert not pg_repo.needs_media()


@pytest.mark.postgres
def test_proposal_selection_does_not_jump_over_other_learner_or_backoff(pg_repo, config):
    from test_multiuser import Bot

    bot = Bot(pg_repo, config)
    other = bot.join(101)
    other.enqueue("earlier", {"type": "telegram", "text": "/help"})
    pg_repo.enqueue("telegram:92000:next", {"type": "journey", "action": "propose", "journey_id": "test"})
    token = pg_repo.acquire("domain", 60)
    try:
        assert pg_repo.next_job(token, proposal_for="telegram:92000") is None
        with pg_repo.connection() as conn:
            assert (
                conn.execute("SELECT attempts FROM jobs WHERE id='telegram:92000:next'").fetchone()[
                    "attempts"
                ]
                == 0
            )
            conn.execute(
                "UPDATE jobs SET status='done' WHERE id=%s", (f"learner:{other.learner_id}:earlier",)
            )
            conn.execute(
                "UPDATE jobs SET available_at=now()+interval '5 minutes' WHERE id='telegram:92000:next'"
            )
        assert pg_repo.next_job(token, proposal_for="telegram:92000") is None
    finally:
        pg_repo.release("domain", token)


@pytest.mark.postgres
def test_fast_proposal_reuses_one_connection_and_never_holds_transactions_over_network(
    pg_repo, config, monkeypatch
):
    from test_multiuser import Bot

    bot = Bot(pg_repo, config)
    journey = shared_journey(bot.runtime.clock())
    journey.stage, journey.plans, journey.active_id = "diagnostic", {}, None
    journey.diagnostic_answers = ["real answer"] * 4
    journey.diagnostic_questions = [{"skill": "cloud", "question": f"Explain {i}"} for i in range(5)]

    def initialize(state):
        state.journey, state.focus = journey, "onboarding"

    bot.save(pg_repo, initialize)
    with pg_repo.connection() as conn:
        from psycopg.types.json import Jsonb

        conn.execute(
            "UPDATE coach_state SET displayed_target=%s WHERE learner_id='owner'", (Jsonb(journey.target()),)
        )
    bot.runtime.ai.responses.extend([READINESS, proposal()])
    connections = []
    real_connect = psycopg.connect

    @contextmanager
    def tracked(*args, **kwargs):
        connections.append(True)
        with real_connect(*args, **kwargs) as conn:
            yield conn

    monkeypatch.setattr("skillcoach.storage.psycopg.connect", tracked)
    original_ai = bot.runtime.ai.structured
    original_send = bot.runtime.telegram.send

    def ai(*args, **kwargs):
        assert pg_repo._session_connection.get().info.transaction_status == TransactionStatus.IDLE
        return original_ai(*args, **kwargs)

    def send(*args, **kwargs):
        assert pg_repo._session_connection.get().info.transaction_status == TransactionStatus.IDLE
        return original_send(*args, **kwargs)

    monkeypatch.setattr(bot.runtime.ai, "structured", ai)
    monkeypatch.setattr(bot.runtime.telegram, "send", send)
    result = (
        create_app(bot.runtime)
        .test_client()
        .post(
            "/",
            json={
                "update_id": 93000,
                "message": {
                    "from": {"id": config.owner_id},
                    "chat": {"id": config.owner_id, "type": "private"},
                    "text": "Fifth answer",
                },
            },
            headers={"X-Telegram-Bot-Api-Secret-Token": config.webhook_secret},
        )
    )
    assert result.status_code == 202 and len(connections) == 1
    assert pg_repo._session_connection.get() is None
    assert pg_repo.read()[1].journey.stage == "ready"


@pytest.mark.postgres
def test_day_one_preflight_and_single_recovery_run_send_full_lesson(pg_repo, config, monkeypatch):
    from test_multiuser import Bot

    bot = Bot(pg_repo, config)
    now = datetime(2026, 9, 28, 9, tzinfo=IST)
    journey = shared_journey(now.replace(hour=8))
    bot.save(pg_repo, lambda state: setattr(state, "journey", journey))
    pg_repo.enqueue(
        "day-one",
        {
            "type": "journey",
            "journey_id": journey.id,
            "action": "lesson",
            "plan_id": journey.active_id,
            "date": now.date().isoformat(),
        },
    )
    assert pg_repo.needs_media()  # The workflow uses this before installing renderers.
    videos = []

    def render(telegram, body, budget, *, before_send, cached):
        before_send()
        videos.append(body)
        return {"file_id": f"synthetic-{len(videos)}", "kind": "video", "metadata": {"voice": False}}

    monkeypatch.setattr("skillcoach.runtime.deliver_storyboard", render)
    runtime = Runtime(config, pg_repo, FakeAI(), FakeTelegram(), FakePublisher(), lambda: now)
    runtime.ai.responses.append(core_guide())
    runtime.recover(media=pg_repo.needs_media())
    assert len(videos) == 1 and all(not b["voice"] for b in videos)
    state = pg_repo.read()[1]
    assert len(state.tasks) == 2
    assert all(lesson["delivered_at"] for lesson in state.lessons.values())
    with pg_repo.connection() as conn:
        assert conn.execute("SELECT status FROM jobs WHERE id='day-one'").fetchone()["status"] == "done"
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM outbox WHERE status NOT IN ('sent','suppressed')"
            ).fetchone()["n"]
            == 0
        )
    runtime.recover(media=True)
    assert len(videos) == 1
