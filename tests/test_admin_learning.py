import json
from contextlib import nullcontext
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from test_journey import TOPIC, shared_journey

from skillcoach.admin_auth import AdminDenied
from skillcoach.admin_learning import (
    PAGE_SIZE,
    catalog_topic,
    delivery_view,
    learner_detail,
    lesson_history,
    materials,
    upcoming_view,
)
from skillcoach.catalog import TOPICS
from skillcoach.course_library import VERSION
from skillcoach.lesson_delivery import lesson_id
from skillcoach.models import State
from skillcoach.storage import Repository
from skillcoach.timeutil import IST

NOW = datetime(2026, 9, 29, 22, 30, tzinfo=IST)


def state():
    return State(journey=shared_journey(NOW))


def test_materials_are_complete_public_references_without_lab_secrets(config):
    data = materials(config)
    assert data["courses"]["total"] == 199
    assert len(data["courses"]["modules"]) == 23
    assert len(data["resources"]["items"]) == 24
    assert data["labs"]["items"]
    encoded = json.dumps(data["labs"])
    for forbidden in ("scenario", "options", "explanation", "correct", "answer_keys"):
        assert f'"{forbidden}"' not in encoded
    assert "YOUR_LAB_TOKEN" in encoded
    assert "not independently expert-reviewed" in data["courses"]["notice"]


def test_next_slots_are_ist_based_and_read_only():
    value = state()
    before = value.model_dump()
    result = upcoming_view(value, "active", NOW, labs_enabled=True)
    slots = {slot["kind"]: slot for slot in result["slots"]}
    assert slots["lesson"]["at"] == "2026-09-30T09:00:00+05:30"
    assert slots["lesson"]["topic"]["id"] == TOPIC
    assert slots["quiz"]["at"] == "2026-09-30T18:00:00+05:30"
    assert slots["weekly"]["at"] == "2026-10-03T09:00:00+05:30"
    assert slots["review"]["at"] == "2026-10-04T10:00:00+05:30"
    assert "Conditional" in slots["quiz"]["detail"]
    assert value.model_dump() == before
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize(
    "now,expected",
    [
        (datetime(2026, 10, 2, 8, 59, tzinfo=IST), "2026-10-02T09:00:00+05:30"),
        (datetime(2026, 10, 2, 9, 0, tzinfo=IST), "2026-10-02T09:00:00+05:30"),
        (datetime(2026, 10, 2, 9, 1, tzinfo=IST), "2026-10-05T09:00:00+05:30"),
        (datetime(2026, 10, 4, 23, 59, tzinfo=IST), "2026-10-05T09:00:00+05:30"),
    ],
)
def test_missed_topics_move_to_the_next_weekday_opportunity(now, expected):
    result = upcoming_view(state(), "active", now, labs_enabled=True)
    lesson = next(slot for slot in result["slots"] if slot["kind"] == "lesson")
    assert lesson["at"] == expected


@pytest.mark.parametrize("restriction", ["paused", "revoked", "consent", "plan"])
def test_forecast_never_promises_delivery_without_access_consent_or_plan(restriction):
    value = state()
    membership = "active"
    if restriction == "paused":
        value.paused = True
    elif restriction == "revoked":
        membership = "revoked"
    elif restriction == "consent":
        value.journey.consent_at = None
    else:
        value.journey.active_id = None
    assert upcoming_view(value, membership, NOW, labs_enabled=True)["slots"] == []


def test_prepared_lesson_is_not_advertised_as_a_new_lesson():
    value = state()
    for index, session in enumerate(value.journey.plans["plan-test"].sessions):
        session.lesson_key = f"prepared:{index}"
    result = upcoming_view(value, "active", NOW, labs_enabled=True)
    assert not any(slot["kind"] == "lesson" for slot in result["slots"])
    assert "recovery" in result["status"]


def test_history_has_safe_catalog_topics_versions_and_stable_pagination():
    value = state()
    for index in range(PAGE_SIZE + 3):
        value.lessons[f"private-record:{index}"] = {
            "topic": TOPICS[TOPIC][1] if index else "Private employer project",
            "date": (NOW.date() - timedelta(days=index)).isoformat(),
            "prepared_at": NOW.isoformat(),
            "delivered_at": NOW.isoformat() if index == 1 else None,
            "source": "library",
            "library_version": VERSION,
            "job_id": "Private transport job",
            "personal_content": "Private document",
        }
    before = value.model_dump()
    first, cursor = lesson_history(value, None)
    assert len(first) == PAGE_SIZE and cursor
    second, end = lesson_history(value, cursor)
    assert len(second) == 3 and end is None
    assert len({item["id"] for item in first + second}) == PAGE_SIZE + 3
    assert first[0]["topic"] == {"id": None, "title": "Private/custom topic"}
    assert first[0]["delivered_at"] is None and first[1]["delivered_at"]
    assert first[1]["topic"]["id"] == TOPIC and first[1]["version"] == VERSION
    for secret in ("Private employer", "Private transport", "Private document", "private-record:"):
        assert secret not in json.dumps(first + second)
    assert before == value.model_dump()
    with pytest.raises(AdminDenied):
        lesson_history(value, lesson_id("missing"))


@pytest.mark.parametrize("record", [{}, {"topic": "personal topic"}, {"topic_id": "../../secret"}])
def test_unknown_topics_are_redacted(record):
    assert catalog_topic(record) == {"id": None, "title": "Private/custom topic"}


