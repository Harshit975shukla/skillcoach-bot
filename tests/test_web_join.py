"""Web invitations: email verification, owner approval and the refusals around them."""

import re
import threading
from datetime import timedelta
from types import SimpleNamespace

import pytest
from psycopg.types.json import Jsonb
from test_admin import confirm as confirm_action
from test_admin import preview as preview_action
from test_web_channel import ORIGIN, build_web, post, sign_in, web_config

from skillcoach import web_join
from skillcoach.web import create_app
from skillcoach.web_channel import WebCodeIncorrect, WebDenied, digest, keyed
from skillcoach.web_join import JOIN_COOKIE, access_email, clean_name, start_join, verify_join


def test_names_are_trimmed_and_control_characters_refused():
    assert clean_name("  Asha \n  Rao ") == "Asha Rao"
    for raw in ("", "   ", "x" * 61, "Asha\u202eoaR", "Asha\x00", None, 7):
        assert clean_name(raw) is None


def test_join_routes_and_public_requests_are_web_only(harness):
    client = create_app(harness.runtime).test_client()
    body = {"invite": "a" * 32, "name": "Asha", "email": "a@example.test"}
    response = client.post("/web/join/start", base_url=ORIGIN, json=body, headers={"Origin": ORIGIN})
    assert response.status_code == 404 and response.json["enabled"] is False
    harness.runtime.config = web_config(harness.runtime.config)
    assert client.get("/join/config", base_url=ORIGIN).json["available"] is False
    # Malformed requests are refused before anything is stored.
    for invite, name, email, message in (
        ("short", "Asha", "a@example.test", "not valid"),
        ("a" * 32, "", "a@example.test", "Enter your name"),
        ("a" * 32, "Asha", "not-an-address", "valid email"),
    ):
        with pytest.raises(WebDenied, match=message):
            start_join(harness.runtime, invite, name, email)


# PostgreSQL ----------------------------------------------------------------------------------


@pytest.fixture
def web(pg_repo, config, monkeypatch):
    return build_web(pg_repo, config, monkeypatch)


def mail(web, to, subject):
    return [m for m in web.email.sent if m["to"] == to and m["subject"] == subject]


def code_for(web, to):
    text = mail(web, to, "Your SkillCoach verification code")[-1]["text"]
    return re.search(r"verification code is ([0-9]{6})", text).group(1)


def owner_admin(web):
    admin = SimpleNamespace(bot=web.bot, client=web.app.test_client(), csrf=None, clock=web.clock)
    assert post(admin, "/admin/login/pin/start", client=admin.client, csrf=False).status_code == 200
    pin = re.search(
        r"PIN: ([0-9]{4})", mail(web, "owner@example.test", "Your SkillCoach admin PIN")[-1]["text"]
    )
    verified = post(admin, "/admin/login/pin/verify", {"pin": pin.group(1)}, client=admin.client, csrf=False)
    assert verified.status_code == 200, verified.json
    admin.csrf = verified.json["csrf"]
    return admin


def act(admin, action, target="owner", arguments=None):
    pending = preview_action(admin, action, target, arguments if arguments is not None else {})
    assert pending.status_code == 200, pending.json
    result = confirm_action(admin, pending.json)
    assert result.status_code == 200, result.json
    return pending.json, result.json


def invite(web, admin, label="Friend"):
    _, result = act(admin, "invite", "owner", {"label": label})
    text = "\n".join(result["messages"])
    assert "t.me" not in text and "confirm their email" in text
    return re.search(r"https://coach\.example\.test/web#invite=([A-Za-z0-9_-]{32})", text).group(1)


def start(web, token, email, client, name="Asha Rao"):
    return post(
        web, "/web/join/start", {"invite": token, "name": name, "email": email}, client=client, csrf=False
    )


def verify(web, code, client):
    return post(web, "/web/join/verify", {"code": code}, client=client, csrf=False)


def learner_by_email(web, email):
    with web.bot.repo.connection() as conn:
        return conn.execute("SELECT * FROM learners WHERE email=%s", (email,)).fetchone()


def invitation(web, token):
    with web.bot.repo.connection() as conn:
        return conn.execute("SELECT * FROM invitations WHERE token_hash=%s", (digest(token),)).fetchone()


def later(web, seconds=61):
    web.clock.now += timedelta(seconds=seconds)


