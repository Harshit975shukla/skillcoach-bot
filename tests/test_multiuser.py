import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime

import pytest
from conftest import FakeAI, FakePublisher, FakeTelegram
from psycopg import sql
from psycopg.types.json import Jsonb
from test_flows import PROFILE, question_set

from skillcoach.clients import ExternalError
from skillcoach.export import public_export
from skillcoach.models import Profile, Task
from skillcoach.runtime import Runtime
from skillcoach.storage import MembershipChanged, Repository
from skillcoach.timeutil import IST
from skillcoach.web import create_app

pytestmark = pytest.mark.postgres


class Bot:
    def __init__(self, repo, config):
        self.repo = repo
        self.config = replace(config, bot_username="SkillCoachTestBot")
        self.runtime = Runtime(
            self.config,
            repo,
            FakeAI(),
            FakeTelegram(),
            FakePublisher(),
            lambda: datetime(2026, 9, 25, 18, tzinfo=IST),
        )
        self.sequence = 1000

    def input(self, user, text=None, callback=None, *, drain=True, update_id=None):
        self.sequence += 1
        payload = {"type": "telegram", "actor_id": user, "display_name": f"Learner {user}"}
        if callback is None:
            payload["text"] = text
        else:
            payload.update(callback=callback, callback_id="fake")
        outcome = self.repo.accept_update(update_id or self.sequence, payload, self.config)
        if drain:
            self.runtime.recover(media=False)
        return outcome

    def invite(self):
        self.input(self.config.owner_id, "/invite test")
        message = self.runtime.telegram.messages[-1][0]
        return re.search(r"start=(invite_[A-Za-z0-9_-]{32})", message).group(1)

    def member(self, user):
        with self.repo.connection() as conn:
            return conn.execute("SELECT * FROM learners WHERE telegram_id=%s", (user,)).fetchone()

    def join(self, user, approve=True):
        invite = self.invite()
        assert self.input(user, "/start " + invite) == "pending"
        member = self.member(user)
        if approve:
            self.input(self.config.owner_id, "/approve " + member["id"])
        return self.repo.for_learner(member["id"])

    def save(self, scoped, mutate):
        self.sequence += 1
        key = f"seed:{self.sequence}"
        scoped.enqueue(key, {"type": "telegram", "text": "/help"})
        if not scoped.is_owner:
            key = f"learner:{scoped.learner_id}:{key}"
        token = self.repo.acquire("domain", 60)
        try:
            revision, state = scoped.read()
            mutate(state)
            scoped.finish(key, token, revision, state, [], [])
        finally:
            self.repo.release("domain", token)


@pytest.fixture
def bot(pg_repo, config):
    return Bot(pg_repo, config)


def test_one_use_invitation_requires_owner_approval_and_rejects_replays(bot):
    invitation = bot.invite()
    assert bot.input(101, "/start " + invitation, update_id=5001) == "pending"
    assert bot.input(101, "/start " + invitation, update_id=5001) == "duplicate"
    assert bot.input(102, "/start " + invitation) == "invalid_invite"
    pending = bot.member(101)
    assert pending["status"] == "pending"
    assert bot.input(101, "/ask private prompt") == "pending"
    assert not bot.runtime.ai.calls
    assert bot.member(102) is None
    bot.input(bot.config.owner_id, "/approve " + pending["id"])
    assert bot.member(101)["status"] == "active"
    bot.input(101, "/setup")
    assert bot.repo.for_learner(pending["id"]).read()[1].draft.stage == "resume"
    assert bot.repo.read()[1].draft is None
    with bot.repo.connection() as conn:
        row = conn.execute("SELECT token_hash,status FROM invitations LIMIT 1").fetchone()
        assert row["token_hash"] == hashlib.sha256(invitation.removeprefix("invite_").encode()).hexdigest()
        assert row["status"] == "claimed"
        assert not conn.execute(
            "SELECT payload::text AS p FROM jobs WHERE payload::text LIKE %s", ("%" + invitation + "%",)
        ).fetchall()


def test_concurrent_claims_only_admit_one_pending_learner(bot):
    invitation = bot.invite()

    def claim(index):
        return bot.repo.accept_update(
            6000 + index,
            {
                "type": "telegram",
                "actor_id": 200 + index,
                "text": "/start " + invitation,
                "display_name": "Test candidate",
            },
            bot.config,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, range(2)))
    assert results.count("pending") == 1 and results.count("invalid_invite") == 1
    with bot.repo.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM learners WHERE status='pending'").fetchone()["n"] == 1


