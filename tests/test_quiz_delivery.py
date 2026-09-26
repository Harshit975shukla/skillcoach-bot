from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from threading import Barrier

import psycopg
import pytest
from conftest import FakeAI, FakePublisher, FakeTelegram
from psycopg.pq import TransactionStatus
from test_flows import PROFILE, question_set
from test_postgres import seed

from skillcoach.clients import ExternalError
from skillcoach.models import Profile
from skillcoach.runtime import Runtime
from skillcoach.storage import Repository
from skillcoach.timeutil import IST
from skillcoach.web import create_app


def test_connection_reuse_is_scoped_and_transactions_end_before_external_work(monkeypatch):
    connections = []

    class Connection:
        in_transaction = False
        transactions = 0

        @contextmanager
        def transaction(self):
            assert not self.in_transaction
            self.in_transaction = True
            self.transactions += 1
            try:
                yield
            finally:
                self.in_transaction = False

        def execute(self, statement):
            assert self.in_transaction

    @contextmanager
    def connect(*args, **kwargs):
        assert kwargs["autocommit"] is True
        connection = Connection()
        connections.append(connection)
        yield connection
        assert not connection.in_transaction

    monkeypatch.setattr("skillcoach.storage.psycopg.connect", connect)
    repo = Repository("postgresql://unused")
    with repo.session():
        for scoped in (repo, repo.for_learner("u_synthetic"), repo):
            with scoped.connection() as connection:
                assert connection is connections[0]
            assert not connection.in_transaction
        assert connections[0].transactions == 3
    with repo.connection():
        pass
    assert len(connections) == 2  # No process-global idle connection reused by future requests.


@pytest.mark.postgres
def test_answer_feedback_and_next_question_fit_budget_despite_slow_connect(pg_repo, config, monkeypatch):
    runtime = Runtime(
        config,
        pg_repo,
        FakeAI(),
        FakeTelegram(),
        FakePublisher(),
        lambda: datetime(2026, 9, 25, 18, tzinfo=IST),
    )

    def setup(state):
        state.profile = Profile(**PROFILE)
        state.lessons["today"] = {"topic": "EC2", "date": "2026-09-25"}

    seed(pg_repo, setup)
    runtime.ai.responses.append(question_set(5))
    pg_repo.enqueue("quiz", {"type": "schedule", "kind": "quiz", "date": "2026-09-25"})
    runtime.recover(media=False)
    target = pg_repo.read()[1].target()
    runtime.telegram.messages.clear()
    original_connect = psycopg.connect
    elapsed, connects = [0.0], []

    def slow_connect(*args, **kwargs):
        # One cold connection costs five seconds. Reconnecting for every repository operation
        # reproduces saved answers with no feedback before the webhook's 20-second budget ends.
        elapsed[0] += 5
        connects.append(True)
        return original_connect(*args, **kwargs)

    monkeypatch.setattr("skillcoach.storage.psycopg.connect", slow_connect)
    monkeypatch.setattr("skillcoach.clients.time.monotonic", lambda: elapsed[0])
    before_send = runtime.telegram.send

    def checked_send(text, budget, buttons=None):
        assert pg_repo._session_connection.get().info.transaction_status == TransactionStatus.IDLE
        assert budget.remaining() > 0
        elapsed[0] += 1
        return before_send(text, budget, buttons)

    monkeypatch.setattr(runtime.telegram, "send", checked_send)
    client = create_app(runtime).test_client()
    update = {
        "update_id": 81001,
        "callback_query": {
            "id": "test-callback",
            "from": {"id": config.owner_id},
            "message": {"chat": {"id": config.owner_id, "type": "private"}},
            "data": f"q:{target['session']}:{target['question']}:B",
        },
    }
    response = client.post(
        "/", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": config.webhook_secret}
    )
    assert response.status_code == 202
    assert len(connects) == 1
    assert elapsed[0] == 7
    assert len(runtime.telegram.messages) == 2
    assert "Correct." in runtime.telegram.messages[0][0]
    assert "question 2/5" in runtime.telegram.messages[1][0]
    assert runtime.telegram.messages[1][1] is not None
    assert pg_repo._session_connection.get() is None
    monkeypatch.setattr("skillcoach.storage.psycopg.connect", original_connect)
    state = pg_repo.read()[1]
    assert len(state.assessments[target["session"]].answers) == 1
    with pg_repo.connection() as conn:
        displayed = conn.execute(
            "SELECT displayed_target FROM coach_state WHERE learner_id='owner'"
        ).fetchone()
        assert displayed["displayed_target"] == state.target()
        assert conn.execute("SELECT count(*) AS n FROM answer_keys").fetchone()["n"] == 1
    # Telegram's duplicate update cannot grade again or redeliver already-sent feedback.
    assert (
        client.post(
            "/", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": config.webhook_secret}
        ).status_code
        == 202
    )
    assert len(runtime.telegram.messages) == 2
    assert len(pg_repo.read()[1].assessments[target["session"]].answers) == 1


@pytest.mark.postgres
def test_reused_connection_rolls_back_only_failed_operation_and_keeps_session_usable(pg_repo):
    with pg_repo.session():
        with pytest.raises(psycopg.errors.UniqueViolation):
            with pg_repo.connection() as conn:
                conn.execute("INSERT INTO jobs(id,payload) VALUES ('rolled-back','{}')")
                conn.execute("INSERT INTO jobs(id,payload) VALUES ('rolled-back','{}')")
        with pg_repo.connection() as conn:
            assert conn.execute("SELECT count(*) AS n FROM jobs WHERE id='rolled-back'").fetchone()["n"] == 0
        assert pg_repo._session_connection.get().info.transaction_status == TransactionStatus.IDLE
        pg_repo.enqueue("good", {"type": "telegram", "text": "/help"})
    with pg_repo.connection() as conn:
        assert conn.execute("SELECT status FROM jobs WHERE id='good'").fetchone()["status"] == "pending"


@pytest.mark.postgres
def test_request_connections_do_not_leak_across_threads_or_tenant_scopes(pg_repo):
    barrier = Barrier(2)

    def operation(index):
        with pg_repo.session():
            with pg_repo.connection() as conn:
                pid = conn.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
            barrier.wait(timeout=5)
            with pg_repo.for_learner(f"synthetic_{index}").connection() as conn:
                assert conn.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"] == pid
            return pid

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(operation, range(2)))
    assert len(set(ids)) == 2
    assert pg_repo._session_connection.get() is None


def test_failed_callback_toast_does_not_discard_answer_processing(harness, monkeypatch):
    budgets = []

    def fail_ack(callback_id, budget):
        budgets.append(budget.remaining())
        raise ExternalError("callback_ack_unavailable")

    monkeypatch.setattr(harness.telegram, "acknowledge", fail_ack)
    response = (
        create_app(harness.runtime)
        .test_client()
        .post(
            "/",
            json={
                "update_id": 81002,
                "callback_query": {
                    "id": "expired",
                    "from": {"id": 42},
                    "message": {"chat": {"id": 42, "type": "private"}},
                    "data": "q:stale:stale:A",
                },
            },
            headers={"X-Telegram-Bot-Api-Secret-Token": harness.runtime.config.webhook_secret},
        )
    )
    assert response.status_code == 202
    assert 0 < budgets[0] <= 3
    assert harness.repo.jobs["telegram:81002"]["status"] == "done"
    assert harness.telegram.messages
