import re
import smtplib
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from conftest import FakeEmail
from psycopg.types.json import Jsonb

from skillcoach import web_channel
from skillcoach.cli import email_test, main
from skillcoach.clients import Budget, ExternalError
from skillcoach.config import Config, ConfigurationError, normalize_email
from skillcoach.email_client import Email
from skillcoach.reengage import ENCOURAGEMENTS
from skillcoach.web import create_app
from skillcoach.web_channel import (
    LOGIN_COOKIE,
    MAX_SENDS_PER_HOUR,
    MAX_UNKNOWN_PER_HOUR,
    WEB_COOKIE,
    feed_item,
    notification,
    pad_response,
    web_button,
    web_payload,
)

ORIGIN = "https://localhost"
WEB_ENV = (
    "DELIVERY_CHANNEL",
    "WEB_APP_URL",
    "OWNER_EMAIL",
    "EMAIL_FROM",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
)


def web_config(config):
    return replace(
        config,
        delivery_channel="web",
        web_app_url="https://coach.example.test",
        owner_email="owner@example.test",
        email_from="SkillCoach <coach@example.test>",
        smtp_host="smtp.example.test",
        smtp_username="coach@example.test",
        smtp_password="app-password",
    )


# Configuration -------------------------------------------------------------------------------


def test_web_mode_is_off_by_default_and_needs_complete_email_settings(monkeypatch):
    for name in WEB_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://test-only")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("OWNER_ID", "42")
    config = Config.from_env()
    assert config.delivery_channel == "telegram" and not config.web_mode and not config.email_configured
    monkeypatch.setenv("DELIVERY_CHANNEL", "web")
    with pytest.raises(ConfigurationError, match="WEB_APP_URL, OWNER_EMAIL, EMAIL_FROM, SMTP_HOST"):
        Config.from_env()
    settings = {
        "WEB_APP_URL": "https://coach.example.test/",
        "OWNER_EMAIL": " Owner@Example.TEST ",
        "EMAIL_FROM": "SkillCoach <coach@example.test>",
        "SMTP_HOST": "smtp.example.test",
        "SMTP_USERNAME": "coach@example.test",
        "SMTP_PASSWORD": "app-password",
    }
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    config = Config.from_env()
    assert config.web_mode and config.email_configured and config.smtp_port == 587
    assert config.owner_email == "owner@example.test" and config.web_app_url == "https://coach.example.test"
    for name, value, message in (
        ("DELIVERY_CHANNEL", "sms", "telegram or web"),
        ("WEB_APP_URL", "http://coach.example.test", "HTTPS origin"),
        ("WEB_APP_URL", "https://coach.example.test/web", "HTTPS origin"),
        ("OWNER_EMAIL", "owner@example", "one email"),
        ("EMAIL_FROM", "SkillCoach <coach@example.test>\nBcc: x@example.test", "single line"),
        ("SMTP_HOST", "smtp.example.test;rm", "host name"),
        ("SMTP_PORT", "25", "587"),
    ):
        monkeypatch.setenv(name, value)
        with pytest.raises(ConfigurationError, match=message):
            Config.from_env()
        monkeypatch.setenv(name, settings.get(name, "587" if name == "SMTP_PORT" else "web"))
    assert normalize_email("A.B+tag@Mail.Example.org") == "a.b+tag@mail.example.org"
    assert normalize_email("two@example.test,three@example.test") is None
    assert normalize_email(None) is None


# SMTP ----------------------------------------------------------------------------------------


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None, context=None):
        if host == "down.example.test":
            raise OSError("connection refused")
        self.host, self.port, self.timeout, self.calls = host, port, timeout, []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.calls.append("quit")

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, username, password):
        self.calls.append(("login", username, password))
        if password == "wrong":
            raise smtplib.SMTPAuthenticationError(535, b"rejected")

    def send_message(self, message):
        self.calls.append(("send", message))
        return {}