def test_expired_cancelled_and_forged_links_cannot_create_access(bot):
    invite = bot.invite()
    with bot.repo.connection() as conn:
        conn.execute("UPDATE invitations SET expires_at=now()-interval '1 second'")
    assert bot.input(101, "/start " + invite) == "invalid_invite"
    invite = bot.invite()
    with bot.repo.connection() as conn:
        ident = conn.execute(
            "SELECT id FROM invitations WHERE status='open' AND expires_at>now()"
        ).fetchone()["id"]
    bot.input(bot.config.owner_id, "/revokeinvite " + ident)
    assert bot.input(101, "/start " + invite) == "invalid_invite"
    assert bot.input(101, "/start invite_" + "x" * 32) == "invalid_invite"
    assert bot.member(101) is None


def test_nonowner_cannot_invite_approve_reject_revoke_or_publish(bot):
    a = bot.join(101)
    b = bot.join(102, approve=False)
    for command in (
        "/invite",
        "/approve " + b.learner_id,
        "/reject " + b.learner_id,
        "/revoke owner",
        "/revoke " + a.learner_id,
        "/members",
        "/requests",
    ):
        assert bot.input(101, command) == "denied"
    assert bot.member(101)["status"] == "active" and bot.member(102)["status"] == "pending"
    bot.input(101, "/publish")
    assert not bot.runtime.publisher.documents
    bot.input(bot.config.owner_id, "/revoke owner")
    assert bot.repo.member()["status"] == "active"


def test_rejection_revocation_and_reinvite_preserve_history_but_cancel_work(bot):
    scoped = bot.join(101, approve=False)
    bot.input(bot.config.owner_id, "/reject " + scoped.learner_id)
    assert bot.member(101)["status"] == "rejected"
    bot.input(bot.config.owner_id, "/approve " + scoped.learner_id)
    assert bot.member(101)["status"] == "rejected"
    invite = bot.invite()
    bot.input(101, "/start " + invite)
    bot.input(bot.config.owner_id, "/approve " + scoped.learner_id)
    bot.input(101, "/nextweek preserve this private preference")
    bot.input(101, "/ask queued answer", drain=False)
    bot.input(bot.config.owner_id, "/revoke " + scoped.learner_id, drain=False)
    before = len(bot.runtime.telegram.chat_messages[101])
    bot.runtime.recover(media=False)
    assert not bot.runtime.ai.calls
    received = bot.runtime.telegram.chat_messages[101][before:]
    assert len(received) == 1 and "revoked" in received[0][0]
    assert scoped.read()[1].preference == "preserve this private preference"
    bot.input(101, "/retry")
    with bot.repo.connection() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM jobs WHERE learner_id=%s AND "
                "status IN ('pending','running','failed')",
                (scoped.learner_id,),
            ).fetchone()["n"]
            == 0
        )


def test_revocation_during_ai_prevents_commit_and_later_reactivation_replay(bot):
    scoped = bot.join(101)
    bot.input(101, "/ask something", drain=False)

    class RevokingAI:
        def structured(self, prompt, model, budget, validate=None):
            bot.input(bot.config.owner_id, "/revoke " + scoped.learner_id, drain=False)
            return model(text="MUST NOT REACH REVOKED LEARNER")

    bot.runtime.ai = RevokingAI()
    bot.runtime.recover(media=False)
    assert bot.member(101)["status"] == "revoked"
    assert not any("MUST NOT" in text for text, _ in bot.runtime.telegram.chat_messages[101])
    invitation = bot.invite()
    bot.input(101, "/start " + invitation)
    bot.input(bot.config.owner_id, "/approve " + scoped.learner_id)
    bot.input(101, "/retry")
    assert not any("MUST NOT" in text for text, _ in bot.runtime.telegram.chat_messages[101])


