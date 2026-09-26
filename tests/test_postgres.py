from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

import psycopg
import pytest
from conftest import FakeAI, FakePublisher, FakeTelegram
from test_flows import PROFILE, question_set

from skillcoach.clients import Budget, ExternalError
from skillcoach.migration import import_snapshot
from skillcoach.models import Profile, Task
from skillcoach.runtime import Runtime
from skillcoach.storage import LostLease
from skillcoach.timeutil import IST

pytestmark = pytest.mark.postgres


def run(repo, config):
    return Runtime(
        config, repo, FakeAI(), FakeTelegram(), FakePublisher(), lambda: datetime(2026, 9, 25, 18, tzinfo=IST)
    )


def seed(repo, mutate):
    repo.enqueue("seed", {"type": "telegram", "text": "/help"})
    token = repo.acquire("domain", 60)
    revision, state = repo.read()
    mutate(state)
    repo.finish("seed", token, revision, state, [], [])
    repo.release("domain", token)


def test_real_transaction_rollback_and_unique_answer_constraint(pg_repo):
    repo = pg_repo
    repo.enqueue("one", {"type": "telegram", "text": "/help"})
    token = repo.acquire("domain", 60)
    revision, state = repo.read()
    repo.finish("one", token, revision, state, [], [("session", "question")])
    repo.enqueue("two", {"type": "telegram", "text": "/help"})
    revision, state = repo.read()
    state.paused = True
    with pytest.raises(psycopg.errors.UniqueViolation):
        repo.finish(
            "two",
            token,
            revision,
            state,
            [{"kind": "text", "text": "must rollback"}],
            [("session", "question")],
        )
    assert repo.read()[1].paused is False
    with repo.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM outbox").fetchone()["n"] == 0
        assert conn.execute("SELECT status FROM jobs WHERE id='two'").fetchone()["status"] == "pending"
    repo.release("domain", token)


def test_real_repository_private_schema_and_no_public_usage(pg_repo):
    from skillcoach.storage import Repository

    assert type(pg_repo) is Repository
    with pg_repo.connection() as conn:
        assert conn.execute("SELECT current_schema() AS name").fetchone()["name"] == pg_repo.schema
        assert conn.execute("SHOW statement_timeout").fetchone()["statement_timeout"] == "5s"
        assert conn.execute("SHOW lock_timeout").fetchone()["lock_timeout"] == "3s"
        assert (
            conn.execute(
                "SELECT table_schema FROM information_schema.tables "
                "WHERE table_name='coach_state' AND table_schema=%s",
                (pg_repo.schema,),
            ).fetchone()["table_schema"]
            == pg_repo.schema
        )
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM pg_namespace, "
                "LATERAL aclexplode(coalesce(nspacl, acldefault('n', nspowner))) AS a "
                "WHERE nspname=%s AND a.grantee=0 AND a.privilege_type IN ('USAGE','CREATE')",
                (pg_repo.schema,),
            ).fetchone()["n"]
            == 0
        )


def test_concurrent_unique_receipts_and_worker_leases(pg_repo):
    repo = pg_repo
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(
            executor.map(
                lambda _: repo.enqueue("same-update", {"type": "telegram", "text": "/help"}), range(10)
            )
        )
    assert sum(results) == 1
    with ThreadPoolExecutor(max_workers=5) as executor:
        tokens = list(executor.map(lambda _: repo.acquire("domain", 60), range(5)))
    assert sum(token is not None for token in tokens) == 1
    repo.release("domain", next(token for token in tokens if token))


def test_stale_lease_cannot_commit_and_does_not_release_new_worker(pg_repo):
    repo = pg_repo
    repo.enqueue("job", {"type": "telegram", "text": "/pause"})
    old = repo.acquire("domain", 60)
    revision, state = repo.read()
    with repo.connection() as conn:
        conn.execute("UPDATE worker_leases SET expires_at=now()-interval '1 second' WHERE name='domain'")
    current = repo.acquire("domain", 60)
    with pytest.raises(LostLease):
        repo.finish("job", old, revision, state, [], [])
    repo.release("domain", old)
    assert repo.acquire("domain", 60) is None
    repo.release("domain", current)


