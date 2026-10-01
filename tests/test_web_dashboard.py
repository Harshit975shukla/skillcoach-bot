"""The private dashboard in web + email mode. The signed-in /web session is the only identity: its
cookie, CSRF token and same-origin check. A learner ID in the body or address is never accepted,
signed Telegram launch data is not needed, and the page served to web learners never loads
Telegram's script. Every /app route is covered: data, course, lesson, documents, labs, exercises."""

import io
import json
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from test_flows import PROFILE, RESUME
from test_journey import shared_journey
from test_labs import FakeChecker
from test_remediations import pdf_bytes
from test_web_channel import ORIGIN, build_web, sign_in, web_config
from test_web_join import act, owner_admin

from skillcoach.catalog import TOPICS
from skillcoach.models import LabAssignment, Profile, Task
from skillcoach.timeutil import IST
from skillcoach.web import create_app
from skillcoach.web_channel import SESSION_SECONDS, WEB_COOKIE

LESSON = "0123456789abcdef0123"
TOPIC = next(iter(TOPICS))
PRIVATE = (("/app/data", {}), ("/app/course", {"topic": TOPIC}), ("/app/lesson", {"lesson": LESSON}))
LAB_LINK = "https://github.com/learner/labs"


def task_id(user):
    return f"{user:020x}"[-20:]


def test_web_dashboard_page_is_web_only_and_never_loads_telegram(harness):
    client = create_app(harness.runtime).test_client()
    assert client.get("/web/dashboard", base_url=ORIGIN).status_code == 404
    # Telegram mode keeps requiring launch data: a body without it is refused.
    for path, body in PRIVATE:
        assert client.post(path, base_url=ORIGIN, json=body, headers={"Origin": ORIGIN}).status_code == 403
    mini_app = client.get("/app", base_url=ORIGIN)
    assert b"https://telegram.org/js/telegram-web-app.js" in mini_app.data
    assert "script-src 'self' https://telegram.org;" in mini_app.headers["Content-Security-Policy"]
    harness.runtime.config = web_config(harness.runtime.config)
    page = client.get("/web/dashboard", base_url=ORIGIN)
    assert page.status_code == 200 and page.mimetype == "text/html"
    assert b"telegram.org" not in page.data
    assert b'src="/static/dashboard.js"' in page.data and b'id="chat-link"' in page.data
    policy = page.headers["Content-Security-Policy"]
    assert "script-src 'self';" in policy and "telegram.org" not in policy
    assert "frame-ancestors 'none'" in policy and page.headers["Cache-Control"] == "no-store, private"
    assert "telegram.org" not in client.get("/web", base_url=ORIGIN).headers["Content-Security-Policy"]
    # Without a signed-in browser nothing private opens, and no learner can be named instead.
    for path, body in (*PRIVATE, ("/app/data", {"learner": "owner"})):
        assert client.post(path, base_url=ORIGIN, json=body, headers={"Origin": ORIGIN}).status_code == 403


@pytest.fixture
def web(pg_repo, config, monkeypatch):
    """The owner and two learners, each signing in with their own address. Both learners have a
    profile, a lab assignment and an exercise of their own."""
    web = build_web(pg_repo, config, monkeypatch)
    with pg_repo.connection() as conn:
        conn.execute("UPDATE learners SET email='second@example.test' WHERE id=%s", (web.silent.learner_id,))
    today = datetime.now(IST).date()

    def seed(name, user=None):
        def apply(state):
            state.profile = Profile(**{**PROFILE, "name": name})
            state.journey = shared_journey(datetime.now(IST))
            if user:
                state.labs[f"lab-{user}"] = LabAssignment(
                    id=f"lab-{user}",
                    lab_id="iam-least-privilege",
                    required=True,
                    token=f"SC-{user}A-BCDE",
                    assigned_date=today,
                )
                state.tasks[task_id(user)] = Task(
                    id=task_id(user),
                    origin=f"lesson-{user}:0",
                    title=f"Exercise {user}",
                    skill="iam",
                    detail="Steps",
                    assigned_date=today,
                )

        return apply

    web.bot.save(web.bot.repo, seed("Owner Person"))
    web.bot.save(web.learner, seed("Learner A", 101))
    web.bot.save(web.silent, seed("Learner B", 102))
    web.bot.runtime.labs = FakeChecker()
    return web