def test_stale_work_generation_fails_even_after_member_is_reapproved(bot):
    scoped = bot.join(101)
    scoped.enqueue("waiting", {"type": "telegram", "text": "/help"})
    token = bot.repo.acquire("domain", 60)
    job = bot.repo.next_job(token)
    revision, state = scoped.read()
    bot.input(bot.config.owner_id, "/revoke " + scoped.learner_id, drain=False)
    with pytest.raises(MembershipChanged):
        scoped.finish(job["id"], token, revision, state, [], [])
    bot.repo.release("domain", token)


def test_profiles_drafts_cache_answers_and_recipients_are_isolated(bot):
    a, b = bot.join(101), bot.join(102)
    for scoped, marker in ((a, "SECRET-A"), (b, "SECRET-B")):

        def initialize(state, marker=marker):
            state.profile = Profile(**{**PROFILE, "name": marker, "resume_text": marker})
            state.lessons["today"] = {"topic": "IAM", "date": "2026-09-25"}

        bot.save(scoped, initialize)
    bot.runtime.ai.responses.extend([question_set(5), question_set(5)])
    for scoped in (a, b):
        scoped.enqueue("same-quiz-key", {"type": "schedule", "kind": "quiz", "date": "2026-09-25"})
    bot.runtime.recover(media=False)
    target_a, target_b = a.read()[1].target(), b.read()[1].target()
    assert target_a["session"] != target_b["session"]
    bot.input(102, callback=f"q:{target_a['session']}:{target_a['question']}:B")
    assert not b.read()[1].assessments[target_b["session"]].answers
    bot.input(101, "/q B")
    assert len(a.read()[1].assessments[target_a["session"]].answers) == 1
    assert not b.read()[1].assessments[target_b["session"]].answers
    assert a.read()[1].profile.name == "SECRET-A" and b.read()[1].profile.name == "SECRET-B"
    a_job = f"learner:{a.learner_id}:same-quiz-key"
    assert a.cached(a_job, "assessment") is not None
    assert b.cached(a_job, "assessment") is None
    bot.input(101, "/cancel")
    bot.input(101, "/setup")
    bot.input(102, "/cancel")
    assert a.read()[1].draft is not None and b.read()[1].draft is None
    bot.input(102, "private free-text for wrong flow")
    assert a.read()[1].draft.resume_text == ""
    bot.input(101, "/profile")
    bot.input(102, "/profile")
    assert "SECRET-B" not in "\n".join(t for t, _ in bot.runtime.telegram.chat_messages[101])
    assert "SECRET-A" not in "\n".join(t for t, _ in bot.runtime.telegram.chat_messages[102])
    assert "SECRET-" not in "\n".join(t for t, _ in bot.runtime.telegram.messages)


def test_same_task_origin_completion_and_statistics_are_scoped(bot):
    a, b = bot.join(101), bot.join(102)

    def task(state):
        state.tasks["same"] = Task(
            id="same",
            origin="same-origin",
            title="Practice",
            skill="IAM",
            detail="",
            assigned_date=date(2026, 9, 25),
        )

    bot.save(a, task)
    bot.save(b, task)
    bot.input(101, "/complete same 19")
    assert a.read()[1].tasks["same"].status == "done"
    assert b.read()[1].tasks["same"].status == "pending"
    assert b.read()[1].activity == []
    with bot.repo.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM task_keys WHERE id='same'").fetchone()["n"] == 2
    exported = public_export(bot.repo.read()[1], datetime(2026, 9, 25, tzinfo=IST))
    assert exported["stats"]["total"] == 0 and not exported["open_tasks"]


def test_pause_cancel_and_retry_do_not_touch_another_learner(bot):
    a, b = bot.join(101), bot.join(102)
    bot.runtime.ai.responses.extend([ExternalError("failed-A"), ExternalError("failed-B")])
    bot.input(101, "/ask A")
    bot.input(102, "/ask B")
    bot.input(101, "/cancel")
    with bot.repo.connection() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM jobs WHERE learner_id=%s AND status='failed'", (b.learner_id,)
            ).fetchone()["n"]
            == 1
        )
    bot.input(101, "/pause")
    assert a.read()[1].paused and not b.read()[1].paused
    bot.input(101, "/retry")
    with bot.repo.connection() as conn:
        assert (
            conn.execute(
                "SELECT status FROM jobs WHERE learner_id=%s AND payload->>'text'='/ask B'", (b.learner_id,)
            ).fetchone()["status"]
            == "failed"
        )


