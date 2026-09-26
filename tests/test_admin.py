from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from test_dashboard import signed
from test_flows import PROFILE
from test_multiuser import Bot

from skillcoach.admin import execute_action
from skillcoach.admin_auth import LOGIN_COOKIE, SESSION_COOKIE, digest
from skillcoach.models import Interview, InterviewFeedback, OpenQuestion, Profile, Task
from skillcoach.web import create_app

ORIGIN = "https://localhost"
pytestmark = pytest.mark.postgres


@pytest.fixture
def admin(pg_repo, config):
    bot = Bot(pg_repo, config)
    clock = SimpleNamespace(now=datetime.now(timezone.utc))
    bot.runtime.clock = lambda: clock.now
    app = create_app(bot.runtime)
    client = app.test_client()
    return SimpleNamespace(bot=bot, clock=clock, app=app, client=client, csrf=None)


def post(admin, path, body=None, *, client=None, csrf=True, origin=ORIGIN):
    headers = {"Origin": origin} if origin else {}
    if csrf and admin.csrf:
        headers["X-CSRF-Token"] = admin.csrf
    return (client or admin.client).post(path, base_url=ORIGIN, json=body or {}, headers=headers)


def login(admin, actor=None):
    response = post(
        admin,
        "/admin/session",
        {
            "init_data": signed(
                actor or admin.bot.config.owner_id,
                admin.bot.config.telegram_token,
                int(admin.clock.now.timestamp()),
            )
        },
    )
    if response.status_code == 200:
        admin.csrf = response.json["csrf"]
    return response


def preview(admin, action="invite", target="owner", arguments=None, ident=None):
    return post(
        admin,
        "/admin/action/preview",
        {
            "request_id": ident or str(uuid4()),
            "action": action,
            "target": target,
            "arguments": arguments if arguments is not None else {"label": "Test invitation"},
        },
    )


def confirm(admin, value):
    return post(
        admin,
        "/admin/action/execute",
        {
            "request_id": value["request_id"],
            "confirmation": value["confirmation"],
        },
    )


def test_direct_browser_is_private_and_signed_owner_cookie_is_secure(admin):
    page = admin.client.get("/admin", base_url=ORIGIN)
    assert page.status_code == 200 and b"Sign in through Telegram" in page.data
    assert page.headers["Cache-Control"] == "no-store, private"
    assert post(admin, "/admin/data").status_code == 403
    assert admin.client.get("/admin/session", base_url=ORIGIN).status_code == 403
    response = login(admin)
    assert response.status_code == 200
    cookie = response.headers["Set-Cookie"]
    for flag in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/", "Max-Age=900"):
        assert flag in cookie
    assert SESSION_COOKIE in cookie
    assert post(admin, "/admin/data").status_code == 200
    assert post(admin, "/admin/logout").json["logged_out"]
    assert post(admin, "/admin/data").status_code == 403


def test_nonowner_forged_stale_and_claimed_role_cannot_sign_in(admin):
    guest = admin.bot.join(101)
    assert login(admin, 101).status_code == 403
    admin.bot.input(admin.bot.config.owner_id, "/revoke " + guest.learner_id)
    assert login(admin, 101).status_code == 403
    for payload in (
        {"init_data": signed(42, "wrong-token", int(admin.clock.now.timestamp()))},
        {"init_data": signed(42, admin.bot.config.telegram_token, int(admin.clock.now.timestamp()) - 301)},
        {"init_data": "", "owner_id": 42, "role": "owner"},
    ):
        assert post(admin, "/admin/session", payload).status_code == 403


def test_browser_approval_is_owner_only_and_bound_to_initiating_cookie(admin):
    started = post(admin, "/admin/login/start").json
    assert admin.client.get_cookie(LOGIN_COOKIE) is not None
    token = parse_qs(urlsplit(started["telegram_url"]).query)["start"][0]
    identifier = token.removeprefix("admin_login_")
    assert admin.bot.input(999, "/start " + token) == "denied"
    assert admin.bot.input(admin.bot.config.owner_id, "/start " + token) == "admin_login_requested"
    message, buttons = admin.bot.runtime.telegram.messages[-1]
    assert started["code"] in message
    assert "Approve only if YOU" in message
    assert post(admin, "/admin/login/status").json["pending"]
    assert admin.bot.input(999, callback=buttons[0][0]["callback_data"]) == "denied"
    other = admin.app.test_client()
    assert post(admin, "/admin/login/status", client=other).status_code == 403
    assert post(admin, "/admin/login/status", {"id": identifier}, client=other).status_code == 403
    assert (
        admin.bot.input(admin.bot.config.owner_id, callback=buttons[0][0]["callback_data"])
        == "admin_login_approved"
    )
    response = post(admin, "/admin/login/status")
    assert response.status_code == 200 and response.json["authenticated"]
    admin.csrf = response.json["csrf"]
    assert post(admin, "/admin/data").status_code == 200
    assert post(admin, "/admin/login/status").status_code == 403  # one-use exchange
    assert post(admin, "/admin/data", client=other).status_code == 403
    with admin.bot.repo.connection() as conn:
        assert (
            conn.execute("SELECT status FROM admin_logins WHERE id=%s", (identifier,)).fetchone()["status"]
            == "consumed"
        )