def browser(web, email):
    """A separate browser signed in as `email`; returns its client and CSRF token."""
    client = web.app.test_client()
    csrf = sign_in(web, email, client=client).json["csrf"]
    web.clock.now += timedelta(seconds=61)  # The next code for an address may be sent after a minute.
    return client, csrf


def private(client, csrf, path="/app/data", body=None, *, origin=ORIGIN, query="", headers=None):
    sent = {"Origin": origin} if origin else {}
    if csrf:
        sent["X-CSRF-Token"] = csrf
    return client.post(
        path + query, base_url=ORIGIN, json={} if body is None else body, headers={**sent, **(headers or {})}
    )


def upload(client, csrf, *, raw=None, name="resume.txt", headers=None, query=""):
    return client.post(
        "/app/documents/preview" + query,
        base_url=ORIGIN,
        headers=headers if headers is not None else {"Origin": ORIGIN, "X-CSRF-Token": csrf},
        data={
            "request_id": str(uuid4()),
            "kind": "resume",
            "file": (io.BytesIO(raw or RESUME.encode()), name),
        },
    )


def confirm(client, csrf, preview, choice="keep"):
    return private(
        client,
        csrf,
        "/app/documents/confirm",
        {"request_id": preview["request_id"], "confirmation": preview["confirmation"], "choice": choice},
    )


def lab(assignment="lab-101", ident=None):
    return {"request_id": ident or str(uuid4()), "assignment_id": assignment, "url": LAB_LINK}


def tap(task, ident=None, action="done"):
    return {"request_id": ident or str(uuid4()), "task_id": task, "action": action}


def every_route(client, csrf):
    """Status codes from every private dashboard route for this browser, as learner A."""
    statuses = [private(client, csrf, path, body).status_code for path, body in PRIVATE]
    statuses.append(upload(client, csrf).status_code)
    for path, body in (
        ("/app/documents/confirm", {"request_id": str(uuid4()), "confirmation": "x" * 64, "choice": "keep"}),
        ("/app/labs/submit", lab()),
        ("/app/exercise", tap(task_id(101))),
    ):
        statuses.append(private(client, csrf, path, body).status_code)
    return statuses


@pytest.mark.postgres
def test_each_browser_sees_only_its_own_learner_and_no_request_can_name_another(web):
    owner, owner_csrf = browser(web, "owner@example.test")
    first, first_csrf = browser(web, "learner@example.test")
    second, second_csrf = browser(web, "second@example.test")
    for client, csrf, name in (
        (owner, owner_csrf, "Owner Person"),
        (first, first_csrf, "Learner A"),
        (second, second_csrf, "Learner B"),
    ):
        data = private(client, csrf).json
        assert data["profile"]["name"] == name
        assert data["web"] is True and data["bot_url"] is None and data["private"] is True
        assert data["document_csrf"] == csrf
    # Identity never comes from the request: extra fields, forged launch data, URL parameters,
    # a missing or another browser's token, a foreign origin or a token without its cookie all fail.
    for body in (
        {"learner": "owner"},
        {"learner_id": web.silent.learner_id},
        {"init_data": "forged"},
        {"init_data": "forged", "learner": "owner"},
    ):
        assert private(first, first_csrf, body=body).status_code == 403
    assert private(first, first_csrf, query="?learner=owner").status_code == 403
    assert private(first, None).status_code == 403
    assert private(first, second_csrf).status_code == 403
    assert private(first, first_csrf, origin="https://evil.invalid").status_code == 403
    assert private(web.app.test_client(), first_csrf).status_code == 403
    # The course library and lesson reader use the same identity.
    course = private(second, second_csrf, "/app/course", {"topic": TOPIC})
    assert course.status_code == 200 and course.json["private"] is True
    assert (
        private(second, second_csrf, "/app/course", {"topic": TOPIC, "learner": "owner"}).status_code == 403
    )
    assert private(second, second_csrf, "/app/course", {"topic": "../../x"}).status_code == 404
    assert private(second, None, "/app/course", {"topic": TOPIC}).status_code == 403
    assert private(second, second_csrf, "/app/lesson", {"lesson": LESSON}).status_code == 404
    assert (
        private(second, second_csrf, "/app/lesson", {"lesson": LESSON, "learner": "owner"}).status_code == 403
    )
    # Opening counts once per browser session, like once per Telegram launch.
    assert private(first, first_csrf).status_code == 200
    with web.bot.repo.connection() as conn:
        opened = conn.execute(
            "SELECT learner_id, sum(count) AS n FROM usage_daily WHERE event='dashboard_open' GROUP BY learner_id"
        ).fetchall()
        sessions = conn.execute("SELECT auth_hash FROM dashboard_sessions").fetchall()
    assert {row["learner_id"]: row["n"] for row in opened} == {
        "owner": 1,
        web.learner.learner_id: 1,
        web.silent.learner_id: 1,
    }
    assert len(sessions) == 3 and all(row["auth_hash"].startswith("web:") for row in sessions)
    assert not any(token in row["auth_hash"] for row in sessions for token in (owner_csrf, first_csrf))


