import copy
import os
import re
from contextlib import nullcontext
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from skillcoach.clients import ExternalError
from skillcoach.config import Config
from skillcoach.models import State
from skillcoach.runtime import Runtime
from skillcoach.storage import Repository
from skillcoach.timeutil import IST


@pytest.fixture(autouse=True)
def block_external_http(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must not use live HTTP APIs")

    monkeypatch.setattr("requests.Session.request", forbidden)
    # The transport choke point also covers sessions that bypass Session.request (lab checks).
    monkeypatch.setattr("requests.adapters.HTTPAdapter.send", forbidden)


@pytest.fixture
def config():
    return Config("postgresql://test-only", "fake-token", 42, "a" * 32)


class FakeAI:
    def __init__(self):
        self.responses = []
        self.calls = []

    def structured(self, prompt, model, budget, validate=None):
        self.calls.append((prompt, model.__name__))
        if not self.responses:
            raise AssertionError("Unexpected AI invocation: " + model.__name__)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        result = model.model_validate(response)
        if validate:
            validate(result)
        return result


class FakeTelegram:
    def __init__(self):
        self.messages = []
        self.acks = []
        self.fail = False
        self.chat_messages = {}
        self.silent = []

    def for_chat(self, chat_id):
        parent = self

        class Recipient:
            def send(self, text, budget, buttons=None, *, parse_mode=None, silent=False):
                if parent.fail:
                    raise ExternalError("fake_telegram_failure")
                parent.chat_messages.setdefault(chat_id, []).append((text, buttons))
                parent.silent.append(silent)

        return Recipient()

    def send(self, text, budget, buttons=None, *, parse_mode=None, silent=False):
        if self.fail:
            raise ExternalError("fake_telegram_failure")
        self.messages.append((text, buttons))
        self.silent.append(silent)

    def acknowledge(self, callback, budget):
        self.acks.append(callback)


class FakePublisher:
    def __init__(self):
        self.documents = []
        self.fail = False

    def prepare(self, budget):
        return {"sha": "base"}

    def publish(self, document, budget, base):
        if self.fail:
            raise ExternalError("fake_publish_failure")
        self.documents.append(document)


class MemoryRepository:
    """Fast test double only. Production always uses Repository/PostgreSQL."""

    def __init__(self):
        self.state = State()
        self.revision = 0
        self.jobs = {}
        self.outbox = {}
        self.cache_data = {}
        self.displayed = None
        self.leases = {}
        self.answer_keys = set()
        self.is_owner = True
        self.learner_id = "owner"
        self.owner_id = 42
        self.ai_reservations = []

    def for_learner(self, learner_id):
        assert learner_id == "owner", "Use real PostgreSQL tests for multi-learner persistence"
        return self

    def session(self):
        return nullcontext()

    def member(self):
        return {"id": "owner", "status": "active", "generation": 1}

    def active_learners(self):
        return ["owner"]

    def accept_update(self, update_id, payload, config):
        if payload["actor_id"] != config.owner_id:
            return "invite_required"
        body = {k: v for k, v in payload.items() if k not in ("actor_id", "display_name")}
        return "queued" if self.enqueue(f"telegram:{update_id}", body) else "duplicate"

    def reserve_ai(self, job, operation, local_date, limit):
        if sum(day == local_date for _, _, day in self.ai_reservations) >= limit:
            raise ExternalError("daily_ai_budget_exhausted", retryable=False)
        self.ai_reservations.append((job, operation, local_date))

    def enqueue(self, key, payload, *, available_at=None):
        if key in self.jobs:
            return False
        payload = copy.deepcopy(payload)
        if payload["type"] == "telegram":
            payload["target"] = copy.deepcopy(self.displayed)
        self.jobs[key] = {"id": key, "payload": payload, "status": "pending", "available_at": available_at}
        return True

    def read(self):
        return self.revision, self.state.model_copy(deep=True)

    def acquire(self, name, seconds):
        if name in self.leases:
            return None
        self.leases[name] = "token"
        return "token"

    def release(self, name, token):
        self.leases.pop(name, None)

    def next_job(self, token, *, proposal_for=None, document_job=None):
        pending = [j for j in self.jobs.values() if j["status"] == "pending"]
        controls = [j for j in pending if j["payload"].get("text") in ("/pause", "/cancel", "/retry")]
        job = next(iter(controls or pending), None)
        if document_job is not None and (
            not job or job["id"] != document_job or job["payload"].get("type") not in ("document", "lab")
        ):
            return None
        if proposal_for is not None and (
            not job
            or job["id"] != proposal_for + ":next"
            or job["payload"].get("type") != "journey"
            or job["payload"].get("action") != "propose"
        ):
            return None
        if job:
            job["status"] = "running"
        return job

    def cached(self, job, operation):
        return copy.deepcopy(self.cache_data.get((job, operation)))

    def lesson_job(self, key):
        return next(
            (row["job_id"] for row in self.outbox.values() if row["body"].get("lesson_key") == key), None
        )

    def cache(self, job, operation, body, token):
        self.cache_data.setdefault((job, operation), copy.deepcopy(body))

    def finish(self, job, token, revision, state, messages, answers, control=None):
        assert revision == self.revision
        assert not self.answer_keys.intersection(answers)
        self.answer_keys.update(answers)
        self.state = state.model_copy(deep=True)
        self.revision += 1
        for index, body in enumerate(messages):
            ident = f"{job}:{index}"
            self.outbox.setdefault(ident, {"id": ident, "job_id": job, "body": body, "status": "pending"})
        if isinstance(control, dict):
            self.enqueue(job + ":next", control)
        elif control == "retry":
            for row in [*self.jobs.values(), *self.outbox.values()]:
                if row["status"] == "failed":
                    row["status"] = "pending"
        elif control == "pause":
            for row in self.outbox.values():
                if row["body"].get("scheduled") and row["status"] in ("failed", "pending"):
                    row["status"] = "suppressed"
            for row in self.jobs.values():
                if row["payload"]["type"] == "schedule" and row["status"] in ("failed", "pending"):
                    row["status"] = "cancelled"
        elif control == "cancel":
            failed_groups = {row["job_id"] for row in self.outbox.values() if row["status"] == "failed"}
            for row in self.jobs.values():
                if row["status"] in ("pending", "running", "failed") and row["id"] != job:
                    row["status"] = "cancelled"
            for row in self.outbox.values():
                if row["status"] in ("failed", "pending") and (
                    row["body"].get("target")
                    or self.jobs[row["job_id"]]["status"] == "cancelled"
                    or row["job_id"] in failed_groups
                ):
                    row["status"] = "suppressed"
        self.jobs[job]["status"] = "done"
        for row in self.jobs.values():
            payload = row["payload"]
            if row["status"] not in ("done", "cancelled"):
                continue
            if payload.get("type") == "lab":
                payload.pop("url", None)
            elif payload.get("type") == "telegram" and re.match(
                r"\s*/(submitlab|labcleanup)(@[a-z0-9_]+)?\s", payload.get("text", ""), re.I
            ):
                payload["text"] = payload["text"].split()[0]

    def fail(self, job, token, code):
        self.jobs[job]["status"] = "failed"
        self.outbox.setdefault(
            f"{job}:failure",
            {
                "id": f"{job}:failure",
                "job_id": job,
                "status": "pending",
                "body": {
                    "kind": "text",
                    "text": "Operation unavailable. /retry or /cancel.",
                    "recovery_notice": True,
                },
            },
        )

    def defer(self, job, token):
        self.jobs[job]["status"] = "pending"

    def next_delivery(self, token, media=True):
        blocked = set()
        for row in self.outbox.values():
            if row["status"] in ("sent", "suppressed"):
                continue
            ready = (
                row["status"] == "pending"
                and (row["job_id"] not in blocked or row["body"].get("recovery_notice"))
                and (media or row["body"]["kind"] != "media")
            )
            if ready:
                return row
            blocked.add(row["job_id"])
        return None

    def prepare_delivery(self, key, token, body):
        self.outbox[key]["body"] = copy.deepcopy(body)

    def ensure_delivery_authorized(self, key, token):
        if self.outbox[key]["status"] not in ("pending", "failed"):
            from skillcoach.storage import MembershipChanged

            raise MembershipChanged("Delivery was suppressed")

    def delivery_result(self, key, token, status, code=None):
        item = self.outbox[key]
        item["status"] = status
        if status == "sent" and item["body"].get("target"):
            self.displayed = copy.deepcopy(item["body"]["target"])
        if status == "sent":
            notice = self.outbox.get(key + ":delivery-error")
            if notice and notice["status"] in ("pending", "failed"):
                notice["status"] = "suppressed"
        if status == "failed" and not key.endswith(":delivery-error"):
            error_id = key + ":delivery-error"
            self.outbox.setdefault(
                error_id,
                {
                    "id": error_id,
                    "job_id": item["job_id"],
                    "status": "pending",
                    "body": {
                        "kind": "text",
                        "text": "Delivery/publication failed. /retry.",
                        "recovery_notice": True,
                    },
                },
            )

    def status(self, *, all_learners=False):
        return {"jobs": [], "outbox": []}

    def slot_deliveries(self, key):
        rows = [row for row in self.outbox.values() if row["job_id"] == key]
        if not rows:
            return []
        sent = [row["delivered_at"] for row in rows if row["status"] == "sent" and row.get("delivered_at")]
        return [
            {
                "learner_id": "owner",
                "first_sent": min(sent) if sent else None,
                "last_sent": max(sent) if sent else None,
                "waiting": sum(row["status"] in ("pending", "failed") for row in rows),
            }
        ]


@pytest.fixture
def harness(config):
    repo, ai, telegram, publisher = MemoryRepository(), FakeAI(), FakeTelegram(), FakePublisher()
    clock = SimpleNamespace(now=datetime(2026, 9, 25, 18, tzinfo=IST))
    runtime = Runtime(config, repo, ai, telegram, publisher, lambda: clock.now)
    return SimpleNamespace(
        repo=repo, ai=ai, telegram=telegram, publisher=publisher, runtime=runtime, clock=clock
    )


@pytest.fixture
def pg_repo():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL unavailable; requires disposable PostgreSQL (provided in CI)")
    if "test" not in url.lower():
        pytest.fail("TEST_DATABASE_URL must visibly identify a disposable test database")
    schema = "test_" + uuid4().hex
    repo = Repository(url, schema=schema)
    try:
        repo.migrate()
        yield repo
    finally:
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