@pytest.mark.parametrize(
    "counts,status",
    [
        ((4, 4, 0, 0, 0), "Sent to Telegram"),
        ((4, 1, 2, 1, 0), "Partially sent"),
        ((4, 0, 3, 1, 0), "Delivery failed"),
        ((4, 0, 4, 0, 0), "Awaiting delivery"),
        ((4, 0, 0, 0, 4), "Suppressed; not sent"),
        ((0, 0, 0, 0, 0), "No outgoing messages recorded"),
    ],
)
def test_delivery_counts_are_not_mislabelled_as_viewing_or_mastery(counts, status):
    row = dict(zip(("total", "sent", "pending", "failed", "suppressed"), counts))
    row.update(
        sequence=123,
        kind="schedule",
        scheduled_kind="quiz",
        job_status="done",
        created_at=NOW,
        available_at=NOW,
        last_sent_at=NOW if row["sent"] else None,
        media_sent=0,
        body="Private answer",
        payload="private text",
        id="private-job",
    )
    view = delivery_view(row)
    assert view["status"] == status
    assert view["title"] == "Daily quiz" and view["cursor"] == "123"
    assert "private" not in json.dumps(view).lower()
    assert "body" not in view and "payload" not in view


@pytest.mark.parametrize(
    "learner,lessons,deliveries",
    [
        ([], None, None),
        ("u_not valid", None, None),
        ("owner", [], None),
        ("owner", "../x", None),
        ("owner", None, True),
        ("owner", None, "-1"),
        ("owner", None, "9223372036854775808"),
        ("owner", None, {"cursor": 1}),
    ],
)
def test_invalid_cursor_or_learner_fails_before_accessing_storage(learner, lessons, deliveries):
    with pytest.raises(AdminDenied):
        learner_detail(SimpleNamespace(), learner, lessons, deliveries)


def test_admin_material_routes_validate_shapes_and_fail_explicitly(harness, monkeypatch):
    from skillcoach.clients import ExternalError
    from skillcoach.web import create_app

    monkeypatch.setattr("skillcoach.admin.authenticate", lambda *args, **kwargs: ({}, "test"))
    client = create_app(harness.runtime).test_client()
    before = harness.repo.read()
    response = client.post("/admin/materials", json={})
    assert response.status_code == 200 and response.json["courses"]["total"] == 199
    response = client.post("/admin/course", json={"topic": TOPIC, "version": VERSION})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store, private"
    for body in (
        {"topic": [], "version": VERSION},
        {"topic": TOPIC, "version": "../secret"},
        {"topic": TOPIC, "version": VERSION, "learner": "owner"},
    ):
        assert client.post("/admin/course", json=body).status_code == 403
    assert harness.repo.read() == before and not harness.ai.calls

    def unavailable(*args):
        raise ExternalError("course_content_unavailable", retryable=False)

    monkeypatch.setattr("skillcoach.course_library.page", unavailable)
    response = client.post("/admin/course", json={"topic": TOPIC, "version": VERSION})
    assert response.status_code == 503
    assert "unavailable" in response.json["error"]


@pytest.mark.parametrize("path", ["/admin/materials", "/admin/course", "/admin/learner"])
def test_new_views_never_allow_an_unsigned_owner_claim(harness, path):
    from skillcoach.web import create_app

    response = create_app(harness.runtime).test_client().post(path, json={"owner_id": 42})
    assert response.status_code == 403


@pytest.mark.parametrize("readonly", [False, True])
def test_readonly_transaction_is_configured_before_the_first_query(config, readonly):
    commands = []

    class Connection:
        def transaction(self):
            return nullcontext()

        def execute(self, query, *args):
            commands.append(query)

    repo = Repository(config.database_url)
    token = repo._session_connection.set(Connection())
    try:
        with repo.connection(readonly=readonly):
            pass
    finally:
        repo._session_connection.reset(token)
    if readonly:
        assert commands[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
        assert commands[1].startswith("SELECT set_config")
    else:
        assert len(commands) == 1 and commands[0].startswith("SELECT set_config")


@pytest.mark.parametrize("consent", [False, True])
def test_learner_view_only_queries_selected_recipient_and_obeys_consent(config, consent):
    value = state()
    if not consent:
        value.journey.consent_at = None
    calls = []

    class Connection:
        def execute(self, query, params):
            calls.append((query, params))
            return SimpleNamespace(
                fetchone=lambda: {"status": "active", "body": value.model_dump(mode="json")},
                fetchall=lambda: [],
            )

    class Repo:
        def connection(self, *, readonly):
            assert readonly
            return nullcontext(Connection())

    runtime = SimpleNamespace(repo=Repo(), config=config, clock=lambda: NOW)
    response = learner_detail(runtime, "u_abcdef123456", None, "100")
    assert calls[0][1] == ("u_abcdef123456",)
    assert len(calls) == (2 if consent else 1)
    if consent:
        assert calls[1][1] == ("u_abcdef123456", "100", "100", PAGE_SIZE + 1, "u_abcdef123456")
    assert "private goal" not in json.dumps(response)
    assert response["learning"]["shared"] is consent


@pytest.mark.postgres
def test_readonly_snapshot_rejects_writes_without_affecting_later_transactions(pg_repo):
    from psycopg.errors import ReadOnlySqlTransaction

    with pytest.raises(ReadOnlySqlTransaction), pg_repo.connection(readonly=True) as conn:
        assert (
            conn.execute("SHOW transaction_isolation").fetchone()["transaction_isolation"]
            == "repeatable read"
        )
        conn.execute("UPDATE coach_state SET revision=revision+1 WHERE learner_id='owner'")
    with pg_repo.connection() as conn:
        assert conn.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"] == "off"
