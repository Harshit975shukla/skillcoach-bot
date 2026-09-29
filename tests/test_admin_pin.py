import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
import test_admin
from test_admin import ORIGIN, post

from skillcoach.admin_auth import LOGIN_COOKIE, SESSION_COOKIE, digest
from skillcoach.web import create_app

pytestmark = pytest.mark.postgres
admin_fixture = test_admin.admin


@pytest.fixture(name="admin")
def pin_admin(admin_fixture):
    return admin_fixture


def begin(admin):
    response = post(admin, "/admin/login/pin/start")
    assert response.status_code == 200
    text, buttons = admin.bot.runtime.telegram.chat_messages[admin.bot.config.owner_id][-1]
    assert buttons is None
    return response, re.search(r"PIN: ([0-9]{4})", text).group(1)


def verify(admin, pin, **kwargs):
    return post(admin, "/admin/login/pin/verify", {"pin": pin}, **kwargs)


def test_pin_is_owner_only_cookie_bound_single_use_and_never_returned(admin, monkeypatch):
    monkeypatch.setattr("skillcoach.admin_auth.secrets.randbelow", lambda _: 7)
    response, pin = begin(admin)
    assert pin == "0007"
    assert set(admin.bot.runtime.telegram.chat_messages) == {admin.bot.config.owner_id}
    assert response.json["method"] == "pin" and response.json["attempts_remaining"] == 3
    assert set(response.json) == {
        "method",
        "attempts_remaining",
        "pending",
        "authenticated",
        "expires_at",
        "resend_at",
    }
    for flag in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/", "Max-Age=300"):
        assert flag in response.headers["Set-Cookie"]
    verifier = admin.client.get_cookie(LOGIN_COOKIE).value
    other = admin.app.test_client()
    assert verify(admin, pin, client=other).status_code == 403
    assert post(admin, "/admin/login/status", client=other).status_code == 403
    assert verify(admin, pin, origin="https://evil.invalid").status_code == 403
    assert post(admin, "/admin/data").status_code == 403
    with admin.bot.repo.connection() as conn:
        row = conn.execute("SELECT * FROM admin_logins").fetchone()
        assert row["display_code"] == "" and row["pin_hash"] != pin
        assert row["pin_attempts"] == 0 and row["notified"]
        assert conn.execute("SELECT count(*) AS n FROM outbox").fetchone()["n"] == 0
    # An old approval URL or callback cannot bypass a PIN.
    admin.bot.input(admin.bot.config.owner_id, callback="adminlogin:approve:" + row["id"], drain=False)
    with admin.bot.repo.connection() as conn:
        assert conn.execute("SELECT status FROM admin_logins").fetchone()["status"] == "pending"
    reopened = admin.app.test_client()
    reopened.set_cookie(LOGIN_COOKIE, verifier)
    assert post(admin, "/admin/login/status", client=reopened).json == response.json
    signed_in = verify(admin, pin, client=reopened)
    assert signed_in.status_code == 200 and signed_in.json["authenticated"]
    assert reopened.get_cookie(SESSION_COOKIE) is not None
    assert reopened.get_cookie(LOGIN_COOKIE) is None
    assert verify(admin, pin).status_code == 403
    with admin.bot.repo.connection() as conn:
        assert conn.execute("SELECT status FROM admin_logins").fetchone()["status"] == "consumed"
        assert conn.execute("SELECT count(*) AS n FROM admin_sessions").fetchone()["n"] == 1


def test_bad_guesses_commit_attempts_and_lock_pin(admin):
    _, pin = begin(admin)
    wrong = "1234" if pin != "1234" else "4321"
    for remaining in (2, 1):
        response = verify(admin, wrong)
        assert response.status_code == 400 and f"{remaining} attempts" in response.json["error"]
    assert verify(admin, wrong).status_code == 403
    assert verify(admin, pin).status_code == 403
    with admin.bot.repo.connection() as conn:
        row = conn.execute("SELECT * FROM admin_logins").fetchone()
        assert row["status"] == "rejected" and row["pin_attempts"] == 3
        assert conn.execute("SELECT count(*) AS n FROM admin_sessions").fetchone()["n"] == 0


def test_owner_wide_guess_limit_survives_new_requests(admin):
    _, pin = begin(admin)
    wrong = "1234" if pin != "1234" else "4321"
    for _ in range(3):
        verify(admin, wrong)
    admin.clock.now += timedelta(seconds=61)
    _, pin = begin(admin)
    wrong = "1234" if pin != "1234" else "4321"
    verify(admin, wrong)
    verify(admin, wrong)
    assert verify(admin, pin).status_code == 429
    admin.clock.now += timedelta(seconds=61)
    assert post(admin, "/admin/login/pin/start").status_code == 429
    assert len(admin.bot.runtime.telegram.chat_messages[admin.bot.config.owner_id]) == 2


def test_resend_throttles_invalidates_old_pin_and_expires(admin):
    _, first = begin(admin)
    old_cookie = admin.client.get_cookie(LOGIN_COOKIE).value
    assert post(admin, "/admin/login/pin/start").status_code == 429
    assert len(admin.bot.runtime.telegram.chat_messages[admin.bot.config.owner_id]) == 1
    admin.clock.now += timedelta(seconds=61)
    _, second = begin(admin)
    old = admin.app.test_client()
    old.set_cookie(LOGIN_COOKIE, old_cookie)
    assert verify(admin, first, client=old).status_code == 403
    admin.clock.now += timedelta(minutes=5)
    assert verify(admin, second).status_code == 403