def test_concurrent_answers_bound_to_displayed_question(pg_repo, config):
    repo, runtime = pg_repo, run(pg_repo, config)

    def initialize(state):
        state.profile = Profile(**PROFILE)
        state.lessons["today"] = {"topic": "IAM", "date": "2026-09-25"}

    seed(repo, initialize)
    runtime.ai.responses.append(question_set(5))
    repo.enqueue("quiz", {"type": "schedule", "kind": "quiz", "date": "2026-09-25"})
    runtime.recover(media=False)
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(
            executor.map(
                lambda i: repo.enqueue(f"answer:{i}", {"type": "telegram", "text": "/q B"}), range(2)
            )
        )
    runtime.recover(media=False)
    session = next(iter(repo.read()[1].assessments.values()))
    assert len(session.answers) == 1
    with repo.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM answer_keys").fetchone()["n"] == 1


def test_cache_survives_crash_without_repeat_ai(pg_repo, config):
    repo, runtime = pg_repo, run(pg_repo, config)
    repo.enqueue("ask", {"type": "telegram", "text": "/ask AWS"})
    token = repo.acquire("domain", 60)
    repo.next_job(token)
    repo.cache("ask", "ask", {"text": "Persisted answer"}, token)
    repo.release("domain", token)
    runtime.recover(media=False)
    assert not runtime.ai.calls
    assert runtime.telegram.messages[0][0] == "Persisted answer"


def test_delivery_failure_retry_does_not_regrade_or_hide_other_work(pg_repo, config):
    repo, runtime = pg_repo, run(pg_repo, config)
    runtime.ai.responses.extend(
        [
            {"skill": "IAM", "question": "Explain policy evaluation."},
            {
                "score": 7,
                "accuracy": 7,
                "reasoning": 7,
                "communication": 7,
                "feedback": "More detail.",
                "model_answer": "Hypothetical example.",
            },
        ]
    )
    repo.enqueue("interview", {"type": "telegram", "text": "/interview IAM"})
    runtime.recover(media=False)
    runtime.telegram.fail = True
    repo.enqueue("answer", {"type": "telegram", "text": "Actual answer"})
    runtime.recover(media=False)
    assert next(iter(repo.read()[1].interviews.values())).status == "completed"
    runtime.telegram.fail = False
    repo.enqueue("retry", {"type": "telegram", "text": "/retry"})
    runtime.recover(media=False)
    assert len(runtime.ai.calls) == 2
    assert any("Hypothetical model answer" in text for text, _ in runtime.telegram.messages)


def test_publish_failure_notice_bypasses_failed_item_not_success(pg_repo, config):
    repo, runtime = pg_repo, run(pg_repo, config)
    runtime.publisher.fail = True
    repo.enqueue("publish", {"type": "telegram", "text": "/publish"})
    repo.enqueue("help", {"type": "telegram", "text": "/help"})
    runtime.recover(media=False)
    text = "\n".join(message for message, _ in runtime.telegram.messages)
    assert "publication failed" in text and "SkillCoach" in text
    assert "summary published" not in text
    with repo.connection() as conn:
        assert conn.execute("SELECT body->'base' AS b FROM outbox WHERE id='publish:0'").fetchone()["b"] == {
            "sha": "base"
        }


def test_pause_then_unpause_suppresses_pending_scheduled_only(pg_repo, config):
    repo, runtime = pg_repo, run(pg_repo, config)
    repo.enqueue("scheduled", {"type": "schedule", "kind": "lesson", "date": "2026-09-25"})
    runtime.process_one(Budget())
    repo.enqueue("pause", {"type": "telegram", "text": "/pause"})
    repo.enqueue("unpause", {"type": "telegram", "text": "/unpause"})
    runtime.recover(media=False)
    assert repo.read()[1].paused is False
    assert not any("Set up your private" in t for t, _ in runtime.telegram.messages)
    with repo.connection() as conn:
        assert (
            conn.execute("SELECT status FROM outbox WHERE job_id='scheduled'").fetchone()["status"]
            == "suppressed"
        )


def test_repeated_migrations_and_idempotent_legacy_import(pg_repo):
    repo = pg_repo
    repo.migrate()
    raw = {
        "open_tasks": [],
        "completed_tasks": [
            {
                "id": "legacy-1",
                "title": "Practice",
                "assigned_date": "2026-09-24",
                "completed_at": "2026-09-25T10:00:00+05:30",
                "skill": "IAM",
            }
        ],
    }
    repo.enqueue("import:hash", {"type": "import", "snapshot": raw, "digest": "hash"})
    token = repo.acquire("domain", 60)
    revision, state = repo.read()
    state = import_snapshot(state, raw, "hash")
    repo.finish("import:hash", token, revision, state, [], [])
    revision, state = repo.read()
    state = import_snapshot(state, raw, "hash")
    repo.finish("import:hash", token, revision, state, [], [])
    assert len(repo.read()[1].tasks) == 1
    with repo.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM task_keys").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"] == 6
    repo.release("domain", token)