@pytest.mark.postgres
def test_invited_person_verifies_email_then_owner_approves_once(web):
    admin = owner_admin(web)
    token = invite(web, admin, "Asha")
    browser, other = web.app.test_client(), web.app.test_client()
    address = "asha.new+cloud@example.test"
    started = start(web, token, " Asha.New+cloud@Example.TEST ", browser, name="  Asha \n Rao ")
    assert started.status_code == 200 and set(started.json) == {"pending", "expires_at", "resend_at"}
    cookie = [v for v in started.headers.getlist("Set-Cookie") if v.startswith(JOIN_COOKIE)][0]
    for flag in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/", "Max-Age=600"):
        assert flag in cookie
    code = code_for(web, address)  # Plus tags are kept: the address is only trimmed and lowercased.
    with web.bot.repo.connection() as conn:
        # Typing an address creates nothing; the invitation stays open until the code is confirmed.
        assert (
            conn.execute("SELECT count(*) AS n FROM learners WHERE email=%s", (address,)).fetchone()["n"] == 0
        )
        row = conn.execute("SELECT * FROM web_joins").fetchone()
        assert code not in (row["code_hash"], row["verifier_hash"]) and row["status"] == "pending"
    assert invitation(web, token)["status"] == "open"
    wrong = "000000" if code != "000000" else "111111"
    failed = verify(web, wrong, browser)
    assert failed.status_code == 400 and "4 attempts remaining" in failed.json["error"]
    assert verify(web, code, other).status_code == 403  # The code works only in the requesting browser.
    assert (
        post(
            web, "/web/join/verify", {"code": code}, client=browser, csrf=False, origin="https://evil.invalid"
        ).status_code
        == 403
    )
    verifier = browser.get_cookie(JOIN_COOKIE).value
    done = verify(web, code, browser)
    assert done.status_code == 200 and done.json == {"requested": True}
    assert browser.get_cookie(JOIN_COOKIE) is None
    member = learner_by_email(web, address)
    assert member["status"] == "pending" and member["telegram_id"] is None
    assert member["display_name"] == "Asha Rao"
    claimed = invitation(web, token)
    assert (claimed["status"], claimed["claimed_by"]) == ("claimed", member["id"])
    owner_mail = mail(web, "owner@example.test", "New SkillCoach access request")
    assert len(owner_mail) == 1 and "a•••@example.test" in owner_mail[0]["text"]
    assert address not in owner_mail[0]["text"] and member["id"] in owner_mail[0]["text"]
    # Replays create nothing, from the same browser or with the old cookie restored.
    browser.set_cookie(JOIN_COOKIE, verifier)
    assert verify(web, code, browser).status_code == 403
    with web.bot.repo.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM learners WHERE status='pending'").fetchone()["n"] == 1
    # A pending learner cannot sign in: the usual answer, but no code is sent.
    sent = len(web.email.sent)
    assert post(web, "/web/login/start", {"email": address}, client=web.app.test_client()).status_code == 200
    assert len(web.email.sent) == sent
    # Approval emails the verified address once; repeating the action sends nothing more.
    approval, result = act(admin, "approve", member["id"])
    assert result["state"] == "handled"
    approved = mail(web, address, "Your SkillCoach access is approved")
    assert len(approved) == 1 and "https://coach.example.test/web" in approved[0]["text"]
    assert confirm_action(admin, approval).json["duplicate"] is True
    assert preview_action(admin, "approve", member["id"], {}).status_code == 409
    assert len(mail(web, address, "Your SkillCoach access is approved")) == 1
    # The approved learner signs in with the verified address and finds the setup button.
    learner = web.app.test_client()
    later(web)
    sign_in(web, address, client=learner)
    messages = post(web, "/web/feed", client=learner).json["messages"]
    setup = [b for m in messages for line in m["buttons"] for b in line if b["text"] == "Set up my learning"]
    assert setup and setup[0]["data"] == "onboard:start"


@pytest.mark.postgres
def test_join_refuses_existing_access_owner_address_revoked_and_expired_links(web):
    admin = owner_admin(web)
    token = invite(web, admin)
    browser = web.app.test_client()
    with web.bot.repo.connection() as conn:
        before = conn.execute("SELECT * FROM learners WHERE id=%s", (web.learner.learner_id,)).fetchone()
    # An address that already has access is never reassigned or re-pended, and the link stays usable.
    assert start(web, token, "learner@example.test", browser).status_code == 200
    refused = verify(web, code_for(web, "learner@example.test"), browser)
    assert refused.status_code == 403 and "already has SkillCoach access" in refused.json["error"]
    with web.bot.repo.connection() as conn:
        assert (
            conn.execute("SELECT * FROM learners WHERE id=%s", (web.learner.learner_id,)).fetchone() == before
        )
    assert invitation(web, token)["status"] == "open"
    later(web)
    assert start(web, token, "owner@example.test", browser).status_code == 200
    refused = verify(web, code_for(web, "owner@example.test"), browser)
    assert refused.status_code == 403 and "coach's own sign-in" in refused.json["error"]
    # Revoking the invitation while its code is in flight stops the join.
    later(web)
    assert start(web, token, "late@example.test", browser).status_code == 200
    act(admin, "revokeinvite", "owner", {"invite_id": invitation(web, token)["id"]})
    refused = verify(web, code_for(web, "late@example.test"), browser)
    assert refused.status_code == 403 and "not valid" in refused.json["error"]
    assert start(web, token, "late@example.test", web.app.test_client()).status_code == 403
    # An invitation that expires before the code is confirmed cannot be redeemed either.
    expiring = invite(web, admin, "Expiring")
    later(web)
    assert start(web, expiring, "slow@example.test", browser).status_code == 200
    web.clock.now += timedelta(hours=25)
    assert verify(web, code_for(web, "slow@example.test"), browser).status_code == 403
    assert (
        learner_by_email(web, "late@example.test") is None
        and learner_by_email(web, "slow@example.test") is None
    )