def test_rejected_or_expired_browser_challenge_cannot_create_session(admin):
    started = post(admin, "/admin/login/start").json
    token = parse_qs(urlsplit(started["telegram_url"]).query)["start"][0]
    identifier = token.removeprefix("admin_login_")
    admin.bot.input(admin.bot.config.owner_id, callback="adminlogin:reject:" + identifier)
    assert post(admin, "/admin/login/status").status_code == 403
    started = post(admin, "/admin/login/start").json
    identifier = parse_qs(urlsplit(started["telegram_url"]).query)["start"][0].removeprefix("admin_login_")
    with admin.bot.repo.connection() as conn:
        conn.execute(
            "UPDATE admin_logins SET expires_at=now()-interval '1 second' WHERE id=%s", (identifier,)
        )
    assert post(admin, "/admin/login/status").status_code == 403
    assert (
        admin.bot.input(admin.bot.config.owner_id, callback="adminlogin:approve:" + identifier)
        == "admin_login_closed"
    )


def test_csrf_origin_and_get_cannot_perform_mutations(admin):
    login(admin)
    body = {"request_id": str(uuid4()), "action": "invite", "target": "owner", "arguments": {"label": "test"}}
    assert post(admin, "/admin/action/preview", body, csrf=False).status_code == 403
    assert post(admin, "/admin/action/preview", body, origin="https://evil.invalid").status_code == 403
    assert post(admin, "/admin/action/preview", body, origin=None).status_code == 403
    assert admin.client.get("/admin/action/execute", base_url=ORIGIN).status_code == 405
    assert admin.client.get("/admin/login/status", base_url=ORIGIN).status_code == 405
    assert post(admin, "/admin/data?owner_id=42").status_code == 403
    with admin.bot.repo.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM admin_requests").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM invitations").fetchone()["n"] == 0


def test_preview_is_nonmutating_and_confirmation_is_idempotent(admin):
    login(admin)
    ident = str(uuid4())
    response = preview(admin, arguments={"label": "  A friend  "}, ident=ident)
    assert response.status_code == 200
    with admin.bot.repo.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM invitations").fetchone()["n"] == 0
    again = preview(admin, arguments={"label": "  A friend  "}, ident=ident)
    assert again.status_code == 200 and again.json["confirmation"] == response.json["confirmation"]
    result = confirm(admin, response.json)
    assert result.status_code == 200 and "start=invite_" in "\n".join(result.json["messages"])
    duplicate = confirm(admin, response.json)
    assert duplicate.json["duplicate"] is True
    with admin.bot.repo.connection() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM invitations WHERE label='A friend'").fetchone()["n"] == 1
        )
        assert (
            conn.execute("SELECT count(*) AS n FROM admin_audit WHERE request_id=%s", (ident,)).fetchone()[
                "n"
            ]
            == 1
        )
        assert (
            conn.execute("SELECT count(*) AS n FROM outbox WHERE job_id=%s", ("admin:" + ident,)).fetchone()[
                "n"
            ]
            == 0
        )


def test_concurrent_confirmation_issues_only_one_invitation(admin):
    login(admin)
    value = preview(admin).json
    token = admin.client.get_cookie(SESSION_COOKIE).value
    session = {"token_hash": digest(token)}
    body = {"request_id": value["request_id"], "confirmation": value["confirmation"]}
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: execute_action(admin.bot.runtime, session, body), range(2)))
    assert sum(result.get("duplicate", False) for result in results) == 1
    with admin.bot.repo.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM invitations").fetchone()["n"] == 1


def test_confirmation_cannot_be_tampered_stolen_or_used_after_expiry(admin):
    login(admin)
    value = preview(admin).json
    assert confirm(admin, {**value, "confirmation": "0" * 64}).status_code == 403
    login(admin)  # another session cannot claim the first session's preview
    assert confirm(admin, value).status_code == 403
    value = preview(admin).json
    assert (
        post(
            admin,
            "/admin/action/execute",
            {
                "request_id": value["request_id"],
                "confirmation": value["confirmation"],
                "target": "someone-else",
            },
        ).status_code
        == 403
    )
    admin.clock.now += timedelta(minutes=6)
    assert confirm(admin, value).status_code == 409
    admin.clock.now += timedelta(minutes=10)
    assert post(admin, "/admin/data").status_code == 403