@pytest.mark.postgres
def test_labs_and_exercises_through_the_web_session_reach_only_the_signed_in_learner(web):
    client, csrf = browser(web, "learner@example.test")
    data = private(client, csrf).json
    assert [item["id"] for item in data["labs"]["items"]] == ["lab-101"]
    assert data["labs"]["items"][0]["token"] == "SC-101A-BCDE" and "SC-102A-BCDE" not in json.dumps(data)
    other = web.silent.read()[1]
    submission = lab(ident=str(uuid4()))
    assert private(client, csrf, "/app/labs/submit", submission).json == {"queued": True, "duplicate": False}
    assert web.learner.read()[1].labs["lab-101"].status == "verified"
    assert web.bot.runtime.labs.calls[0][2] == "SC-101A-BCDE"
    assert private(client, csrf, "/app/labs/submit", submission).json == {"queued": True, "duplicate": True}
    exercise = tap(task_id(101), ident=str(uuid4()))
    assert private(client, csrf, "/app/exercise", exercise).json == {"queued": True, "duplicate": False}
    assert web.learner.read()[1].tasks[task_id(101)].status == "done"
    assert private(client, csrf, "/app/exercise", exercise).json == {"queued": True, "duplicate": True}
    # Another learner's lab or exercise cannot be reached from this session.
    assert private(client, csrf, "/app/labs/submit", lab("lab-102")).status_code == 409
    assert private(client, csrf, "/app/exercise", tap(task_id(102))).status_code == 409
    # A learner is never named in a request, and the session's token, origin and cookie are required.
    for path, body in (("/app/labs/submit", lab("lab-102")), ("/app/exercise", tap(task_id(102)))):
        assert private(client, csrf, path, {**body, "learner": web.silent.learner_id}).status_code == 409
        assert private(client, csrf, path, body, query="?learner=" + web.silent.learner_id).status_code == 403
        assert private(client, None, path, body).status_code == 403
        assert private(client, csrf, path, body, origin="https://evil.invalid").status_code == 403
        assert private(web.app.test_client(), csrf, path, body).status_code == 403
        assert (
            private(client, csrf, path, body, headers={"X-Telegram-Init-Data": "forged"}).status_code == 403
        )
    assert web.silent.read()[1] == other
    assert len(web.bot.runtime.labs.calls) == 1


