"""Both mode (DELIVERY_CHANNEL=both): the web inbox stays the complete record and Telegram gets copies.

Synthetic people, a fake Telegram and a fake mailbox only: nothing here contacts Telegram, a mail server
or any bot. A distinct numeric bot ID stands for "a bot other than the one whose updates are already
recorded"; no real token is used.
"""

import secrets
import threading
import time
from dataclasses import replace

import pytest
from psycopg.types.json import Jsonb
from test_flows import question_set
from test_quiz_catchup import delivered
from test_web_channel import ORIGIN, build_web
from test_web_dashboard import browser, private

from skillcoach import telegram_copies, web_media
from skillcoach.clients import Budget, ExternalError, telegram_category
from skillcoach.config import Config, ConfigurationError
from skillcoach.storyboard import reviewed_architecture
from skillcoach.timeutil import IST

NEW_BOT = 7000000001
NEW_TOKEN = f"{NEW_BOT}:" + "A" * 35
LEGACY_BOT = 8720643811
OWNER = 42


def tg_error(status, category="", *, retryable=False):
    return ExternalError(f"http_{status}", retryable=retryable, detail=f"telegram={category}" if category else "")


class FakeBot:
    """Records what each Telegram chat would receive; `failures[chat]` lists errors to raise in order,
    `fail_when(chat, text, buttons)` may return an error for one particular send, and `before_send` runs
    during each attempt (the moment the network call would be in flight)."""

    def __init__(self, owner):
        self.owner, self.sent, self.failures, self.uploads, self.calls, self.acks = owner, [], {}, 0, 0, []
        self.before_send = self.fail_when = None

    def for_chat(self, chat):
        return FakeChat(self, chat)

    def send(self, *args, **kwargs):
        return FakeChat(self, self.owner).send(*args, **kwargs)

    def call(self, *args, **kwargs):
        return FakeChat(self, self.owner).call(*args, **kwargs)

    def acknowledge(self, callback, budget):
        self.acks.append(callback)

    def to(self, chat):
        return [entry for entry in self.sent if entry["chat"] == chat]


class FakeChat:
    def __init__(self, bot, chat):
        self.bot, self.chat = bot, chat

    def _attempt(self, text=None, buttons=None):
        self.bot.calls += 1
        if self.bot.before_send:
            self.bot.before_send()
        failure = self.bot.fail_when and self.bot.fail_when(self.chat, text, buttons)
        if failure:
            raise failure
        pending = self.bot.failures.get(self.chat) or []
        if pending:
            raise pending.pop(0)

    def send(self, text, budget, buttons=None, *, parse_mode=None, silent=False):
        self._attempt(text, buttons)
        self.bot.sent.append({"chat": self.chat, "kind": "text", "text": text, "buttons": buttons, "silent": silent})

    def call(self, method, budget, *, data=None, files=None):
        self._attempt()
        field = "video" if method == "sendVideo" else "photo"
        data = data or {}
        if files:
            self.bot.uploads += 1
            file_id, size = f"file-{self.bot.uploads}", len(files[field][1])
        else:
            file_id, size = data[field], None
        self.bot.sent.append({"chat": self.chat, "kind": field, "caption": data.get("caption", ""),
                              "file_id": file_id, "bytes": size})
        return {"video": {"file_id": file_id}} if field == "video" else {"photo": [{"file_id": file_id}]}


@pytest.fixture
def both(pg_repo, config, monkeypatch):
    web = build_web(pg_repo, config, monkeypatch)
    with pg_repo.connection() as conn:
        conn.execute("UPDATE learners SET email='second@example.test' WHERE id=%s", (web.silent.learner_id,))
    runtime = web.bot.runtime
    runtime.config = replace(runtime.config, delivery_channel="both", telegram_token=NEW_TOKEN,
                             telegram_legacy_bot_id=LEGACY_BOT)
    runtime.telegram = FakeBot(OWNER)
    web.tg, web.owner, web.update_id = runtime.telegram, web.bot.repo.for_learner("owner"), 70000
    return web


def drain(web):
    runtime = web.bot.runtime
    for _ in range(60):
        worked = runtime.process_one(Budget(60))
        while runtime.deliver_one(Budget(60)):
            worked = True
        if not worked:
            return


def message(web, actor, text=None, callback=None, *, update_id=None, run=True):
    """One Telegram update from `actor` to the configured bot."""
    web.update_id += 1
    payload = {"type": "telegram", "actor_id": actor, "display_name": f"Person {actor}"}
    if callback is None:
        payload["text"] = text
    else:
        payload.update(callback=callback, callback_id="fake")
    outcome = web.bot.repo.accept_update(update_id or web.update_id, payload, web.bot.runtime.config)
    if run:
        drain(web)
    return outcome


def note(web, *scopes):
    """A mentor note (one inbox message plus one email reminder) for each learner."""
    for scoped in scopes:
        scoped.enqueue("admin:note:" + secrets.token_hex(4), {"type": "encouragement", "message": "goal"})
    drain(web)


def rows(web, sql, *args):
    with web.bot.repo.connection() as conn:
        return conn.execute(sql, args).fetchall()


def copies(web, learner=None):
    return rows(web, "SELECT * FROM outbox WHERE body->>'kind'='telegram' AND (%s::text IS NULL OR learner_id=%s) "
                "ORDER BY sequence", learner, learner)


def emails(web, learner):
    return rows(web, "SELECT * FROM outbox WHERE body->>'kind'='email' AND learner_id=%s ORDER BY sequence", learner)


def pauses(web):
    return rows(web, "SELECT learner_id, code, state, cleared_by FROM telegram_pauses ORDER BY id")


def retry_now(web, key):
    with web.bot.repo.connection() as conn:
        conn.execute("UPDATE outbox SET available_at=now() WHERE id=%s", (key,))
    drain(web)


def event(web, scoped, parts=2):
    """One coaching event of several messages and its held email reminder (as a scheduled lesson)."""
    job = "event:" + secrets.token_hex(4)
    with web.bot.repo.connection() as conn:
        generation = conn.execute("SELECT generation FROM learners WHERE id=%s", (scoped.learner_id,)).fetchone()
        conn.execute("INSERT INTO jobs(id,payload,status,learner_id,access_generation) VALUES "
                     "(%s,'{\"type\":\"schedule\",\"kind\":\"lesson\"}','done',%s,%s)",
                     (job, scoped.learner_id, generation["generation"]))
        bodies = [{"kind": "text", "text": f"Part {index + 1}"} for index in range(parts)]
        bodies.append({"kind": "email", "subject": "Today's SkillCoach lesson is ready", "text": "Open SkillCoach",
                       "hold_for_telegram": True})
        for index, body in enumerate(bodies):
            conn.execute("INSERT INTO outbox(id,job_id,body,learner_id,access_generation) VALUES (%s,%s,%s,%s,%s)",
                         (f"{job}:{index}", job, Jsonb(body), scoped.learner_id, generation["generation"]))
    drain(web)
    return job


