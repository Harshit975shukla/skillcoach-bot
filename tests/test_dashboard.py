import hashlib
import hmac
import json
import time
from dataclasses import replace
from datetime import datetime
from urllib.parse import urlencode

import pytest
from test_multiuser import Bot

from skillcoach.dashboard import DashboardDenied, verify_init_data
from skillcoach.web import create_app


def signed(user_id, token, issued=None, **extra):
    fields = {
        "auth_date": str(issued if issued is not None else int(time.time())),
        "user": json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":")),
        **extra,
    }
    content = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(key, content.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_telegram_signature_age_duplicate_and_user_shape_validation():
    assert verify_init_data(signed(42, "token", 1000), "token", 1001) == (42, 1000)
    with pytest.raises(DashboardDenied):
        verify_init_data(signed(42, "wrong", 1000), "token", 1001)
    with pytest.raises(DashboardDenied):
        verify_init_data(signed(42, "token", 1000), "token", 1301)
    with pytest.raises(DashboardDenied):
        verify_init_data(signed(42, "token", 1050), "token", 1000)
    with pytest.raises(DashboardDenied):
        verify_init_data(signed(True, "token", 1000), "token", 1001)
    with pytest.raises(DashboardDenied):
        verify_init_data(signed(2**63, "token", 1000), "token", 1001)
    with pytest.raises(DashboardDenied):
        verify_init_data(signed(42, "token", 1000) + "&auth_date=1000", "token", 1001)


def test_private_dashboard_requires_signed_launch_and_does_not_cache(harness, monkeypatch):
    monkeypatch.setattr(
        "skillcoach.dashboard.learner_view",
        lambda *args: pytest.fail("Unauthenticated request reached private storage"),
    )
    client = create_app(harness.runtime).test_client()
    response = client.post("/app/data", json={"init_data": ""})
    assert response.status_code == 403
    assert response.headers["Cache-Control"] == "no-store, private"
    page = client.get("/app")
    assert page.status_code == 200 and b"Your next practice" in page.data
    assert "object-src 'none'" in page.headers["Content-Security-Policy"]
    assert b"telegram-web-app.js" in page.data


def test_dashboard_command_uses_private_web_app_button(harness):
    from test_flows import command

    harness.runtime.config = replace(harness.runtime.config, private_dashboard_url="https://example.com/app")
    command(harness, "/dashboard")
    buttons = harness.telegram.messages[-1][1]
    assert buttons == [[{"text": "Open my private dashboard", "web_app": {"url": "https://example.com/app"}}]]


@pytest.mark.postgres
def test_dashboard_is_personal_and_revocation_removes_access(pg_repo, config):
    bot = Bot(pg_repo, config)
    a, b = bot.join(101), bot.join(102)
    bot.input(101, "/nextweek PRIVATE-A")
    bot.input(102, "/nextweek PRIVATE-B")
    bot.runtime.clock = lambda: datetime.now().astimezone()
    client = create_app(bot.runtime).test_client()
    issued = int(time.time()) + 2
    token_a = signed(101, config.telegram_token, issued)
    response = client.post("/app/data", json={"init_data": token_a})
    assert response.status_code == 200 and response.json["private"]
    assert "PRIVATE-B" not in response.get_data(as_text=True)
    assert (
        client.post("/app/data", json={"init_data": token_a, "learner_id": b.learner_id}).status_code == 403
    )
    token_b = signed(102, config.telegram_token, issued)
    assert client.post("/app/data", json={"init_data": token_b}).status_code == 200
    bot.input(config.owner_id, "/revoke " + a.learner_id)
    assert client.post("/app/data", json={"init_data": token_a}).status_code == 403
    assert client.post("/app/data", json={"init_data": token_b}).status_code == 200
    invitation = bot.invite()
    bot.input(101, "/start " + invitation)
    bot.input(config.owner_id, "/approve " + a.learner_id)
    assert client.post("/app/data", json={"init_data": token_a}).status_code == 403


@pytest.mark.postgres
def test_unapproved_and_unknown_users_cannot_open_private_dashboard(pg_repo, config):
    bot = Bot(pg_repo, config)
    bot.join(101, approve=False)
    bot.runtime.clock = lambda: datetime.now().astimezone()
    client = create_app(bot.runtime).test_client()
    for actor in (101, 999):
        assert (
            client.post("/app/data", json={"init_data": signed(actor, config.telegram_token)}).status_code
            == 403
        )