def test_schedule_fanout_is_per_learner_and_suppresses_paused_or_revoked(bot):
    from skillcoach.cli import schedule

    a, b, c = bot.join(101), bot.join(102), bot.join(103)
    bot.input(102, "/pause")
    bot.input(bot.config.owner_id, "/revoke " + c.learner_id)
    schedule(bot.runtime, "lesson", date(2026, 9, 25), media=False)
    schedule(bot.runtime, "lesson", date(2026, 9, 25), media=False)
    with bot.repo.connection() as conn:
        rows = conn.execute(
            "SELECT learner_id,count(*) AS n FROM jobs WHERE payload->>'type'='schedule' GROUP BY learner_id"
        ).fetchall()
        assert {r["learner_id"]: r["n"] for r in rows} == {"owner": 1, a.learner_id: 1}
    assert b.read()[1].paused


def test_active_member_and_per_learner_ai_limits(bot):
    bot.config = replace(bot.config, max_learners=2, daily_ai_operations=1)
    bot.runtime.config = bot.config
    a = bot.join(101)
    b = bot.join(102)
    assert bot.member(102)["status"] == "pending"
    bot.runtime.ai.responses.extend([{"text": "A first answer"}, {"text": "Owner answer"}])
    bot.input(101, "/ask first")
    bot.input(101, "/ask second")
    bot.input(bot.config.owner_id, "/ask owner")
    assert len(bot.runtime.ai.calls) == 2
    with bot.repo.connection() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM ai_usage WHERE learner_id=%s", (a.learner_id,)
            ).fetchone()["n"]
            == 1
        )
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM ai_usage WHERE learner_id=%s", (b.learner_id,)
            ).fetchone()["n"]
            == 0
        )


def test_webhook_sender_identity_not_display_name_authorizes_admin(bot):
    client = create_app(bot.runtime).test_client()
    headers = {"X-Telegram-Bot-Api-Secret-Token": bot.config.webhook_secret}
    response = client.post(
        "/",
        json={
            "update_id": 90001,
            "message": {
                "from": {"id": 999, "first_name": "Owner"},
                "chat": {"id": 999, "type": "private"},
                "text": "/invite",
            },
        },
        headers=headers,
    )
    assert response.status_code == 202
    with bot.repo.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM invitations").fetchone()["n"] == 0
    response = client.post(
        "/",
        json={
            "update_id": 90002,
            "message": {
                "from": {"id": bot.config.owner_id},
                "chat": {"id": 999, "type": "private"},
                "text": "/invite",
            },
        },
        headers=headers,
    )
    assert response.status_code == 403


def test_version_two_migration_preserves_exact_owner_state_and_receipts(pg_repo):
    from pathlib import Path

    legacy_schema = "legacy_test_" + pg_repo.schema[-20:]
    repo = Repository(pg_repo.url, schema=legacy_schema)
    original = {
        "profile": {**PROFILE, "resume_text": "OWNER PRIVATE"},
        "paused": True,
        "media": "static",
        "preference": "Preserve all existing intent",
    }
    try:
        with repo.connection() as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(legacy_schema)))
            conn.execute((Path("skillcoach") / "migrations" / "001_private_state.sql").read_text())
            conn.execute(
                "UPDATE coach_state SET body=%s,revision=17,displayed_target=%s WHERE id=1",
                (Jsonb(original), Jsonb({"kind": "draft", "session": "original"})),
            )
            conn.execute("INSERT INTO jobs(id,payload) VALUES ('legacy-update','{}')")
            conn.execute("INSERT INTO outbox(id,job_id,body) VALUES ('legacy-out','legacy-update','{}')")
        repo.migrate()
        with repo.connection() as conn:
            row = conn.execute("SELECT * FROM coach_state WHERE id=1").fetchone()
            assert row["body"] == original and row["revision"] == 17
            assert row["displayed_target"] == {"kind": "draft", "session": "original"}
            assert row["learner_id"] == "owner"
            assert (
                conn.execute("SELECT learner_id FROM jobs WHERE id='legacy-update'").fetchone()["learner_id"]
                == "owner"
            )
            assert (
                conn.execute("SELECT learner_id FROM outbox WHERE id='legacy-out'").fetchone()["learner_id"]
                == "owner"
            )
    finally:
        with pg_repo.connection() as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(legacy_schema)))