def test_send_limits_are_owner_wide_hourly_and_daily(admin):
    for index in range(10):
        if index == 5:
            assert post(admin, "/admin/login/pin/start").status_code == 429
            admin.clock.now += timedelta(hours=1)
        begin(admin)
        admin.clock.now += timedelta(seconds=61)
    admin.clock.now += timedelta(hours=1)
    assert post(admin, "/admin/login/pin/start").status_code == 429
    assert len(admin.bot.runtime.telegram.chat_messages[admin.bot.config.owner_id]) == 10


def test_failed_delivery_invalidates_pin_and_does_not_report_sent(admin, monkeypatch):
    monkeypatch.setattr("skillcoach.admin_auth.secrets.randbelow", lambda _: 1234)
    admin.bot.runtime.telegram.fail = True
    response = post(admin, "/admin/login/pin/start")
    assert response.status_code == 503 and "invalid" in response.json["error"]
    assert admin.client.get_cookie(LOGIN_COOKIE) is None
    with admin.bot.repo.connection() as conn:
        row = conn.execute("SELECT * FROM admin_logins").fetchone()
        assert row["status"] == "rejected" and not row["notified"]


def test_telegram_send_holds_no_database_locks(admin, monkeypatch):
    def recipient(chat_id):
        assert chat_id == admin.bot.config.owner_id

        def send(text, budget):
            with admin.bot.repo.connection() as conn:
                conn.execute("SELECT id FROM learners WHERE id='owner' FOR UPDATE NOWAIT")
                conn.execute("SELECT id FROM admin_logins FOR UPDATE NOWAIT")
            assert budget.remaining() <= 12

        return SimpleNamespace(send=send)

    monkeypatch.setattr(admin.bot.runtime.telegram, "for_chat", recipient)
    assert post(admin, "/admin/login/pin/start").status_code == 200


def test_concurrent_correct_pin_is_consumed_once(admin):
    _, pin = begin(admin)
    verifier = admin.client.get_cookie(LOGIN_COOKIE).value

    def attempt(_):
        client = admin.app.test_client()
        client.set_cookie(LOGIN_COOKIE, verifier)
        return verify(admin, pin, client=client).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == [200, 403]
    with admin.bot.repo.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM admin_sessions").fetchone()["n"] == 1


def test_concurrent_pin_sends_have_one_delivery_and_request(admin):
    def attempt(_):
        return post(admin, "/admin/login/pin/start", client=admin.app.test_client()).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == [200, 429]
    assert len(admin.bot.runtime.telegram.chat_messages[admin.bot.config.owner_id]) == 1
    with admin.bot.repo.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM admin_logins").fetchone()["n"] == 1


def test_concurrent_bad_pin_attempts_cannot_exceed_limit(admin):
    _, pin = begin(admin)
    verifier = admin.client.get_cookie(LOGIN_COOKIE).value
    wrong = "1234" if pin != "1234" else "4321"

    def attempt(_):
        client = admin.app.test_client()
        client.set_cookie(LOGIN_COOKIE, verifier)
        return verify(admin, wrong, client=client).status_code

    with ThreadPoolExecutor(max_workers=5) as pool:
        statuses = list(pool.map(attempt, range(5)))
    assert statuses.count(400) == 2 and statuses.count(403) == 3
    with admin.bot.repo.connection() as conn:
        assert conn.execute("SELECT pin_attempts FROM admin_logins").fetchone()["pin_attempts"] == 3


@pytest.mark.parametrize("pin", ["123", "12345", "abcd", "１２３４", 1234, None, True])
def test_pin_validation_rejects_non_four_ascii_digits(admin, pin):
    begin(admin)
    assert verify(admin, pin).status_code == 400
    with admin.bot.repo.connection() as conn:
        assert conn.execute("SELECT pin_attempts FROM admin_logins").fetchone()["pin_attempts"] == 0


def test_pin_routes_deny_cross_origin_and_unconfigured_owner(admin):
    assert post(admin, "/admin/login/pin/start", origin=None).status_code == 403
    assert post(admin, "/admin/login/pin/start", {"owner_id": 999}).status_code == 403
    assert admin.client.get("/admin/login/pin/start", base_url=ORIGIN).status_code == 405
    admin.bot.runtime.config = replace(admin.bot.runtime.config, owner_id=0)
    client = create_app(admin.bot.runtime).test_client()
    assert post(admin, "/admin/login/pin/start", client=client).status_code == 403
    assert not admin.bot.runtime.telegram.chat_messages


def test_wrong_cookie_cannot_spend_another_request_attempts(admin):
    _, pin = begin(admin)
    client = admin.app.test_client()
    client.set_cookie(LOGIN_COOKIE, "x" * 43)
    assert verify(admin, pin, client=client).status_code == 403
    with admin.bot.repo.connection() as conn:
        assert (
            conn.execute(
                "SELECT pin_attempts FROM admin_logins WHERE verifier_hash=%s",
                (digest(admin.client.get_cookie(LOGIN_COOKIE).value),),
            ).fetchone()["pin_attempts"]
            == 0
        )