def event_email(web, job):
    return rows(web, "SELECT status, error_code FROM outbox WHERE job_id=%s AND body->>'kind'='email'", job)[0]


def todays_quiz(web):
    """The learner (Telegram 101) gets today's lesson and starts its five-question quiz through Telegram.
    Today, not a fixed date: the web harness runs on the real clock and a day's quiz closes after its week."""
    day = web.clock.now.astimezone(IST).date().isoformat()
    web.bot.save(web.learner, lambda state: delivered(state, day=day))
    web.bot.runtime.ai.responses.append(question_set(5))
    message(web, 101, f"/quiz {day}")
    state = web.learner.read()[1]
    assert state.active_assessment, "today's quiz did not start"
    return state, state.assessments[state.active_assessment]


# Without a database -------------------------------------------------------------------------------


def test_telegram_errors_map_to_a_fixed_vocabulary_and_only_two_are_bot_wide():
    assert telegram_category("Forbidden: bot was blocked by the user") == "blocked"
    assert telegram_category("Forbidden: user is deactivated") == "deactivated"
    assert telegram_category("Forbidden: bot can't initiate conversation with a user") == "not_started"
    assert telegram_category("Bad Request: chat not found") == "chat_not_found"
    assert telegram_category("Bad Request: PEER_ID_INVALID") == "peer_invalid"
    assert telegram_category("Bad Request: FROZEN_METHOD_INVALID") == "bot_frozen"
    assert telegram_category("Unauthorized") == "credentials_rejected"
    assert telegram_category("Forbidden: something new") == "forbidden"
    assert telegram_category("Bad Request: message is too long") == ""
    assert telegram_copies.GLOBAL_CODES == {"credentials_rejected", "bot_frozen"}
    assert "peer_invalid" in telegram_copies.RECIPIENT_CODES and "forbidden" in telegram_copies.RECIPIENT_CODES
    assert tg_error(403, "blocked").telegram == "blocked" and tg_error(400).telegram == ""