def test_owner_identity_change_invalidates_browser_session(admin):
    from dataclasses import replace

    login(admin)
    admin.bot.runtime.config = replace(admin.bot.runtime.config, owner_id=84)
    assert post(admin, "/admin/data").status_code == 403


def test_member_access_is_revalidated_and_nonowner_can_never_use_admin(admin):
    recipient = admin.bot.join(101, approve=False)
    login(admin)
    value = preview(admin, "approve", recipient.learner_id, {}).json
    admin.bot.input(admin.bot.config.owner_id, "/reject " + recipient.learner_id)
    assert confirm(admin, value).status_code == 409
    assert admin.bot.member(101)["status"] == "rejected"
    assert preview(admin, "revoke", "owner", {}).status_code == 403


def test_targeted_commands_do_not_modify_other_learners_or_owner_quiz(admin):
    a, b = admin.bot.join(101), admin.bot.join(102)
    login(admin)
    due = admin.clock.now + timedelta(hours=2)
    admin.bot.repo.enqueue("owner-future-quiz", {"type": "schedule", "kind": "quiz"}, available_at=due)
    value = preview(admin, "pause", a.learner_id, {}).json
    assert confirm(admin, value).json["state"] == "queued"
    admin.bot.runtime.recover(media=False)
    assert a.read()[1].paused and not b.read()[1].paused and not admin.bot.repo.read()[1].paused
    with admin.bot.repo.connection() as conn:
        job = conn.execute("SELECT status,available_at FROM jobs WHERE id='owner-future-quiz'").fetchone()
        assert job["status"] == "pending" and job["available_at"] == due
    assert (
        preview(admin, "owner_command", b.learner_id, {"command": "learn", "argument": "EC2"}).status_code
        == 403
    )


@pytest.mark.parametrize(
    "command,argument",
    [
        ("q", "A"),
        ("complete", "task"),
        ("setup", ""),
        ("profile", "setup"),
        ("resume", ""),
        ("sql", "drop table jobs"),
        ("shell", "whoami"),
        ("media", "invalid"),
    ],
)
def test_unapproved_command_shapes_fail_explicitly(admin, command, argument):
    login(admin)
    assert (
        preview(admin, "owner_command", "owner", {"command": command, "argument": argument}).status_code
        == 403
    )


def test_scheduled_quiz_preview_cannot_overwrite_existing_due_request(admin):
    login(admin)
    due = admin.clock.now + timedelta(hours=2)
    args = {"topic": "EC2", "at": due.isoformat()}
    value = preview(admin, "schedule_quiz", "owner", args).json
    assert confirm(admin, value).json["state"] == "queued"
    assert (
        preview(
            admin, "schedule_quiz", "owner", {"topic": "IAM", "at": (due + timedelta(minutes=5)).isoformat()}
        ).status_code
        == 409
    )
    with admin.bot.repo.connection() as conn:
        row = conn.execute(
            "SELECT payload,available_at FROM jobs WHERE id LIKE 'requested:quiz:%'"
        ).fetchone()
        assert row["available_at"] == due and row["payload"]["requested_topic"] == "EC2"


def test_admin_overview_contains_counts_not_private_learning_content(admin):
    guest = admin.bot.join(101)
    private = "DO-NOT-EXPOSE-LEARNER-CONTENT"

    def seed(state):
        state.profile = Profile(
            **{**PROFILE, "name": private, "target_role": private, "resume_text": private, "jd_text": private}
        )
        state.tasks["private-task"] = Task(
            id="private-task",
            origin="private-task",
            title=private,
            detail=private,
            skill=private,
            assigned_date=admin.clock.now.date(),
        )
        state.interviews["private-interview"] = Interview(
            id="private-interview",
            question=OpenQuestion(skill=private, question=private),
            answer=private,
            status="completed",
            completed_at=admin.clock.now,
            feedback=InterviewFeedback(
                score=7, accuracy=7, reasoning=7, communication=7, feedback=private, model_answer=private
            ),
        )

    admin.bot.save(guest, seed)
    login(admin)
    response = post(admin, "/admin/data")
    assert response.status_code == 200
    assert private not in response.get_data(as_text=True)
    assert "resume_text" not in response.get_data(as_text=True)
    member = next(item for item in response.json["learners"] if item["id"] == guest.learner_id)
    assert member["progress"]["assigned"] == 1 and member["progress"]["interviews_completed"] == 1
    assert "profile" not in member and "telegram_id" not in member
    assert response.headers["Cache-Control"] == "no-store, private"