@pytest.mark.postgres
def test_dashboard_access_ends_with_logout_expiry_address_change_and_revocation(web):
    learner = web.learner.learner_id
    before = web.learner.read()[1]
    # Signing out ends the session itself, not just the cookie in this browser.
    client, csrf = browser(web, "learner@example.test")
    token = client.get_cookie(WEB_COOKIE).value
    assert private(client, csrf).status_code == 200
    assert private(client, csrf, "/web/logout").status_code == 200
    replay = web.app.test_client()
    replay.set_cookie(WEB_COOKIE, token, domain="localhost")
    assert set(every_route(replay, csrf)) == {403}
    # Expiry.
    client, csrf = browser(web, "learner@example.test")
    assert private(client, csrf).status_code == 200
    web.clock.now += timedelta(seconds=SESSION_SECONDS + 1)
    assert set(every_route(client, csrf)) == {403}
    # A changed sign-in address ends the session, including for a preview made before the change.
    client, csrf = browser(web, "learner@example.test")
    preview = upload(client, csrf)
    assert preview.status_code == 200, preview.json
    with web.bot.repo.connection() as conn:
        conn.execute("UPDATE learners SET email='moved@example.test' WHERE id=%s", (learner,))
    assert set(every_route(client, csrf)) == {403}
    assert confirm(client, csrf, preview.json).status_code == 403
    with web.bot.repo.connection() as conn:
        conn.execute("UPDATE learners SET email='learner@example.test' WHERE id=%s", (learner,))
    # Revocation by the owner ends every private route at once.
    client, csrf = browser(web, "learner@example.test")
    preview = upload(client, csrf)
    assert preview.status_code == 200, preview.json
    act(owner_admin(web), "revoke", learner)
    assert set(every_route(client, csrf)) == {403}
    assert confirm(client, csrf, preview.json).status_code == 403
    after = web.learner.read()[1]
    assert after.labs == before.labs and after.tasks == before.tasks
    assert after.profile == before.profile
    assert not web.bot.runtime.labs.calls


@pytest.mark.postgres
def test_document_preview_confirm_and_cancel_through_the_web_session_stay_private(web):
    others = {"second": web.silent.read()[1].profile, "owner": web.bot.repo.read()[1].profile}
    client, csrf = browser(web, "learner@example.test")
    assert private(client, csrf).json["documents"]["can_update"] is True
    for headers in (
        {"Origin": ORIGIN},
        {"Origin": "https://evil.invalid", "X-CSRF-Token": csrf},
        {"Origin": ORIGIN, "X-CSRF-Token": "bad"},
        {"Origin": ORIGIN, "X-CSRF-Token": csrf, "X-Telegram-Init-Data": "forged"},
    ):
        assert upload(client, csrf, headers=headers).status_code == 403
    assert upload(client, csrf, query="?learner=owner").status_code == 403
    first = upload(client, csrf)
    assert first.status_code == 200 and RESUME not in first.text
    # Neither another browser of the same learner nor another learner can confirm this preview.
    other, other_csrf = browser(web, "learner@example.test")
    second, second_csrf = browser(web, "second@example.test")
    assert confirm(other, other_csrf, first.json).status_code == 409
    assert confirm(second, second_csrf, first.json).status_code == 409
    assert confirm(client, csrf, first.json).json["queued"] is True
    assert web.learner.read()[1].profile.resume_text == RESUME.strip()
    assert confirm(client, csrf, first.json).json["duplicate"] is True
    # A real PDF preview reports only its size; cancelling discards the parsed text and changes nothing.
    pdf = upload(client, csrf, raw=pdf_bytes(), name="private-resume.pdf")
    assert pdf.status_code == 200, pdf.json
    assert set(pdf.json) == {
        "request_id",
        "confirmation",
        "characters",
        "kind",
        "expires_at",
        "can_revise",
        "status",
    }
    assert (
        pdf.json["characters"] > 0 and "Synthetic resume" not in pdf.text and "private-resume" not in pdf.text
    )
    assert confirm(second, second_csrf, pdf.json, "cancel").status_code == 409
    assert confirm(client, csrf, pdf.json, "cancel").json == {"cancelled": True}
    assert confirm(client, csrf, pdf.json).status_code == 409
    with web.bot.repo.connection() as conn:
        rows = {
            row["id"]: row
            for row in conn.execute(
                "SELECT id, learner_id, auth_hash, status, text FROM learner_document_requests"
            ).fetchall()
        }
    assert (
        rows[pdf.json["request_id"]]["status"] == "cancelled" and rows[pdf.json["request_id"]]["text"] == ""
    )
    assert {row["learner_id"] for row in rows.values()} == {web.learner.learner_id}
    assert all(row["auth_hash"].startswith("web:") and csrf not in row["auth_hash"] for row in rows.values())
    assert web.learner.read()[1].profile.resume_text == RESUME.strip()
    # Nobody else's documents change.
    assert {"second": web.silent.read()[1].profile, "owner": web.bot.repo.read()[1].profile} == others