def test_both_mode_is_explicit_about_which_bot_owns_the_recorded_updates(monkeypatch):
    for name, value in {"DATABASE_URL": "postgresql://test-only", "TELEGRAM_BOT_TOKEN": NEW_TOKEN, "OWNER_ID": "42",
                        "DELIVERY_CHANNEL": "both", "WEB_APP_URL": "https://coach.example.test",
                        "OWNER_EMAIL": "owner@example.test", "EMAIL_FROM": "coach@example.test",
                        "SMTP_HOST": "smtp.example.test", "SMTP_USERNAME": "coach@example.test",
                        "SMTP_PASSWORD": "app-password"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("TELEGRAM_LEGACY_BOT_ID", raising=False)
    with pytest.raises(ConfigurationError, match="TELEGRAM_LEGACY_BOT_ID"):
        Config.from_env()
    monkeypatch.setenv("TELEGRAM_LEGACY_BOT_ID", "not-a-number")
    with pytest.raises(ConfigurationError, match="numeric ID"):
        Config.from_env()
    monkeypatch.setenv("TELEGRAM_LEGACY_BOT_ID", str(LEGACY_BOT))
    config = Config.from_env()
    assert config.web_mode and config.telegram_copies and config.telegram_bot_id == NEW_BOT
    assert config.telegram_namespace == NEW_BOT  # a different bot gets its own receipts
    assert replace(config, telegram_legacy_bot_id=NEW_BOT).telegram_namespace == 0  # same bot, new token
    assert replace(config, telegram_legacy_bot_id=0).telegram_namespace == 0
    # A token whose bot identity cannot be read fails closed instead of falling back to namespace 0.
    for broken in ("not-a-token", "0:" + "A" * 35, "123:" + "A" * 35, f"{NEW_BOT}:short"):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", broken)
        with pytest.raises(ConfigurationError, match="well-formed TELEGRAM_BOT_TOKEN"):
            Config.from_env()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", NEW_TOKEN)
    monkeypatch.setenv("DELIVERY_CHANNEL", "web")
    assert not Config.from_env().telegram_copies


def test_a_telegram_request_belongs_to_the_bot_it_came_through():
    assert telegram_copies.source_bot("telegram:5001") == 0
    assert telegram_copies.source_bot("telegram:5001:next") == 0
    assert telegram_copies.source_bot(f"telegram:{NEW_BOT}:5001") == NEW_BOT
    assert telegram_copies.source_bot(f"telegram:{NEW_BOT}:5001:next") == NEW_BOT
    for other in ("schedule:lesson:2026-10-05", "admin:note:ab12", "web:9d1", "learner:u_1:telegram:5", "telegram:x"):
        assert telegram_copies.source_bot(other) is None
    config = replace(Config("postgresql://test-only", NEW_TOKEN, 42, "a" * 32), delivery_channel="both",
                     telegram_legacy_bot_id=LEGACY_BOT)
    assert telegram_copies.telegram_prompt({"bot": NEW_BOT, "target": {"q": 1}}, config) == {"q": 1}
    assert telegram_copies.telegram_prompt({"bot": 0, "target": {"q": 1}}, config) is None
    assert telegram_copies.telegram_prompt({"q": 1}, config) is None  # unversioned: never trusted


def test_workers_and_the_example_configuration_carry_the_recorded_bot():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    worker = (root / ".github" / "workflows" / "coach-job.yml").read_text(encoding="utf-8")
    assert "          TELEGRAM_LEGACY_BOT_ID: ${{ vars.TELEGRAM_LEGACY_BOT_ID }}\n" in worker
    assert "\nTELEGRAM_LEGACY_BOT_ID=\n" in (root / ".env.example").read_text(encoding="utf-8")


# On a real database ---------------------------------------------------------------------------------


@pytest.mark.postgres
def test_copies_go_only_to_people_who_messaged_this_bot_and_email_is_the_backup(both):
    web = both
    note(web, web.owner, web.learner)
    # Nobody has messaged this bot yet: both notes are in the inboxes and both reminders went by email.
    assert not web.tg.sent and not copies(web)
    assert sorted(mail["to"] for mail in web.email.sent) == ["learner@example.test", "owner@example.test"]
    assert message(web, OWNER, "/help") == "queued"
    key = rows(web, "SELECT id FROM jobs WHERE id LIKE 'telegram:%%' ORDER BY created_at DESC LIMIT 1")[0]["id"]
    assert key == f"telegram:{NEW_BOT}:{web.update_id}"
    assert rows(web, "SELECT bot_id FROM telegram_receipts WHERE update_id=%s", web.update_id)[0]["bot_id"] == NEW_BOT
    # The owner's own Telegram request is answered in the inbox and in Telegram.
    assert web.tg.to(OWNER) and copies(web, "owner")[-1]["status"] == "sent"
    sent, web.tg.sent = len(web.email.sent), []
    note(web, web.owner, web.learner)
    assert [entry["chat"] for entry in web.tg.sent] == [OWNER]
    assert [mail["to"] for mail in web.email.sent[sent:]] == ["learner@example.test"]
    reminder = emails(web, "owner")[-1]
    assert (reminder["status"], reminder["error_code"]) == ("suppressed", "telegram_delivered")
    # The inbox is complete either way: every note is in the owner's feed.
    texts = rows(web, "SELECT count(*) AS n FROM outbox WHERE learner_id='owner' AND body->>'kind'='text' "
                 "AND job_id LIKE 'admin:note:%%' AND status='sent' AND delivered_seq IS NOT NULL")
    assert texts[0]["n"] == 2
    # The learner messages the bot; from then on their notes are copied too, and no email is needed.
    message(web, 101, "/help")
    sent, web.tg.sent = len(web.email.sent), []
    note(web, web.learner)
    assert [entry["chat"] for entry in web.tg.sent] == [101] and len(web.email.sent) == sent


@pytest.mark.postgres
def test_the_learners_own_web_requests_are_answered_on_the_web_only(both):
    web = both
    message(web, OWNER, "/help")
    web.tg.sent.clear()
    client, csrf = browser(web, "owner@example.test")
    response = private(client, csrf, "/web/send", {"request_id": "0b0e3a2c-9f2e-4f43-8c55-2c4b1c3f9a10", "text": "/help"})
    assert response.status_code == 202
    drain(web)
    assert not web.tg.sent
    web_job = rows(web, "SELECT id FROM jobs WHERE payload->>'channel'='web' ORDER BY created_at DESC LIMIT 1")[0]["id"]
    assert rows(web, "SELECT count(*) AS n FROM outbox WHERE job_id=%s AND status='sent'", web_job)[0]["n"] > 0
    assert not rows(web, "SELECT 1 FROM outbox WHERE job_id=%s AND body->>'kind'='telegram'", web_job)


@pytest.mark.postgres
def test_the_email_reminder_follows_what_actually_happened_to_the_telegram_copy(both):
    web = both
    message(web, OWNER, "/help")
    base = len(web.email.sent)
    # A copy that fails for good after the note was queued (Telegram healthy then): one email.
    web.tg.failures[OWNER] = [tg_error(400)]
    note(web, web.owner)
    copy = copies(web, "owner")[-1]
    assert (copy["status"], copy["attempts"]) == ("failed", 5)
    assert len(web.email.sent) == base + 1
    drain(web)
    assert len(web.email.sent) == base + 1  # never twice
    # Passing faults: the email waits while the copy may still be accepted...
    web.tg.failures[OWNER] = [tg_error(503, retryable=True), tg_error(503, retryable=True)]
    note(web, web.owner)
    copy, reminder = copies(web, "owner")[-1], emails(web, "owner")[-1]
    assert (copy["status"], copy["attempts"], reminder["status"]) == ("failed", 1, "pending")
    assert len(web.email.sent) == base + 1
    retry_now(web, copy["id"])
    retry_now(web, copy["id"])
    retry_now(web, reminder["id"])
    # ...and is dropped once Telegram accepts it.
    assert copies(web, "owner")[-1]["status"] == "sent"
    assert (emails(web, "owner")[-1]["status"], len(web.email.sent)) == ("suppressed", base + 1)
    # A copy still failing after the waiting time lets the email go anyway.
    web.tg.failures[OWNER] = [tg_error(503, retryable=True)]
    note(web, web.owner)
    with web.bot.repo.connection() as conn:
        conn.execute("UPDATE outbox SET delivered_at=now()-interval '31 minutes' WHERE learner_id='owner' "
                     "AND body->>'kind'='text' AND job_id=%s", (copies(web, "owner")[-1]["job_id"],))
    retry_now(web, emails(web, "owner")[-1]["id"])
    assert len(web.email.sent) == base + 2


@pytest.mark.postgres
def test_recipient_problems_pause_only_that_person_until_they_message_the_bot(both):
    web = both
    for actor in (OWNER, 101, 102):
        message(web, actor, "/help")
    web.tg.sent.clear()
    web.tg.failures[101] = [tg_error(403, "blocked")]
    web.tg.failures[102] = [tg_error(400, "peer_invalid")]
    sent = len(web.email.sent)
    note(web, web.owner, web.learner, web.silent)
    assert [entry["chat"] for entry in web.tg.sent] == [OWNER]
    assert sorted(mail["to"] for mail in web.email.sent[sent:]) == ["learner@example.test", "second@example.test"]
    assert {(p["learner_id"], p["code"], p["state"]) for p in pauses(web)} == {
        (web.learner.learner_id, "blocked", "paused"), (web.silent.learner_id, "peer_invalid", "paused")}
    # Paused people get no Telegram attempts at all; everyone else continues.
    calls = web.tg.calls
    note(web, web.owner, web.learner, web.silent)
    assert web.tg.calls == calls + 1
    # A person's own message ends their pause, and only theirs.
    message(web, 101, "/help")
    assert {p["learner_id"]: p["state"] for p in pauses(web)} == {
        web.learner.learner_id: "cleared", web.silent.learner_id: "paused"}
    web.tg.sent.clear()
    note(web, web.learner, web.silent)
    assert [entry["chat"] for entry in web.tg.sent] == [101]


@pytest.mark.postgres
def test_a_rejected_or_frozen_bot_pauses_every_copy_until_an_operator_and_the_owner_confirm(both):
    web = both
    for actor in (OWNER, 101):
        message(web, actor, "/help")
    web.tg.failures[OWNER] = [tg_error(401)]
    sent = len(web.email.sent)
    note(web, web.owner)
    note(web, web.learner)
    assert [(p["learner_id"], p["code"], p["state"]) for p in pauses(web)] == [(None, "credentials_rejected", "paused")]
    assert sorted(mail["to"] for mail in web.email.sent[sent:]) == ["learner@example.test", "owner@example.test"]
    notice = rows(web, "SELECT body FROM outbox WHERE id LIKE 'telegram-health:%%' AND learner_id='owner'")
    assert len(notice) == 1 and "Telegram rejected the bot's credentials" in notice[0]["body"]["text"]
    assert "why" not in notice[0]["body"]["text"].lower()
    # No Telegram attempt while paused, and one learner's message does not end it.
    calls = web.tg.calls
    note(web, web.owner, web.learner)
    message(web, 101, "/help")
    assert web.tg.calls == calls and pauses(web)[0]["state"] == "paused"
    # Restoration needs the owner's own message to the bot after the pause began...
    config, repo = web.bot.runtime.config, web.bot.repo
    assert telegram_copies.restore(repo, config) == {
        "restored": False, "reason": "owner_message_to_bot_required_after_pause"}
    message(web, OWNER, "/help")
    assert web.tg.calls == calls
    assert telegram_copies.restore(repo, config)["state"] == "probation"
    assert telegram_copies.status(repo, config)["bot"]["state"] == "probation"
    # ...then only the owner gets copies until one is accepted.
    note(web, web.learner)
    assert web.tg.calls == calls
    note(web, web.owner)
    assert web.tg.to(OWNER) and pauses(web)[0]["cleared_by"] == "confirmed"
    web.tg.sent.clear()
    note(web, web.learner)
    assert [entry["chat"] for entry in web.tg.sent] == [101]
    # An explicit frozen-bot error pauses the bot again, under its own code.
    web.tg.failures[OWNER] = [tg_error(400, "bot_frozen")]
    note(web, web.owner)
    assert [(p["code"], p["state"]) for p in pauses(web) if p["learner_id"] is None][-1] == ("bot_frozen", "paused")


@pytest.mark.postgres
def test_late_copies_never_move_a_conversation_back_and_typed_replies_bind_per_channel(both):
    web = both
    message(web, 101, "/help")
    state, session = todays_quiz(web)
    first = rows(web, "SELECT displayed_target, telegram_target FROM coach_state WHERE learner_id=%s",
                 web.learner.learner_id)[0]
    assert first["displayed_target"] == state.target()
    assert first["telegram_target"] == {"bot": NEW_BOT, "target": state.target()}
    question_one = state.target()
    # The learner answers question 1 on the web. Question 2 appears on the web only.
    client, csrf = browser(web, "learner@example.test")
    callback = f"q:{session.id}:{session.question_ids[0]}:B"
    assert private(client, csrf, "/web/send", {"request_id": "6f0f3b1a-2d34-4b8e-9a4b-6a1c9f1d2e01",
                                                 "callback": callback}).status_code == 202
    drain(web)
    targets = rows(web, "SELECT displayed_target, telegram_target FROM coach_state WHERE learner_id=%s",
                   web.learner.learner_id)[0]
    assert targets["displayed_target"] == web.learner.read()[1].target() != question_one
    assert targets["telegram_target"] == {"bot": NEW_BOT, "target": question_one}
    # A typed Telegram reply binds to what Telegram showed (question 1), so it cannot answer question 2.
    message(web, 101, "/q B")
    job = rows(web, "SELECT payload FROM jobs WHERE learner_id=%s AND id LIKE 'telegram:%%' "
               "ORDER BY created_at DESC LIMIT 1", web.learner.learner_id)
    assert job and job[0]["payload"]["target"] == question_one
    assert len(web.learner.read()[1].assessments[session.id].answers) == 1
    # An unsent copy of question 2 whose answer arrives first is skipped, not shown with old buttons.
    second = f"q:{session.id}:{session.question_ids[1]}:B"
    with web.bot.repo.connection() as conn:
        latest = conn.execute(
            "SELECT id FROM outbox WHERE learner_id=%s AND body->>'kind'='text' AND body ? 'target' "
            "ORDER BY sequence DESC LIMIT 1", (web.learner.learner_id,)).fetchone()["id"]
        conn.execute("INSERT INTO outbox(id,job_id,body,learner_id,access_generation) SELECT %s, job_id, %s, "
                     "learner_id, access_generation FROM outbox WHERE id=%s",
                     (latest + ":tg", Jsonb({"kind": "telegram", "copy_of": latest, "bot": NEW_BOT}), latest))
    message(web, 101, callback=second, run=False)
    web.bot.runtime.process_one(Budget(60))
    drain(web)
    skipped = rows(web, "SELECT status, error_code FROM outbox WHERE id=%s", latest + ":tg")[0]
    assert (skipped["status"], skipped["error_code"]) == ("suppressed", "outdated")
    # Simultaneous answers to one question from both channels: exactly one is recorded.
    third = f"q:{session.id}:{session.question_ids[2]}:B"
    barrier, outcomes = threading.Barrier(2), []

    def telegram_answer():
        barrier.wait()
        outcomes.append(message(web, 101, callback=third, run=False))

    def web_answer():
        barrier.wait()
        outcomes.append(private(client, csrf, "/web/send", {"request_id": "1c5a7b52-3f0d-4d8a-8b6e-0f6c2d9e4a11",
                                                            "callback": third}).status_code)

    threads = [threading.Thread(target=telegram_answer), threading.Thread(target=web_answer)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    drain(web)
    answers = web.learner.read()[1].assessments[session.id].answers
    assert len(answers) == 3 and len(outcomes) == 2


@pytest.mark.postgres
def test_receipts_and_file_ids_belong_to_one_bot(both):
    web = both
    runtime = web.bot.runtime
    # An update ID the earlier bot already used is a new update for a different bot...
    with web.bot.repo.connection() as conn:
        conn.execute("INSERT INTO telegram_receipts(bot_id,update_id,learner_id,disposition) "
                     "VALUES (0, 424242, 'owner', 'queued')")
    assert message(web, OWNER, "/help", update_id=424242) == "queued"
    assert message(web, OWNER, "/help", update_id=424242) == "duplicate"
    # ...while a regenerated token for the earlier bot keeps deduplicating against its records.
    runtime.config = replace(runtime.config, telegram_legacy_bot_id=NEW_BOT)
    assert runtime.config.telegram_namespace == 0
    assert message(web, OWNER, "/help", update_id=424242) == "duplicate"
    receipts = rows(web, "SELECT bot_id FROM telegram_receipts WHERE update_id=424242 ORDER BY bot_id")
    assert [row["bot_id"] for row in receipts] == [0, NEW_BOT]
    # A person counts as started per bot: messaging one bot authorizes no copies from another.
    starts = rows(web, "SELECT bot_id FROM telegram_starts WHERE learner_id='owner' ORDER BY bot_id")
    assert [row["bot_id"] for row in starts] == [0, NEW_BOT]


@pytest.mark.postgres
def test_media_copies_upload_the_stored_video_or_say_honestly_why_not(both, monkeypatch):
    web = both
    story = reviewed_architecture("EC2").model_dump()

    def render(body, folder, budget):
        return [{"role": "video", "mime": "video/mp4", "data": secrets.token_bytes(600_000),
                 "details": {"duration": 30.0, "width": 1280, "height": 720, "voice": bool(body.get("voice"))}},
                {"role": "poster", "mime": "image/png", "data": secrets.token_bytes(20_000), "details": {}}]

    monkeypatch.setattr(web_media, "render", render)
    for actor in (OWNER, 101):
        message(web, actor, "/help")
    web.tg.sent.clear()

    def lesson(scoped, **extra):
        job = "lesson:" + secrets.token_hex(4)
        with web.bot.repo.connection() as conn:
            generation = conn.execute("SELECT generation FROM learners WHERE id=%s", (scoped.learner_id,)).fetchone()
            conn.execute("INSERT INTO jobs(id,payload,status,learner_id,access_generation) VALUES "
                         "(%s,'{\"type\":\"test\"}','done',%s,%s)", (job, scoped.learner_id, generation["generation"]))
            body = {"kind": "media", "mode": "video", "caption": "Walkthrough", "storyboard": story,
                    "shared_reviewed": True, **extra}
            conn.execute("INSERT INTO outbox(id,job_id,body,learner_id,access_generation) VALUES (%s,%s,%s,%s,%s)",
                         (job + ":0", job, Jsonb(body), scoped.learner_id, generation["generation"]))
        while web.bot.runtime.deliver_one(Budget(200), media=True):
            pass
        return job + ":0"

    lesson(web.owner)
    lesson(web.learner)
    videos = [entry for entry in web.tg.sent if entry["kind"] == "video"]
    # The stored file is uploaded once; the shared asset's Telegram file ID is reused for the learner.
    assert [(entry["chat"], entry["bytes"]) for entry in videos] == [(OWNER, 600_000), (101, None)]
    assert videos[1]["file_id"] == videos[0]["file_id"] and web.tg.uploads == 1
    assert "Reviewed authored explanation." in videos[0]["caption"]
    # A video no longer kept, one not made, and a narrated one with narration now off: honest notes.
    with web.bot.repo.connection() as conn:
        conn.execute("DELETE FROM web_media")
        conn.execute("DELETE FROM media_assets WHERE asset_key LIKE 'copy:%%'")
    web.tg.sent.clear()
    kept = lesson(web.owner, caption="Second")
    assert web.tg.to(OWNER)[-1]["kind"] == "video"  # rendered and stored again for a new message
    with web.bot.repo.connection() as conn:
        conn.execute("DELETE FROM web_media")
        conn.execute("UPDATE outbox SET status='pending', attempts=0, available_at=now() WHERE id=%s", (kept + ":tg",))
    drain(web)
    assert web.tg.to(OWNER)[-1]["text"] == telegram_copies.NOT_KEPT
    monkeypatch.setattr(web_media, "render", lambda body, folder, budget: (_ for _ in ()).throw(
        ExternalError("scene_caption_does_not_fit", retryable=False)))
    lesson(web.owner, caption="Third", storyboard={**story, "title": "Not made"})
    assert "Video unavailable" in web.tg.to(OWNER)[-1]["text"]
    monkeypatch.setattr(web_media, "render", render)
    web.bot.runtime.config = replace(web.bot.runtime.config, narration_enabled=True)
    with web.bot.repo.connection() as conn:
        conn.execute("UPDATE coach_state SET body=jsonb_set(body,'{voice}','true') WHERE learner_id='owner'")
    voiced = lesson(web.owner, caption="Fourth", voice=True, storyboard={**story, "title": "Narrated"})
    assert web.tg.to(OWNER)[-1]["kind"] == "video"
    with web.bot.repo.connection() as conn:
        conn.execute("UPDATE coach_state SET body=jsonb_set(body,'{voice}','false') WHERE learner_id='owner'")
        conn.execute("UPDATE outbox SET status='pending', attempts=0, available_at=now() WHERE id=%s", (voiced + ":tg",))
    drain(web)
    assert web.tg.to(OWNER)[-1]["text"] == telegram_copies.NARRATED


@pytest.mark.postgres
def test_copy_failures_are_current_failures_and_paused_copies_are_not(both):
    web = both
    message(web, OWNER, "/help")
    repo = web.bot.runtime.repo
    web.tg.failures[OWNER] = [tg_error(503, retryable=True)]
    note(web, web.owner)
    assert repo.failure_counts(web_mode=True, all_learners=True)["deliveries"] == 1
    web.tg.failures[OWNER] = [tg_error(401)]
    retry_now(web, copies(web, "owner")[-1]["id"])
    assert repo.failure_counts(web_mode=True, all_learners=True)["deliveries"] == 0
    assert copies(web, "owner")[-1]["error_code"] == "telegram_paused"
    status = telegram_copies.status(repo, web.bot.runtime.config)
    assert status["bot"]["state"] == "paused" and web.learner.learner_id not in str(status)


@pytest.mark.postgres
def test_web_mode_makes_no_copies(both):
    web = both
    message(web, OWNER, "/help")
    before = len(copies(web, "owner"))
    web.bot.runtime.config = replace(web.bot.runtime.config, delivery_channel="web")
    web.tg.sent.clear()
    note(web, web.owner)
    assert not web.tg.sent and len(copies(web, "owner")) == before


@pytest.mark.postgres
def test_feed_never_shows_copies(both):
    web = both
    message(web, OWNER, "/help")
    client, csrf = browser(web, "owner@example.test")
    feed = private(client, csrf, "/web/feed").json["messages"]
    assert feed and all(item["kind"] in ("text", "media") for item in feed)
    assert client.get("/web/session", base_url=ORIGIN).status_code == 200


def fail_attempt(web, number, error):
    """Make the `number`-th Telegram attempt from now fail with `error` (earlier ones succeed)."""
    counter = {"n": 0}

    def before_send():
        counter["n"] += 1
        if counter["n"] == number:
            web.tg.failures.setdefault(OWNER, []).append(error)

    web.tg.before_send = before_send


def media_lesson(web, scoped, title, **extra):
    """A lesson video for `scoped`, delivered by a media worker together with its Telegram copy."""
    job = "lesson:" + secrets.token_hex(4)
    with web.bot.repo.connection() as conn:
        generation = conn.execute("SELECT generation FROM learners WHERE id=%s", (scoped.learner_id,)).fetchone()
        conn.execute("INSERT INTO jobs(id,payload,status,learner_id,access_generation) VALUES "
                     "(%s,'{\"type\":\"test\"}','done',%s,%s)", (job, scoped.learner_id, generation["generation"]))
        body = {"kind": "media", "mode": "video", "caption": title, "shared_reviewed": True,
                "storyboard": {**reviewed_architecture("EC2").model_dump(), "title": title}, **extra}
        conn.execute("INSERT INTO outbox(id,job_id,body,learner_id,access_generation) VALUES (%s,%s,%s,%s,%s)",
                     (job + ":0", job, Jsonb(body), scoped.learner_id, generation["generation"]))
    while web.bot.runtime.deliver_one(Budget(200), media=True):
        pass
    return rows(web, "SELECT status, error_code FROM outbox WHERE id=%s", job + ":0:tg")


def fake_render(body, folder, budget):
    return [{"role": "video", "mime": "video/mp4", "data": secrets.token_bytes(300_000),
             "details": {"duration": 20.0, "width": 1280, "height": 720, "voice": bool(body.get("voice"))}},
            {"role": "poster", "mime": "image/png", "data": secrets.token_bytes(20_000), "details": {}}]


def while_reading(monkeypatch, change):
    """Run `change` right after the copy has read the stored video, i.e. after its earlier checks."""
    original = web_media.read_all

    def read_all(repo, media_id):
        stored = original(repo, media_id)
        change()
        return stored

    monkeypatch.setattr(web_media, "read_all", read_all)
    return lambda: monkeypatch.setattr(web_media, "read_all", original)


@pytest.mark.postgres
def test_one_accepted_part_is_not_delivery_of_the_whole_event(both):
    web = both
    message(web, OWNER, "/help")
    base = len(web.email.sent)
    # Every part accepted by Telegram: no email.
    job = event(web, web.owner, parts=3)
    assert event_email(web, job) == {"status": "suppressed", "error_code": "telegram_delivered"}
    assert len(web.email.sent) == base
    # The first part accepted, the next one refused for this person: the event's one email goes out.
    fail_attempt(web, 2, tg_error(403, "blocked"))
    job = event(web, web.owner, parts=2)
    web.tg.before_send = None
    assert [copy["status"] for copy in copies(web, "owner")[-2:]] == ["sent", "suppressed"]
    assert event_email(web, job)["status"] == "sent" and len(web.email.sent) == base + 1
    message(web, OWNER, "/help")  # the owner's own message ends their pause
    # The first part accepted, then the bot's credentials rejected: the email goes out too.
    fail_attempt(web, 2, tg_error(401))
    job = event(web, web.owner, parts=2)
    web.tg.before_send = None
    assert [(p["learner_id"], p["state"]) for p in pauses(web)][-1] == (None, "paused")
    assert event_email(web, job)["status"] == "sent" and len(web.email.sent) == base + 2


@pytest.mark.postgres
def test_a_passing_fault_after_an_accepted_part_waits_then_sends_the_one_email(both):
    web = both
    message(web, OWNER, "/help")
    base = len(web.email.sent)
    fail_attempt(web, 2, tg_error(503, retryable=True))
    job = event(web, web.owner, parts=2)
    web.tg.before_send = None
    first, second = copies(web, "owner")[-2:]
    assert (first["status"], second["status"], second["attempts"]) == ("sent", "failed", 1)
    assert event_email(web, job)["status"] == "pending" and len(web.email.sent) == base
    # The second copy keeps failing until its attempts are spent: then the held email goes out, once.
    with web.bot.repo.connection() as conn:
        conn.execute("UPDATE outbox SET attempts=4 WHERE id=%s", (second["id"],))
    web.tg.failures[OWNER] = [tg_error(503, retryable=True)]
    retry_now(web, second["id"])
    assert rows(web, "SELECT attempts FROM outbox WHERE id=%s", second["id"])[0]["attempts"] == 5
    assert event_email(web, job)["status"] == "sent" and len(web.email.sent) == base + 1
    drain(web)
    assert len(web.email.sent) == base + 1


@pytest.mark.postgres
def test_copies_replies_and_prompts_never_cross_to_another_bot(both):
    web = both
    runtime = web.bot.runtime
    other_bot = 7000000002
    other = replace(runtime.config, telegram_token=f"{other_bot}:" + "B" * 35)
    assert other.telegram_namespace == other_bot
    message(web, 101, "/help")
    # A copy made for this bot is still waiting when another bot is configured and started...
    web.tg.failures[101] = [tg_error(503, retryable=True)]
    note(web, web.learner)
    waiting = copies(web, web.learner.learner_id)[-1]
    assert (waiting["status"], waiting["body"]["bot"]) == ("failed", NEW_BOT)
    runtime.config = other
    message(web, 101, "/help")
    assert copies(web, web.learner.learner_id)[-1]["body"]["bot"] == other_bot
    # ...so it is never sent through the other bot; the inbox keeps the message.
    web.tg.sent.clear()
    retry_now(web, waiting["id"])
    assert rows(web, "SELECT status, error_code FROM outbox WHERE id=%s", waiting["id"])[0] == {
        "status": "suppressed", "error_code": "other_bot"}
    assert not web.tg.sent
    assert rows(web, "SELECT status FROM outbox WHERE id=%s", waiting["body"]["copy_of"])[0]["status"] == "sent"
    # A request that came through the other bot, answered once this bot is configured again, gets its
    # answer in the web inbox only.
    runtime.config = replace(runtime.config, telegram_token=NEW_TOKEN)
    web.update_id += 1
    payload = {"type": "telegram", "actor_id": 101, "display_name": "Person 101", "text": "/help"}
    assert web.bot.repo.accept_update(web.update_id, payload, other) == "queued"
    web.tg.sent.clear()
    drain(web)
    reply = f"telegram:{other_bot}:{web.update_id}"
    assert not web.tg.sent
    assert rows(web, "SELECT count(*) AS n FROM outbox WHERE job_id=%s AND status='sent'", reply)[0]["n"] > 0
    assert not rows(web, "SELECT 1 FROM outbox WHERE job_id=%s AND body->>'kind'='telegram'", reply)
    # A question shown by one bot never binds a reply typed to another bot; one shown by this bot does.
    shown = {"kind": "assessment", "session": "s", "question": "q"}
    for bot, expected in ((other_bot, None), (NEW_BOT, shown)):
        with web.bot.repo.connection() as conn:
            conn.execute("UPDATE coach_state SET telegram_target=%s WHERE learner_id=%s",
                         (Jsonb({"bot": bot, "target": shown}), web.learner.learner_id))
        message(web, 101, "/q B", run=False)
        job = rows(web, "SELECT payload FROM jobs WHERE id=%s", f"telegram:{NEW_BOT}:{web.update_id}")[0]
        assert job["payload"]["target"] == expected


@pytest.mark.postgres
def test_every_media_send_uses_the_newest_narration_and_health(both, monkeypatch):
    web = both
    runtime = web.bot.runtime
    runtime.config = replace(runtime.config, narration_enabled=True)
    monkeypatch.setattr(web_media, "render", fake_render)
    message(web, OWNER, "/help")

    def voice(on):
        with web.bot.repo.connection() as conn:
            conn.execute("UPDATE coach_state SET body=jsonb_set(body,'{voice}',%s::jsonb) WHERE learner_id='owner'",
                         ("true" if on else "false",))

    def bot_paused():
        with web.bot.repo.connection() as conn:
            conn.execute("INSERT INTO telegram_pauses(bot_id,learner_id,code,state) "
                         "VALUES (%s,NULL,'bot_frozen','paused')", (NEW_BOT,))

    # Narration turned off after the copy's first check: only the honest note goes, nothing is cached.
    voice(True)
    restore = while_reading(monkeypatch, lambda: voice(False))
    web.tg.sent.clear()
    copy = media_lesson(web, web.owner, "Narrated", voice=True)
    restore()
    assert copy == [{"status": "sent", "error_code": None}]
    assert [(entry["kind"], entry.get("text")) for entry in web.tg.sent] == [("text", telegram_copies.NARRATED)]
    assert not rows(web, "SELECT 1 FROM media_assets WHERE asset_key LIKE 'copy:%%'")
    # The bot paused after the copy's first check: nothing is sent and nothing cached.
    restore = while_reading(monkeypatch, bot_paused)
    web.tg.sent.clear()
    copy = media_lesson(web, web.owner, "Paused")
    restore()
    assert copy == [{"status": "suppressed", "error_code": "telegram_paused"}] and not web.tg.sent
    assert not rows(web, "SELECT 1 FROM media_assets WHERE asset_key LIKE 'copy:%%'")


@pytest.mark.postgres
def test_revocation_after_the_copys_first_check_sends_nothing(both, monkeypatch):
    web = both
    monkeypatch.setattr(web_media, "render", fake_render)
    message(web, 101, "/help")

    def revoke():
        with web.bot.repo.connection() as conn:
            conn.execute("UPDATE learners SET generation=generation+1 WHERE id=%s", (web.learner.learner_id,))

    restore = while_reading(monkeypatch, revoke)
    web.tg.sent.clear()
    copy = media_lesson(web, web.learner, "Revoked")
    restore()
    assert copy[0]["status"] == "suppressed" and not web.tg.sent
    assert not rows(web, "SELECT 1 FROM media_assets WHERE asset_key LIKE 'copy:%%'")


def fail_question_once(web, chat):
    """The next Telegram send of a question (a message with answer buttons) to `chat` fails once."""
    armed = [True]

    def fail_when(to, text, buttons):
        callbacks = [str(button.get("callback_data", "")) for row in buttons or [] for button in row]
        if armed[0] and to == chat and any(data.startswith("q:") for data in callbacks):
            armed[0] = False
            return tg_error(503, retryable=True)
        return None

    web.tg.fail_when = fail_when


def question_copy(web, target):
    """The Telegram copy of the inbox message that showed question `target`."""
    found = rows(web, "SELECT c.id, c.status, c.attempts, c.error_code, c.delivered_at, o.body->'target' AS shown "
                 "FROM outbox c JOIN outbox o ON o.id=c.body->>'copy_of' AND o.learner_id=c.learner_id "
                 "WHERE c.body->>'kind'='telegram' AND o.body->'target'=%s", Jsonb(target))
    assert len(found) == 1 and found[0]["shown"] is not None
    return found[0]


def during_send_of(web, learner, statement, *params):
    """While a copy is in flight, a domain transaction takes learner, then coaching state, then changes
    outbox rows with `statement` (what /retry or /cancel does) and commits after a pause."""
    started, locked, errors = [], threading.Event(), []

    def domain():
        try:
            with web.bot.repo.connection() as conn:
                conn.execute("SELECT 1 FROM learners WHERE id=%s FOR UPDATE", (learner,))
                conn.execute("SELECT 1 FROM coach_state WHERE learner_id=%s FOR UPDATE", (learner,))
                locked.set()
                time.sleep(0.8)  # Telegram accepts the copy meanwhile and its worker tries to finish it
                conn.execute(statement, params)
        except Exception as exc:  # noqa: BLE001 - asserted by the caller
            errors.append(exc)

    worker = threading.Thread(target=domain)

    def before_send():
        if not started:
            started.append(True)
            worker.start()
            assert locked.wait(5)

    web.tg.before_send = before_send

    def finished():
        worker.join(10)
        web.tg.before_send = None
        return bool(started) and locked.is_set() and not worker.is_alive() and not errors

    return finished


@pytest.mark.postgres
def test_finishing_a_question_copy_takes_the_domain_locks_first_and_never_deadlocks(both):
    web = both
    learner = web.learner.learner_id
    message(web, 101, "/help")
    fail_question_once(web, 101)
    state, session = todays_quiz(web)
    one = state.target()
    copy = question_copy(web, one)
    assert (copy["status"], copy["attempts"]) == ("failed", 1)
    assert rows(web, "SELECT telegram_target FROM coach_state WHERE learner_id=%s", learner)[0]["telegram_target"] \
        is None

    def shown(question):
        prefix = f"q:{session.id}:{question}:"
        return [entry for entry in web.tg.to(101) if any(
            str(button.get("callback_data", "")).startswith(prefix) for row in entry["buttons"] or [] for button in row)]

    # /retry while the copy of question 1 is in flight. Finishing it updates the copy and then the
    # Telegram prompt in coaching state, so it must wait for the domain's learner and state locks
    # before touching the outbox: in the opposite order the two transactions would deadlock.
    retry = ("UPDATE outbox SET status='pending', attempts=0, available_at=now() WHERE status='failed' "
             "AND learner_id=%s")
    finished = during_send_of(web, learner, retry, learner)
    retry_now(web, copy["id"])
    assert finished()
    after = question_copy(web, one)
    assert (after["status"], after["attempts"]) == ("sent", 1) and after["delivered_at"] is not None
    assert rows(web, "SELECT telegram_target FROM coach_state WHERE learner_id=%s", learner)[0]["telegram_target"] \
        == {"bot": NEW_BOT, "target": one}
    drain(web)
    assert len(shown(session.question_ids[0])) == 1  # sent once, never again
    # Question 2 (answering question 1 in Telegram) is withdrawn by /cancel while its copy is in flight:
    # the withdrawal stands, and Telegram replies stay bound to the last prompt that was recorded.
    fail_question_once(web, 101)
    message(web, 101, callback=f"q:{session.id}:{session.question_ids[0]}:B")
    two = web.learner.read()[1].target()
    assert two not in (None, one)
    copy = question_copy(web, two)
    assert (copy["status"], copy["attempts"]) == ("failed", 1)
    cancel = ("UPDATE outbox SET status='suppressed' WHERE status IN ('failed','pending') AND learner_id=%s "
              "AND (body->>'target' IS NOT NULL OR job_id IN "
              "(SELECT job_id FROM outbox WHERE status='failed' AND learner_id=%s))")
    finished = during_send_of(web, learner, cancel, learner, learner)
    retry_now(web, copy["id"])
    assert finished()
    assert question_copy(web, two)["status"] == "suppressed"
    assert rows(web, "SELECT telegram_target FROM coach_state WHERE learner_id=%s", learner)[0]["telegram_target"] \
        == {"bot": NEW_BOT, "target": one}
    drain(web)
    assert len(shown(session.question_ids[1])) == 1  # the in-flight send only; nothing re-sent


@pytest.mark.postgres
def test_button_taps_are_processed_but_not_acknowledged_through_a_paused_bot(both):
    from skillcoach.web import create_app

    web = both
    runtime = web.bot.runtime
    client = create_app(runtime).test_client()
    for actor in (OWNER, 101):
        message(web, actor, "/help")

    def tap(actor, callback_id):
        web.update_id += 1
        update = {"update_id": web.update_id, "callback_query": {
            "id": callback_id, "data": "home:today", "from": {"id": actor, "is_bot": False, "first_name": "P"},
            "message": {"message_id": 1, "chat": {"id": actor, "type": "private"}}}}
        response = client.post("/api/webhook", json=update,
                               headers={"X-Telegram-Bot-Api-Secret-Token": runtime.config.webhook_secret})
        assert response.status_code == 202, response.get_json()
        assert rows(web, "SELECT 1 FROM jobs WHERE id=%s", f"telegram:{NEW_BOT}:{web.update_id}")

    tap(OWNER, "cb-healthy")
    assert web.tg.acks == ["cb-healthy"]
    with web.bot.repo.connection() as conn:
        conn.execute("INSERT INTO telegram_pauses(bot_id,learner_id,code,state) "
                     "VALUES (%s,NULL,'credentials_rejected','paused')", (NEW_BOT,))
    calls = web.tg.calls
    # While the bot is paused the tap is still recorded and processed, but Telegram is not contacted.
    tap(OWNER, "cb-paused")
    assert web.tg.acks == ["cb-healthy"] and web.tg.calls == calls
    # On probation, only the owner's taps are acknowledged.
    with web.bot.repo.connection() as conn:
        conn.execute("UPDATE telegram_pauses SET state='probation' WHERE bot_id=%s AND learner_id IS NULL", (NEW_BOT,))
    tap(101, "cb-learner")
    tap(OWNER, "cb-owner")
    assert web.tg.acks == ["cb-healthy", "cb-owner"]


@pytest.mark.postgres
def test_status_shows_only_the_learners_own_telegram_copies(both):
    web = both
    repo, config = web.bot.repo, web.bot.runtime.config
    # Nobody has messaged this bot yet: copies are off until they do.
    assert telegram_copies.learner_view(repo, config, "owner") == (
        "Telegram copies: off until you send the bot a message. Email reminders go out meanwhile.")
    for actor in (OWNER, 101, 102):
        message(web, actor, "/help")
    on = telegram_copies.learner_view(repo, config, "owner")
    assert on.startswith("Telegram copies: on.")
    assert telegram_copies.learner_view(repo, config, web.learner.learner_id) == on
    web.tg.failures[102] = [tg_error(403, "blocked")]
    note(web, web.silent)
    assert telegram_copies.learner_view(repo, config, web.silent.learner_id).startswith(
        "Telegram copies: paused for you (Telegram reported: blocked).")

    def status(actor):
        message(web, actor, "/status")
        reply = rows(web, "SELECT body FROM outbox WHERE job_id=%s AND body->>'kind'='text' ORDER BY sequence",
                     f"telegram:{NEW_BOT}:{web.update_id}")
        return "\n".join(row["body"]["text"] for row in reply)

    # Someone else's pause is not shown to the learner, nor to the owner in their own /status.
    for actor in (101, OWNER):
        text = status(actor)
        assert text.splitlines()[-1] == on and web.silent.learner_id not in text
    with web.bot.repo.connection() as conn:
        conn.execute("INSERT INTO telegram_pauses(bot_id,learner_id,code,state) "
                     "VALUES (%s,NULL,'bot_frozen','paused')", (NEW_BOT,))
    assert status(101).splitlines()[-1] == (
        "Telegram copies: paused for everyone. Everything continues here and by email reminders.")
    assert telegram_copies.learner_view(repo, replace(config, delivery_channel="web"), "owner") is None