def memory_login(admin, actor=None, issued=None):
    init_data = signed(
        actor or admin.bot.config.owner_id,
        admin.bot.config.telegram_token,
        int(admin.clock.now.timestamp()) if issued is None else issued,
    )
    response = post(admin, "/admin/telegram-session", {"init_data": init_data})
    return response, init_data


def memory_post(admin, path, body, session, init_data, *, origin=ORIGIN, csrf=True):
    headers = {
        "Origin": origin,
        "X-Admin-Session": session["session_token"],
        "X-Telegram-Init-Data": init_data,
    }
    if csrf:
        headers["X-CSRF-Token"] = session["csrf"]
    return admin.client.post(path, base_url=ORIGIN, json=body, headers=headers)


def test_one_tap_owner_session_needs_no_cookies_and_logs_out(admin):
    response, init_data = memory_login(admin)
    assert response.status_code == 200 and response.json["transport"] == "telegram"
    assert "Set-Cookie" not in response.headers
    assert response.headers["Cache-Control"] == "no-store, private"
    session = response.json
    assert session["session_token"].startswith("tg_")
    assert (datetime.fromisoformat(session["expires_at"]) - admin.clock.now).total_seconds() <= 300
    assert admin.client.get_cookie(SESSION_COOKIE) is None
    assert memory_post(admin, "/admin/data", {}, session, init_data).status_code == 200
    assert memory_post(admin, "/admin/data", {}, session, init_data, csrf=False).status_code == 403
    assert (
        memory_post(admin, "/admin/data", {}, session, init_data, origin="https://evil.invalid").status_code
        == 403
    )
    assert memory_post(admin, "/admin/logout", {}, session, init_data).json["logged_out"]
    assert memory_post(admin, "/admin/data", {}, session, init_data).status_code == 403


def test_one_tap_revalidates_signed_owner_and_freshness_on_every_request(admin):
    response, init_data = memory_login(admin)
    session = response.json
    guest_data = signed(101, admin.bot.config.telegram_token, int(admin.clock.now.timestamp()))
    assert memory_post(admin, "/admin/data", {}, session, guest_data).status_code == 403
    assert memory_post(admin, "/admin/data", {}, session, init_data + "&user=bad").status_code == 403
    assert memory_post(admin, "/admin/data", {}, session, "").status_code == 403
    admin.clock.now += timedelta(seconds=301)
    assert memory_post(admin, "/admin/data", {}, session, init_data).status_code == 403
    assert memory_login(admin, actor=101)[0].status_code == 403


def test_one_tap_session_cannot_downgrade_to_cookie_or_mix_credentials(admin):
    response, init_data = memory_login(admin)
    session = response.json
    admin.client.set_cookie(SESSION_COOKIE, session["session_token"])
    admin.csrf = session["csrf"]
    assert post(admin, "/admin/data").status_code == 403
    admin.client.delete_cookie(SESSION_COOKIE)
    login(admin)  # A distinct browser-cookie session must not silently switch preview identity.
    assert memory_post(admin, "/admin/data", {}, session, init_data).status_code == 403


def test_one_tap_preview_stays_bound_to_its_memory_session(admin):
    first, init_data = memory_login(admin)
    session = first.json
    body = {
        "request_id": str(uuid4()),
        "action": "invite",
        "target": "owner",
        "arguments": {"label": "One tap test"},
    }
    previewed = memory_post(admin, "/admin/action/preview", body, session, init_data)
    assert previewed.status_code == 200
    confirmation = {
        "request_id": previewed.json["request_id"],
        "confirmation": previewed.json["confirmation"],
    }
    second, second_data = memory_login(admin)
    assert (
        memory_post(admin, "/admin/action/execute", confirmation, second.json, second_data).status_code == 403
    )
    assert memory_post(admin, "/admin/action/execute", confirmation, session, init_data).status_code == 200
    assert memory_post(admin, "/admin/action/execute", confirmation, session, init_data).json["duplicate"]


def test_one_tap_owner_reconfiguration_invalidates_header_session(admin):
    from dataclasses import replace

    response, init_data = memory_login(admin)
    admin.bot.runtime.config = replace(admin.bot.runtime.config, owner_id=84)
    assert memory_post(admin, "/admin/data", {}, response.json, init_data).status_code == 403


def test_admin_command_has_one_tap_and_normal_browser_choices(admin):
    from dataclasses import replace

    config = replace(admin.bot.config, private_dashboard_url="https://example.com/app")
    admin.bot.config = config
    admin.bot.runtime.config = config
    admin.bot.input(config.owner_id, "/admin")
    buttons = admin.bot.runtime.telegram.messages[-1][1]
    assert buttons == [
        [{"text": "Open Admin in Telegram", "web_app": {"url": "https://example.com/admin"}}],
        [{"text": "Open in browser", "url": "https://example.com/admin"}],
    ]