@pytest.mark.postgres
def test_a_new_address_replaces_the_old_code_and_concurrent_confirmations_claim_once(web):
    admin = owner_admin(web)
    token = invite(web, admin)
    browser = web.app.test_client()
    assert start(web, token, "first@example.test", browser).status_code == 200
    first_code, first_verifier = code_for(web, "first@example.test"), browser.get_cookie(JOIN_COOKIE).value
    later(web)
    assert start(web, token, "second@example.test", browser).status_code == 200
    # The first address's code no longer counts, in this browser or with its own cookie.
    assert verify(web, first_code, browser).status_code in (400, 403)
    stale = web.app.test_client()
    stale.set_cookie(JOIN_COOKIE, first_verifier)
    assert verify(web, first_code, stale).status_code == 403
    # Two simultaneous confirmations of the same request create one learner.
    verifier, code = browser.get_cookie(JOIN_COOKIE).value, code_for(web, "second@example.test")
    outcomes, barrier = [], threading.Barrier(2)

    def confirm_once():
        barrier.wait()
        try:
            outcomes.append(verify_join(web.bot.runtime, verifier, code))
        except (WebDenied, WebCodeIncorrect) as exc:
            outcomes.append(type(exc).__name__)

    threads = [threading.Thread(target=confirm_once) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(map(str, outcomes)) == sorted(["WebDenied", str({"requested": True})])
    # Two different confirmed requests racing for one invitation: only one can claim it.
    racing = invite(web, admin, "Race")
    with web.bot.repo.connection() as conn:
        invite_id = conn.execute(
            "SELECT id FROM invitations WHERE token_hash=%s", (digest(racing),)
        ).fetchone()["id"]
        rows = []
        for index in range(2):
            ident, secret = f"race-{index}", f"{index}" * 43
            conn.execute(
                "INSERT INTO web_joins(id,invite_id,email,email_hash,display_name,verifier_hash,code_hash,"
                "notified,requested_at,expires_at) VALUES (%s,%s,%s,%s,'Racer',%s,%s,true,%s,%s)",
                (
                    ident,
                    invite_id,
                    f"racer{index}@example.test",
                    keyed(web.bot.runtime.config, "email", f"racer{index}@example.test"),
                    digest(secret),
                    keyed(web.bot.runtime.config, "join-code", f"{ident}:123456"),
                    web.clock.now,
                    web.clock.now + timedelta(minutes=10),
                ),
            )
            rows.append(secret)
    outcomes, barrier = [], threading.Barrier(2)

    def race(secret):
        barrier.wait()
        try:
            outcomes.append(verify_join(web.bot.runtime, secret, "123456")["requested"])
        except WebDenied as exc:
            outcomes.append(str(exc))

    threads = [threading.Thread(target=race, args=(secret,)) for secret in rows]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count(True) == 1 and any("not valid" in str(o) for o in outcomes)
    with web.bot.repo.connection() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM learners WHERE email LIKE 'racer%%'").fetchone()["n"] == 1
        )


@pytest.mark.postgres
def test_rejected_learner_rejoins_with_history_and_decisions_reach_only_the_verified_address(web):
    admin = owner_admin(web)
    browser = web.app.test_client()
    address = "returning@example.test"
    assert start(web, invite(web, admin), address, browser).status_code == 200
    assert verify(web, code_for(web, address), browser).status_code == 200
    first = learner_by_email(web, address)
    act(admin, "reject", first["id"])
    assert len(mail(web, address, "Your SkillCoach access request")) == 1
    # A new invitation re-opens the same learner record; history and identity are kept.
    later(web)
    assert start(web, invite(web, admin, "Second"), address, browser).status_code == 200
    assert verify(web, code_for(web, address), browser).status_code == 200
    again = learner_by_email(web, address)
    assert (
        again["id"] == first["id"]
        and again["status"] == "pending"
        and again["generation"] > first["generation"]
    )
    # A decision email is only delivered while the verified address is still the learner's.
    with web.bot.repo.connection() as conn:
        member = conn.execute("SELECT * FROM learners WHERE id=%s", (again["id"],)).fetchone()
        conn.execute(
            "INSERT INTO jobs(id,payload,learner_id,access_generation,status) VALUES (%s,%s,%s,%s,'done')",
            ("admin:pinned", Jsonb({"type": "access_admin"}), member["id"], member["generation"]),
        )
        access_email(conn, "admin:pinned", member, "rejected", web.bot.runtime.config)
        conn.execute("UPDATE learners SET email='someone-else@example.test' WHERE id=%s", (member["id"],))
    web.bot.runtime.recover(media=False)
    with web.bot.repo.connection() as conn:
        status = conn.execute("SELECT status FROM outbox WHERE id='admin:pinned:access-email'").fetchone()[
            "status"
        ]
    assert status == "suppressed" and not mail(
        web, "someone-else@example.test", "Your SkillCoach access request"
    )
    assert web_join.ACCESS_EMAILS["active"][0] == "Your SkillCoach access is approved"