def test_network_calls_do_not_hold_state_or_lease_row_locks(pg_repo, config):
    repo, runtime = pg_repo, run(pg_repo, config)

    class LockCheckingAI:
        def structured(self, prompt, model, budget, validate=None):
            with repo.connection() as conn:
                conn.execute("SELECT id FROM coach_state FOR UPDATE NOWAIT")
                conn.execute("SELECT name FROM worker_leases FOR UPDATE NOWAIT")
            return model(text="No DB locks crossed the provider call")

    runtime.ai = LockCheckingAI()
    repo.enqueue("ask", {"type": "telegram", "text": "/ask locks"})
    runtime.recover(media=False)
    assert runtime.telegram.messages[0][0] == "No DB locks crossed the provider call"


def test_schedule_receipt_and_task_completion_idempotency(pg_repo, config):
    repo, runtime = pg_repo, run(pg_repo, config)

    def initialize(state):
        state.tasks["t"] = Task(
            id="t",
            origin="stable-origin",
            title="Practice",
            skill="IAM",
            detail="",
            assigned_date=date(2026, 9, 25),
        )

    seed(repo, initialize)
    for i in range(2):
        repo.enqueue(f"complete:{i}", {"type": "telegram", "text": "/complete t 10"})
    runtime.recover(media=False)
    state = repo.read()[1]
    assert state.tasks["t"].actual_minutes == 10
    assert state.activity == [date(2026, 9, 25)]
    assert repo.enqueue(
        "schedule:lesson:2026-09-25", {"type": "schedule", "kind": "lesson", "date": "2026-09-25"}
    )
    assert not repo.enqueue(
        "schedule:lesson:2026-09-25", {"type": "schedule", "kind": "lesson", "date": "2026-09-25"}
    )


def test_failed_job_does_not_block_ready_help(pg_repo, config):
    repo, runtime = pg_repo, run(pg_repo, config)
    runtime.ai.responses.append(ExternalError("unavailable"))
    repo.enqueue("bad", {"type": "telegram", "text": "/ask something"})
    repo.enqueue("good", {"type": "telegram", "text": "/help"})
    runtime.recover(media=False)
    assert any("SkillCoach" in text for text, _ in runtime.telegram.messages)
    with repo.connection() as conn:
        assert conn.execute("SELECT status FROM jobs WHERE id='bad'").fetchone()["status"] == "failed"
        assert conn.execute("SELECT status FROM jobs WHERE id='good'").fetchone()["status"] == "done"


def test_cancel_failed_export_suppresses_group_without_false_success(pg_repo, config):
    repo, runtime = pg_repo, run(pg_repo, config)
    runtime.publisher.fail = True
    repo.enqueue("publish", {"type": "telegram", "text": "/publish"})
    runtime.recover(media=False)
    repo.enqueue("cancel", {"type": "telegram", "text": "/cancel"})
    runtime.recover(media=False)
    runtime.publisher.fail = False
    repo.enqueue("retry", {"type": "telegram", "text": "/retry"})
    runtime.recover(media=False)
    assert not runtime.publisher.documents
    assert not any("summary published" in text for text, _ in runtime.telegram.messages)


def test_runtime_role_creation_works_for_managed_non_superuser_admin(pg_repo, monkeypatch):
    from uuid import uuid4

    from psycopg import sql

    from skillcoach import bootstrap

    admin_role = "test_admin_" + uuid4().hex
    runtime_role = "test_runtime_" + uuid4().hex
    monkeypatch.setattr(bootstrap, "ROLE", runtime_role)
    with pg_repo.connection() as conn:
        with conn.transaction(force_rollback=True):
            conn.execute(sql.SQL("CREATE ROLE {} CREATEROLE NOLOGIN").format(sql.Identifier(admin_role)))
            conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(admin_role)))
            bootstrap.ensure_runtime_role(conn, "test-only-runtime-password-not-production")
            role = conn.execute(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls, rolinherit, rolcanlogin "
                "FROM pg_roles WHERE rolname=%s",
                (runtime_role,),
            ).fetchone()
            assert role["rolcanlogin"] is True
            assert not any(
                role[key]
                for key in ("rolsuper", "rolcreatedb", "rolcreaterole", "rolbypassrls", "rolinherit")
            )