def test_email_client_uses_tls_bounded_steps_and_maps_failures(config, monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    monkeypatch.setattr("smtplib.SMTP_SSL", FakeSMTP)
    settings = web_config(config)
    Email(settings).send("Learner@Example.test", "Your code", "Body text", Budget(30))
    client = FakeSMTP.instances[-1]
    assert (client.host, client.port) == ("smtp.example.test", 587) and client.timeout <= 10
    assert client.calls[0] == "starttls" and client.calls[1] == (
        "login",
        "coach@example.test",
        "app-password",
    )
    message = client.calls[2][1]
    assert message["To"] == "learner@example.test" and message["Subject"] == "Your code"
    assert (
        message["From"] == "SkillCoach <coach@example.test>" and message["Auto-Submitted"] == "auto-generated"
    )
    assert client.calls[-1] == "quit"
    Email(replace(settings, smtp_port=465)).send("learner@example.test", "Code", "Body", Budget(30))
    assert FakeSMTP.instances[-1].port == 465 and "starttls" not in FakeSMTP.instances[-1].calls
    for broken, code, retryable in (
        (replace(settings, smtp_password="wrong"), "email_auth_failed", False),
        (replace(settings, smtp_host="down.example.test"), "email_failed", True),
        (replace(settings, smtp_password=""), "email_not_configured", False),
    ):
        with pytest.raises(ExternalError) as failure:
            Email(broken).send("learner@example.test", "Code", "Body", Budget(30))
        assert failure.value.code == code and failure.value.retryable is retryable
    for recipient, subject, code in (
        ("not-an-address", "Code", "email_recipient_invalid"),
        ("learner@example.test", "Code\r\nBcc: x@example.test", "email_subject_invalid"),
    ):
        with pytest.raises(ExternalError, match=code):
            Email(settings).send(recipient, subject, "Body", Budget(30))


# Delivery in web mode ------------------------------------------------------------------------


def test_web_mode_uses_the_inbox_and_sends_one_email_per_mentor_note(harness):
    h = harness
    h.runtime.config = web_config(h.runtime.config)
    h.repo.enqueue("admin:note", {"type": "encouragement", "message": "checkin"})
    h.runtime.recover(media=False)
    rows = [row for row in h.repo.outbox.values() if row["job_id"] == "admin:note"]
    assert [row["body"]["kind"] for row in rows] == ["text", "email"]
    assert all(row["status"] == "sent" for row in rows) and not h.telegram.messages
    assert h.email.sent == [
        {
            "to": "owner@example.test",
            "subject": "A note from your SkillCoach mentor",
            "text": h.email.sent[0]["text"],
        }
    ]
    assert ENCOURAGEMENTS["checkin"] in h.email.sent[0]["text"]
    assert "https://coach.example.test/web" in h.email.sent[0]["text"]
    # The learner's own browser messages are answered in the inbox only: no email, no Telegram.
    h.repo.enqueue(f"web:{uuid4()}", {"type": "telegram", "channel": "web", "text": "/help", "target": None})
    h.runtime.recover(media=False)
    assert len(h.email.sent) == 1 and not h.telegram.messages
    assert all(row["status"] == "sent" for row in h.repo.outbox.values())


def test_web_mode_never_renders_video_and_failed_email_is_recoverable(harness):
    h = harness
    h.runtime.config = web_config(h.runtime.config)
    h.repo.outbox["lesson:0"] = {
        "id": "lesson:0",
        "job_id": "lesson",
        "status": "pending",
        "body": {"kind": "media", "storyboard": {"title": "Not rendered"}, "mode": "video"},
    }
    assert h.runtime.deliver_one(Budget(60), media=False)
    assert h.repo.outbox["lesson:0"]["status"] == "sent" and not h.telegram.messages
    h.email.fail = True
    h.repo.enqueue("admin:second", {"type": "encouragement", "message": "goal"})
    h.runtime.recover(media=False)
    email = next(row for row in h.repo.outbox.values() if row["body"]["kind"] == "email")
    assert email["status"] == "failed" and not h.email.sent
    notice = h.repo.outbox[email["id"] + ":delivery-error"]
    assert notice["status"] == "sent"  # The learner sees the recoverable failure in the inbox.


def telegram_era_failure(h, key="alert:late:quiz:2026-09-30:0"):
    h.repo.outbox[key] = {
        "id": key,
        "job_id": key.rsplit(":", 1)[0],
        "status": "failed",
        "body": {"kind": "text", "text": "Delivery delay"},
    }


def test_web_mode_keeps_telegram_era_failures_as_history_and_still_reports_real_ones(
    harness, monkeypatch, capsys
):
    h = harness
    monkeypatch.setattr("skillcoach.cli.Runtime.from_env", lambda: h.runtime)
    h.runtime.config = web_config(h.runtime.config)
    telegram_era_failure(h)
    assert main(["recover", "--no-media"]) == 0
    printed = capsys.readouterr()
    assert '"telegram_history": 1' in printed.out and "kept as history" in printed.err
    assert "Recoverable failures remain" not in printed.err
    # /retry retries failed emails and work, but never re-sends a stale Telegram-era message.
    h.repo.outbox["note:email"] = {
        "id": "note:email",
        "job_id": "note",
        "status": "failed",
        "body": {"kind": "email", "subject": "A note", "text": "Hi"},
    }
    assert main(["recover", "--no-media"]) == 1
    assert "Recoverable failures remain" in capsys.readouterr().err
    h.repo.enqueue("telegram:retry", {"type": "telegram", "text": "/retry"})
    h.runtime.recover(media=False)
    assert h.repo.outbox["alert:late:quiz:2026-09-30:0"]["status"] == "failed"
    assert h.repo.outbox["note:email"]["status"] == "sent" and h.email.sent[-1]["subject"] == "A note"
    assert "kept as history" in h.repo.outbox["telegram:retry:0"]["body"]["text"]
    assert main(["recover", "--no-media"]) == 0
    # Telegram mode is unchanged: every failed delivery counts and /retry resends it.
    h.runtime.config = replace(h.runtime.config, delivery_channel="telegram")
    assert main(["recover", "--no-media"]) == 1
    h.repo.enqueue("telegram:retry-2", {"type": "telegram", "text": "/retry"})
    h.runtime.recover(media=False)
    assert h.repo.outbox["alert:late:quiz:2026-09-30:0"]["status"] == "sent"


def test_email_rows_without_an_address_are_suppressed_and_telegram_mode_is_unchanged(harness):
    h = harness
    h.repo.outbox["note:0"] = {
        "id": "note:0",
        "job_id": "note",
        "status": "pending",
        "body": {"kind": "email", "subject": "Hello", "text": "Hi"},
    }
    assert h.runtime.deliver_one(Budget(60))
    assert h.repo.outbox["note:0"]["status"] == "suppressed" and not h.email.sent
    h.repo.enqueue("admin:note", {"type": "encouragement", "message": "progress"})
    h.runtime.recover(media=False)
    assert h.telegram.messages[-1][0] == ENCOURAGEMENTS["progress"]
    assert all(
        row["body"]["kind"] != "email" for row in h.repo.outbox.values() if row["job_id"] == "admin:note"
    )


def test_notifications_cover_scheduled_and_mentor_work_only(config):
    settings = web_config(config)
    lesson = {
        "kind": "text",
        "text": "**Today:** IAM roles " + "word " * 400,
        "format": "md",
        "scheduled": True,
        "scheduled_date": "2026-10-01",
    }
    job = {"payload": {"type": "schedule", "kind": "lesson", "date": "2026-10-01"}}
    body = notification(job, [{"kind": "media"}, lesson], settings)
    assert body["kind"] == "email" and body["subject"] == "Today's SkillCoach lesson is ready"
    assert body["text"].startswith("Today: IAM roles") and "**" not in body["text"] and "…" in body["text"]
    assert body["scheduled"] is True and body["scheduled_date"] == "2026-10-01"
    assert body["text"].rstrip().endswith("Replies to this address are not read.")
    quiz = {"payload": {"type": "schedule", "kind": "quiz"}}
    assert (
        notification(quiz, [{"kind": "text", "text": "Q1"}], settings)["subject"]
        == "Your SkillCoach quiz is ready"
    )
    admin = {"payload": {"type": "telegram", "text": "/learn IAM", "requested_by": "owner_admin"}}
    assert (
        notification(admin, [{"kind": "text", "text": "Lesson"}], settings)["subject"]
        == "New from SkillCoach"
    )
    web = {"payload": {"type": "telegram", "channel": "web", "text": "/today"}}
    assert notification(web, [{"kind": "text", "text": "Today"}], settings) is None
    assert notification(job, [lesson], config) is None  # Telegram mode never emails.
    assert notification(job, [], settings) is None


def test_buttons_map_to_safe_web_actions(config):
    settings = web_config(config)
    lesson = "0123456789abcdef0123"
    cases = [
        ({"text": "B", "callback_data": "a:1:B"}, {"kind": "callback", "text": "B", "data": "a:1:B"}),
        (
            {
                "text": "Open lesson page",
                "web_app": {"url": f"https://coach.example.test/app?lesson={lesson}"},
            },
            {"kind": "lesson", "text": "Open lesson page", "lesson": lesson},
        ),
        (
            {"text": "📊 Open my dashboard", "web_app": {"url": "https://coach.example.test/app"}},
            {"kind": "command", "text": "📊 My progress", "command": "/progress"},
        ),
        (
            {"text": "Admin", "web_app": {"url": "https://coach.example.test/admin"}},
            {"kind": "link", "text": "Admin", "url": "/admin"},
        ),
        (
            {"text": "Resume", "url": "https://t.me/SkillCoachTestBot?start=quiz_2026-09-29"},
            {"kind": "command", "text": "Resume", "command": "/start quiz_2026-09-29"},
        ),
        (
            {"text": "Docs", "url": "https://docs.aws.amazon.com/iam/"},
            {"kind": "link", "text": "Docs", "url": "https://docs.aws.amazon.com/iam/"},
        ),
    ]
    for raw, expected in cases:
        assert web_button(raw, settings) == expected
    for raw in (
        {"text": "x", "url": "javascript:alert(1)"},
        {"text": "x", "url": "http://example.test"},
        {"text": "x", "url": "https://user@example.test/"},
        {"text": "x", "callback_data": "x" * 65},
        {"text": "x", "url": "https://t.me/SkillCoachTestBot?start=bad token"},
        "not a button",
    ):
        assert web_button(raw, settings) is None
    row = {
        "delivered_seq": 7,
        "delivered_at": datetime(2026, 10, 1, 3, 30, tzinfo=timezone.utc),
        "body": {
            "kind": "text",
            "text": "**Hi** `code`",
            "format": "md",
            "buttons": [[{"text": "x", "url": "javascript:x"}], [{"text": "A", "callback_data": "a"}], "bad"],
        },
    }
    item = feed_item(row, settings)
    assert item["id"] == 7 and item["blocks"] and "text" not in item
    assert item["buttons"] == [[{"kind": "callback", "text": "A", "data": "a"}]]
    media = feed_item({"delivered_seq": 8, "delivered_at": None, "body": {"kind": "media"}}, settings)
    assert "Open lesson page" in media["text"] and media["buttons"] == []


def test_sign_in_requests_share_a_minimum_duration():
    slept = []
    pad_response(time.monotonic(), 4.0, slept.append)
    assert len(slept) == 1 and 3.5 < slept[0] <= 4.0
    slept.clear()
    pad_response(time.monotonic() - 5, 4.0, slept.append)
    assert slept == []
    assert web_channel.START_FLOOR_SECONDS >= 3


def test_browser_payloads_are_strict():
    request_id = str(uuid4())
    assert web_payload({"request_id": request_id, "text": "/today"}) == {"text": "/today"}
    assert web_payload({"request_id": request_id, "callback": "home:today"}) == {"callback": "home:today"}
    for body in (
        {"request_id": request_id},
        {"request_id": request_id, "text": "a", "callback": "b"},
        {"request_id": "not-a-uuid", "text": "a"},
        {"request_id": request_id, "text": "   "},
        {"request_id": request_id, "text": "x" * 16001},
        {"request_id": request_id, "callback": "é" * 33},
        {"request_id": request_id, "text": "a", "learner_id": "someone"},
    ):
        with pytest.raises(ValueError):
            web_payload(body)


def test_cli_skips_video_tooling_and_tests_email_without_learners(harness, monkeypatch):
    monkeypatch.setenv("DELIVERY_CHANNEL", "web")
    assert main(["needs-media"]) == 3  # Returns before any database connection.
    h = harness
    h.runtime.config = web_config(h.runtime.config)
    assert email_test(h.runtime) == {"sent": True, "to": "OWNER_EMAIL"}
    assert (
        h.email.sent[0]["to"] == "owner@example.test"
        and h.email.sent[0]["subject"] == "SkillCoach email test"
    )
    h.runtime.config = replace(h.runtime.config, smtp_password="")
    with pytest.raises(ConfigurationError):
        email_test(h.runtime)


def test_web_routes_are_off_in_telegram_mode(harness):
    client = create_app(harness.runtime).test_client()
    page = client.get("/web", base_url=ORIGIN)
    assert page.status_code == 200 and b"Continue your learning" in page.data
    assert page.headers["Cache-Control"] == "no-store, private"
    assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
    assert client.get("/web/session", base_url=ORIGIN).status_code == 404
    response = client.post(
        "/web/login/start", base_url=ORIGIN, json={"email": "a@example.test"}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 404 and response.json["enabled"] is False
    assert client.get("/admin/login/options", base_url=ORIGIN).json == {"pin_channel": "telegram"}


# PostgreSQL: sign-in, inbox and administration ------------------------------------------------


@pytest.fixture
def web(pg_repo, config, monkeypatch):
    from test_multiuser import Bot

    # The response-time floor is covered by its own test; skip the real wait here.
    monkeypatch.setattr(web_channel, "START_FLOOR_SECONDS", 0)
    bot = Bot(pg_repo, config)
    learner, silent = bot.join(101), bot.join(102)
    with pg_repo.connection() as conn:
        conn.execute("UPDATE learners SET email='learner@example.test' WHERE id=%s", (learner.learner_id,))
    clock = SimpleNamespace(now=datetime.now(timezone.utc))
    bot.runtime.clock = lambda: clock.now
    bot.runtime.config = web_config(bot.config)
    bot.runtime.email = FakeEmail()
    app = create_app(bot.runtime)
    return SimpleNamespace(
        bot=bot,
        app=app,
        client=app.test_client(),
        email=bot.runtime.email,
        csrf=None,
        learner=learner,
        silent=silent,
        clock=clock,
    )


def post(web, path, body=None, *, client=None, csrf=True, origin=ORIGIN):
    headers = {"Origin": origin} if origin else {}
    if csrf and web.csrf:
        headers["X-CSRF-Token"] = web.csrf
    return (client or web.client).post(
        path, base_url=ORIGIN, json=body if body is not None else {}, headers=headers
    )


def emailed_code(web):
    return re.search(r"code is ([0-9]{6})", web.email.sent[-1]["text"]).group(1)


def sign_in(web, email, client=None):
    assert post(web, "/web/login/start", {"email": email}, client=client).status_code == 200
    response = post(web, "/web/login/verify", {"code": emailed_code(web)}, client=client)
    assert response.status_code == 200, response.json
    web.csrf = response.json["csrf"]
    return response


def send(web, **payload):
    return post(web, "/web/send", {"request_id": str(uuid4()), **payload})


@pytest.mark.postgres
def test_email_code_sign_in_is_private_rate_limited_and_single_use(web):
    unknown = post(web, "/web/login/start", {"email": "nobody@example.test"})
    known = post(web, "/web/login/start", {"email": " Learner@Example.TEST "})
    assert unknown.status_code == known.status_code == 200
    assert set(unknown.json) == set(known.json) == {"pending", "expires_at", "resend_at"}
    assert [mail["to"] for mail in web.email.sent] == ["learner@example.test"]
    assert web.email.sent[0]["subject"] == "Your SkillCoach sign-in code"
    code = emailed_code(web)
    # Repeats are limited the same way whether or not the address is registered.
    assert post(web, "/web/login/start", {"email": "learner@example.test"}).status_code == 429
    assert post(web, "/web/login/start", {"email": "nobody@example.test"}).status_code == 429
    wrong = "000000" if code != "000000" else "111111"
    failed = post(web, "/web/login/verify", {"code": wrong})
    assert failed.status_code == 400 and "4 attempts remaining" in failed.json["error"]
    assert post(web, "/web/login/verify", {"code": "12"}).status_code == 400
    verifier = web.client.get_cookie(LOGIN_COOKIE).value
    assert post(web, "/web/login/verify", {"code": code}, origin="https://evil.invalid").status_code == 403
    response = post(web, "/web/login/verify", {"code": code})
    assert response.status_code == 200 and response.json["name"] == "Learner 101"
    cookie = [value for value in response.headers.getlist("Set-Cookie") if value.startswith(WEB_COOKIE)][0]
    for flag in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/", "Max-Age=1209600"):
        assert flag in cookie
    assert web.client.get_cookie(LOGIN_COOKIE) is None
    replay = web.app.test_client()
    replay.set_cookie(LOGIN_COOKIE, verifier)
    assert post(web, "/web/login/verify", {"code": code}, client=replay).status_code == 403
    session = web.client.get("/web/session", base_url=ORIGIN)
    assert session.status_code == 200 and session.json["name"] == "Learner 101"
    with web.bot.repo.connection() as conn:
        row = conn.execute("SELECT * FROM web_logins WHERE learner_id IS NOT NULL").fetchone()
        assert code not in (row["code_hash"], row["email_hash"]) and "learner" not in row["email_hash"]
        assert conn.execute("SELECT count(*) AS n FROM web_sessions").fetchone()["n"] == 1
    owner = web.app.test_client()
    assert sign_in(web, "owner@example.test", client=owner).json["name"] == "You (owner)"
    assert post(web, "/web/login/start", {"email": "not an email"}).status_code == 403
    assert (
        post(web, "/web/login/start", {"email": "a@example.test"}, origin="https://evil.invalid").status_code
        == 403
    )


def add_logins(web, prefix, count, *, learner=None, notified=False):
    with web.bot.repo.connection() as conn:
        conn.execute(
            "INSERT INTO web_logins(id,email_hash,learner_id,verifier_hash,notified,requested_at,expires_at) "
            "SELECT %s::text||n, %s::text||n, %s, %s::text||n, %s, %s, %s FROM generate_series(1,%s) n",
            (
                prefix,
                prefix + "-address-",
                learner,
                prefix + "-verifier-",
                notified,
                web.clock.now,
                web.clock.now + timedelta(minutes=10),
                count,
            ),
        )


@pytest.mark.postgres
def test_sign_in_limits_bound_floods_and_answer_every_address_the_same(web):
    signed_in = web.app.test_client()
    sign_in(web, "learner@example.test", client=signed_in)
    add_logins(web, "flood", MAX_UNKNOWN_PER_HOUR)
    sent = len(web.email.sent)
    for email in ("nobody@example.test", "owner@example.test"):
        flooded = post(web, "/web/login/start", {"email": email}, client=web.app.test_client())
        assert flooded.status_code == 429 and "Too many sign-in requests" in flooded.json["error"]
    assert len(web.email.sent) == sent
    assert signed_in.get("/web/session", base_url=ORIGIN).status_code == 200
    # An hour later the flood no longer counts. A failed send gets the usual answer and no code.
    web.clock.now += timedelta(minutes=61)
    web.email.fail = True
    owner = web.app.test_client()
    failed = post(web, "/web/login/start", {"email": "owner@example.test"}, client=owner)
    assert failed.status_code == 200 and set(failed.json) == {"pending", "expires_at", "resend_at"}
    with web.bot.repo.connection() as conn:
        row = conn.execute("SELECT status, notified FROM web_logins WHERE learner_id='owner'").fetchone()
    assert row["status"] == "rejected" and not row["notified"]
    # Past the hourly email limit, registered addresses get the usual answer but no email.
    web.email.fail = False
    web.clock.now += timedelta(seconds=61)
    add_logins(web, "sent", MAX_SENDS_PER_HOUR, learner=web.silent.learner_id, notified=True)
    capped = post(web, "/web/login/start", {"email": "owner@example.test"}, client=owner)
    assert capped.status_code == 200 and len(web.email.sent) == sent
    with web.bot.repo.connection() as conn:
        latest = conn.execute(
            "SELECT code_hash, notified FROM web_logins WHERE learner_id='owner' AND status='pending'"
        ).fetchone()
    assert latest["code_hash"] is None and not latest["notified"]
    assert post(web, "/web/login/verify", {"code": "123456"}, client=owner).status_code == 400


@pytest.mark.postgres
def test_sessions_end_when_the_sign_in_address_changes(web):
    owner = web.app.test_client()
    sign_in(web, "owner@example.test", client=owner)
    sign_in(web, "learner@example.test")
    assert owner.get("/web/session", base_url=ORIGIN).status_code == 200
    assert web.client.get("/web/session", base_url=ORIGIN).status_code == 200
    web.bot.runtime.config = replace(web.bot.runtime.config, owner_email="new-owner@example.test")
    assert owner.get("/web/session", base_url=ORIGIN).status_code == 403
    with web.bot.repo.connection() as conn:
        conn.execute("UPDATE learners SET email='moved@example.test' WHERE id=%s", (web.learner.learner_id,))
    assert web.client.get("/web/session", base_url=ORIGIN).status_code == 403
    assert post(web, "/web/feed").status_code == 403


@pytest.mark.postgres
def test_inbox_follows_delivery_order_when_an_old_message_is_sent_again(web):
    sign_in(web, "learner@example.test")
    first = str(uuid4())
    assert post(web, "/web/send", {"request_id": first, "text": "/help"}).json["status"] == "queued"
    assert send(web, text="/help").json["status"] == "queued"
    cursor = post(web, "/web/feed").json["messages"][-1]["id"]
    with web.bot.repo.connection() as conn:
        old = conn.execute(
            "SELECT id, sequence FROM outbox WHERE job_id=%s AND status='sent' AND body->>'kind'='text' "
            "ORDER BY sequence LIMIT 1",
            ("web:" + first,),
        ).fetchone()
        newest = conn.execute(
            "SELECT max(sequence) AS n FROM outbox WHERE learner_id=%s AND status='sent'",
            (web.learner.learner_id,),
        ).fetchone()["n"]
        assert old["sequence"] < newest
        # As after a failed send that /retry queues again.
        conn.execute("UPDATE outbox SET status='failed', available_at=now() WHERE id=%s", (old["id"],))
    web.bot.runtime.recover(media=False)
    later = post(web, "/web/feed", {"after": cursor}).json["messages"]
    with web.bot.repo.connection() as conn:
        resent = conn.execute("SELECT status, delivered_seq FROM outbox WHERE id=%s", (old["id"],)).fetchone()
    assert resent["status"] == "sent" and resent["delivered_seq"] > cursor
    assert [message["id"] for message in later] == [resent["delivered_seq"]]
    assert post(web, "/web/feed").json["messages"][-1]["id"] == resent["delivered_seq"]


@pytest.mark.postgres
def test_telegram_era_failures_stay_history_while_web_failures_are_retried(web):
    sign_in(web, "owner@example.test")
    alert, note = "alert:late:quiz:2026-09-30", "admin:note:mail"
    with web.bot.repo.connection() as conn:
        generation = conn.execute("SELECT generation FROM learners WHERE id='owner'").fetchone()["generation"]
        for job in (alert, note):
            conn.execute(
                "INSERT INTO jobs(id,payload,status,learner_id,access_generation) VALUES (%s,%s,'done','owner',%s)",
                (job, Jsonb({"type": "notice", "text": "x"}), generation),
            )
        for key, job, body, code in (
            (alert + ":0", alert, {"kind": "text", "text": "Delivery delay"}, "http_401"),
            (
                alert + ":0:delivery-error",
                alert,
                {"kind": "text", "text": "Could not deliver", "recovery_notice": True},
                "http_401",
            ),
            (note + ":1", note, {"kind": "email", "subject": "A note", "text": "Hi"}, "email_failed"),
        ):
            conn.execute(
                "INSERT INTO outbox(id,job_id,body,status,attempts,error_code,learner_id,access_generation) "
                "VALUES (%s,%s,%s,'failed',5,%s,'owner',%s)",
                (key, job, Jsonb(body), code, generation),
            )
    repo = web.bot.runtime.repo
    assert repo.failure_counts(web_mode=True, all_learners=True) == {
        "jobs": 0,
        "deliveries": 1,
        "telegram_history": 2,
    }
    assert repo.failure_counts(web_mode=False, all_learners=True)["deliveries"] == 3
    assert send(web, text="/retry").json["status"] == "queued"
    web.bot.runtime.recover(media=False)
    with web.bot.repo.connection() as conn:
        rows = {
            row["id"]: row
            for row in conn.execute(
                "SELECT id,status,attempts,error_code,delivered_seq FROM outbox WHERE job_id IN (%s,%s)",
                (alert, note),
            )
        }
    # History is preserved exactly and never reaches the inbox; the failed email was retried.
    for key in (alert + ":0", alert + ":0:delivery-error"):
        row = rows[key]
        assert (row["status"], row["attempts"], row["error_code"], row["delivered_seq"]) == (
            "failed",
            5,
            "http_401",
            None,
        )
    assert rows[note + ":1"]["status"] == "sent" and web.email.sent[-1]["subject"] == "A note"
    texts = "\n".join(message.get("text", "") for message in post(web, "/web/feed").json["messages"])
    assert "Delivery delay" not in texts and "Could not deliver" not in texts and "kept as history" in texts
    assert repo.failure_counts(web_mode=True, all_learners=True) == {
        "jobs": 0,
        "deliveries": 0,
        "telegram_history": 2,
    }
    assert send(web, text="/status").json["status"] == "queued"
    assert '"failed_before_web": 2' in post(web, "/web/feed").json["messages"][-1]["text"]


@pytest.mark.postgres
def test_web_migration_numbers_existing_sent_messages_in_delivery_order(pg_repo):
    now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
    with pg_repo.connection() as conn:
        # Return this schema to version 10, as on the live database before the upgrade.
        conn.execute("DROP TABLE web_sessions, web_logins")
        conn.execute("ALTER TABLE learners DROP COLUMN email")
        conn.execute("ALTER TABLE outbox DROP COLUMN delivered_seq")
        conn.execute("DROP SEQUENCE outbox_delivery_order")
        conn.execute("DELETE FROM schema_migrations WHERE version=11")
        conn.execute("INSERT INTO jobs(id,payload,status) VALUES ('before-upgrade','{}','done')")
        # Inserted in this order; the first was retried and delivered last.
        for key, status, delivered in (
            ("retried", "sent", now + timedelta(minutes=5)),
            ("prompt", "sent", now),
            ("waiting", "pending", None),
            ("undated", "sent", None),
        ):
            conn.execute(
                "INSERT INTO outbox(id,job_id,body,status,delivered_at) VALUES (%s,'before-upgrade',%s,%s,%s)",
                (key, Jsonb({"kind": "text", "text": key}), status, delivered),
            )
    pg_repo.migrate()
    with pg_repo.connection() as conn:
        rows = conn.execute(
            "SELECT id, delivered_seq FROM outbox WHERE job_id='before-upgrade' ORDER BY delivered_seq NULLS LAST"
        ).fetchall()
        following = conn.execute("SELECT nextval('outbox_delivery_order') AS n").fetchone()["n"]
        highest = conn.execute("SELECT max(delivered_seq) AS n FROM outbox").fetchone()["n"]
        assert conn.execute("SELECT max(version) AS v FROM schema_migrations").fetchone()["v"] == 11
    assert [row["id"] for row in rows] == ["undated", "prompt", "retried", "waiting"]
    assert rows[-1]["delivered_seq"] is None and following == highest + 1


@pytest.mark.postgres
def test_browser_conversation_runs_the_same_coach_through_the_inbox(web):
    sign_in(web, "learner@example.test")
    telegram_before = len(web.bot.runtime.telegram.chat_messages.get(101, []))
    first = post(web, "/web/feed")
    assert first.status_code == 200 and set(first.json) == {"messages", "working", "older"}
    last = first.json["messages"][-1]["id"] if first.json["messages"] else 0
    request_id = str(uuid4())
    accepted = post(web, "/web/send", {"request_id": request_id, "text": "/help"})
    assert accepted.status_code == 202 and accepted.json["status"] == "queued"
    assert post(web, "/web/send", {"request_id": request_id, "text": "/help"}).json["status"] == "duplicate"
    reply = post(web, "/web/feed", {"after": last}).json
    text = "\n".join(message.get("text", "") for message in reply["messages"])
    assert "/resources" in text and not reply["working"]
    assert len(web.bot.runtime.telegram.chat_messages.get(101, [])) == telegram_before
    with web.bot.repo.connection() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM jobs WHERE id=%s", ("web:" + request_id,)).fetchone()["n"]
            == 1
        )
    assert send(web, callback="home:today").json["status"] == "queued"
    denied = send(web, text="/invite someone")
    assert denied.json["status"] == "admin_elsewhere"
    latest = post(web, "/web/feed").json["messages"][-1]
    assert "admin console" in latest["text"]
    for body in ({"request_id": "bad", "text": "/help"}, {"request_id": str(uuid4())}):
        assert post(web, "/web/send", body).status_code == 403
    assert (
        post(web, "/web/send", {"request_id": str(uuid4()), "text": "/help"}, csrf=False).status_code == 403
    )
    assert post(web, "/web/feed", {"after": -1}).status_code == 403
    web.bot.input(web.bot.config.owner_id, "/revoke " + web.learner.learner_id)
    assert web.client.get("/web/session", base_url=ORIGIN).status_code == 403
    assert post(web, "/web/feed").status_code == 403


@pytest.mark.postgres
def test_mentor_notes_reach_the_inbox_and_the_learner_email_only(web):
    web.learner.enqueue("admin:note", {"type": "encouragement", "message": "goal"})
    web.silent.enqueue("admin:note", {"type": "encouragement", "message": "goal"})
    telegram_before = sum(len(v) for v in web.bot.runtime.telegram.chat_messages.values())
    web.bot.runtime.recover(media=False)
    assert sum(len(v) for v in web.bot.runtime.telegram.chat_messages.values()) == telegram_before
    assert [(mail["to"], mail["subject"]) for mail in web.email.sent] == [
        ("learner@example.test", "A note from your SkillCoach mentor")
    ]
    with web.bot.repo.connection() as conn:
        rows = conn.execute(
            "SELECT learner_id, status, body->>'kind' AS kind FROM outbox WHERE job_id LIKE '%%admin:note' "
            "ORDER BY learner_id, sequence"
        ).fetchall()
    by_learner = {}
    for row in rows:
        by_learner.setdefault(row["learner_id"], []).append((row["kind"], row["status"]))
    assert by_learner[web.learner.learner_id] == [("text", "sent"), ("email", "sent")]
    assert by_learner[web.silent.learner_id] == [("text", "sent"), ("email", "suppressed")]


@pytest.mark.postgres
def test_owner_pin_arrives_by_email_and_learner_emails_are_managed_in_admin(web):
    from test_admin import confirm, preview

    admin = SimpleNamespace(bot=web.bot, client=web.app.test_client(), csrf=None, clock=web.clock)
    assert admin.client.get("/admin/login/options", base_url=ORIGIN).json == {"pin_channel": "email"}
    telegram_before = len(web.bot.runtime.telegram.chat_messages.get(web.bot.config.owner_id, []))
    start = post(admin, "/admin/login/pin/start", client=admin.client, csrf=False)
    assert start.status_code == 200
    mail = web.email.sent[-1]
    assert mail["to"] == "owner@example.test" and mail["subject"] == "Your SkillCoach admin PIN"
    assert len(web.bot.runtime.telegram.chat_messages.get(web.bot.config.owner_id, [])) == telegram_before
    pin = re.search(r"PIN: ([0-9]{4})", mail["text"]).group(1)
    verified = post(admin, "/admin/login/pin/verify", {"pin": pin}, client=admin.client, csrf=False)
    assert verified.status_code == 200
    admin.csrf = verified.json["csrf"]
    overview = post(admin, "/admin/data", client=admin.client).json
    assert overview["web_mode"] is True
    emails = {member["id"]: member["web_email"] for member in overview["learners"]}
    assert emails["owner"] == "o•••@example.test" and emails[web.learner.learner_id] == "l•••@example.test"
    assert emails[web.silent.learner_id] is None
    learner_browser = web.app.test_client()
    sign_in(web, "learner@example.test", client=learner_browser)
    assert learner_browser.get("/web/session", base_url=ORIGIN).status_code == 200
    target = web.learner.learner_id
    for arguments, status in (
        ({"email": "owner@example.test"}, 409),
        ({"email": "not-an-address"}, 403),
    ):
        assert preview(admin, "set_email", target, arguments).status_code == status
    assert preview(admin, "set_email", "owner", {"email": "x@example.test"}).status_code == 403
    assert (
        preview(admin, "set_email", web.silent.learner_id, {"email": "learner@example.test"}).status_code
        == 409
    )
    pending = preview(admin, "set_email", target, {"email": "New.Address@Example.test"})
    assert (
        pending.status_code == 200
        and "Web sign-in email: n•••@example.test" in pending.json["preview"]["details"]
    )
    assert confirm(admin, pending.json).json["messages"] == ["Web sign-in email saved."]
    with web.bot.repo.connection() as conn:
        assert conn.execute("SELECT email FROM learners WHERE id=%s", (target,)).fetchone()["email"] == (
            "new.address@example.test"
        )
    # A changed address ends that learner's browser sessions.
    assert learner_browser.get("/web/session", base_url=ORIGIN).status_code == 403
    removal = preview(admin, "set_email", target, {"email": ""})
    assert confirm(admin, removal.json).json["messages"] == ["Web sign-in email removed."]


@pytest.mark.postgres
def test_lesson_reader_serves_only_the_learners_lessons_and_library(web):
    from skillcoach.catalog import TOPICS

    sign_in(web, "learner@example.test")
    topic = next(iter(TOPICS))
    library = post(web, "/web/lesson", {"topic": topic})
    assert library.status_code == 200 and library.json["lesson"]["library"] and library.json["private"]
    assert post(web, "/web/lesson", {"topic": "../../x"}).status_code == 404
    assert post(web, "/web/lesson", {"lesson": "0123456789abcdef0123"}).status_code == 404
    assert post(web, "/web/lesson", {"lesson": "bad"}).status_code == 404
    assert post(web, "/web/lesson", {"lesson": "0123456789abcdef0123", "topic": topic}).status_code == 403
    assert post(web, "/web/lesson", {"topic": topic}, csrf=False).status_code == 403
