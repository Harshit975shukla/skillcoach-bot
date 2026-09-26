"""PostgreSQL is authoritative; short transactions never contain external calls."""

import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from skillcoach.models import State


class LostLease(RuntimeError):
    pass


class MembershipChanged(LostLease):
    pass


class Repository:
    def __init__(
        self,
        url: str,
        *,
        schema: str = "skillcoach_private",
        learner_id: str = "owner",
        owner_id: int | None = None,
    ):
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", schema):
            raise ValueError("Invalid private schema identifier")
        self.url = url
        self.schema = schema
        self.learner_id = learner_id
        self.owner_id = owner_id
        self._session_connection = ContextVar("skillcoach_connection", default=None)
        configured_ca = os.getenv("DATABASE_CA_CERT_FILE", "")
        self.ca_cert_file = None
        if configured_ca:
            path = Path(configured_ca)
            if not path.is_absolute():
                path = Path(__file__).parent / path
            if not path.is_file():
                raise ValueError("Configured database CA certificate file does not exist.")
            if conninfo_to_dict(url).get("sslmode") != "verify-full":
                raise ValueError("A configured CA certificate requires sslmode=verify-full.")
            self.ca_cert_file = str(path.resolve())

    @property
    def is_owner(self):
        return self.learner_id == "owner"

    def for_learner(self, learner_id: str):
        scoped = Repository(self.url, schema=self.schema, learner_id=learner_id, owner_id=self.owner_id)
        scoped._session_connection = self._session_connection
        return scoped

    def member(self):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM learners WHERE id=%s", (self.learner_id,)).fetchone()
            if row is None:
                raise MembershipChanged("Learner does not exist")
            return row

    def recipient(self):
        member = self.member()
        destination = self.owner_id if self.is_owner else member["telegram_id"]
        if type(destination) is not int or destination <= 0:
            raise ValueError("Recipient is not configured")
        return destination

    def accept_update(self, update_id: int, payload: dict, config):
        from skillcoach.access import accept_update

        return accept_update(self, update_id, payload, config)

    def active_learners(self):
        with self.connection() as conn:
            return [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM learners WHERE status='active' ORDER BY joined_at, id"
                )
            ]

    def _ensure_access(self, conn, generation=None):
        member = conn.execute("SELECT * FROM learners WHERE id=%s FOR UPDATE", (self.learner_id,)).fetchone()
        if (
            not member
            or member["status"] != "active"
            or (generation is not None and generation != member["generation"])
        ):
            raise MembershipChanged("Learner access changed; no mutation applied")
        return member

    def _job(self, conn, job):
        member = self._ensure_access(conn)
        row = conn.execute(
            "SELECT * FROM jobs WHERE id=%s AND learner_id=%s FOR UPDATE", (job, self.learner_id)
        ).fetchone()
        if not row or row["status"] == "cancelled" or row["access_generation"] != member["generation"]:
            raise MembershipChanged("Work is no longer authorized")
        return row

    @contextmanager
    def session(self):
        """Reuse one TCP connection in this request/worker turn, never one long transaction."""
        if self._session_connection.get() is not None:
            yield
            return
        with psycopg.connect(
            self.url,
            connect_timeout=5,
            row_factory=dict_row,
            prepare_threshold=None,
            autocommit=True,
            **({"sslrootcert": self.ca_cert_file} if self.ca_cert_file else {}),
        ) as conn:
            token = self._session_connection.set(conn)
            try:
                yield
            finally:
                self._session_connection.reset(token)

    @contextmanager
    def connection(self):
        with self.session():
            conn = self._session_connection.get()
            with conn.transaction():
                # Reapply within every short transaction, including with transaction poolers.
                conn.execute("SET LOCAL statement_timeout = '5s'")
                conn.execute("SET LOCAL lock_timeout = '3s'")
                conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(self.schema)))
                yield conn

    def migrate(self):
        with self.connection() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(7429031)")
            conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
            conn.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(sql.Identifier(self.schema)))
            exists = conn.execute("SELECT to_regclass('schema_migrations') AS t").fetchone()["t"]
            versions = (
                {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
                if exists
                else set()
            )
            for path in sorted((Path(__file__).parent / "migrations").glob("*.sql")):
                version = int(path.name.split("_")[0])
                if version not in versions:
                    conn.execute(path.read_text(encoding="utf-8"))

    def read(self) -> tuple[int, State]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT revision, body FROM coach_state WHERE learner_id=%s", (self.learner_id,)
            ).fetchone()
            if row is None:
                raise MembershipChanged("Learner state is unavailable")
            return row["revision"], State.model_validate(row["body"])

    def enqueue(self, key: str, payload: dict, *, available_at=None) -> bool:
        if available_at is not None and (available_at.tzinfo is None or available_at.utcoffset() is None):
            raise ValueError("Scheduled work requires a timezone-aware due time")
        with self.connection() as conn:
            member = self._ensure_access(conn)
            row = conn.execute(
                "SELECT displayed_target FROM coach_state WHERE learner_id=%s FOR UPDATE", (self.learner_id,)
            ).fetchone()
            body = dict(payload)
            if body.get("type") == "telegram":
                body["target"] = row["displayed_target"]
            result = conn.execute(
                "INSERT INTO jobs(id,payload,learner_id,access_generation,available_at) "
                "VALUES (%s,%s,%s,%s,coalesce(%s,now())) "
                "ON CONFLICT DO NOTHING RETURNING id",
                (
                    key if self.is_owner else f"learner:{self.learner_id}:{key}",
                    Jsonb(body),
                    self.learner_id,
                    member["generation"],
                    available_at,
                ),
            ).fetchone()
            return result is not None

    def acquire(self, name: str, seconds: int) -> str | None:
        token = uuid4().hex
        with self.connection() as conn:
            row = conn.execute(
                "UPDATE worker_leases SET token=%s, expires_at=now()+(%s * interval '1 second') "
                "WHERE name=%s AND expires_at < now() RETURNING name",
                (token, seconds, name),
            ).fetchone()
        return token if row else None

    def release(self, name: str, token: str):
        with self.connection() as conn:
            conn.execute(
                "UPDATE worker_leases SET token=NULL, expires_at='-infinity' WHERE name=%s AND token=%s",
                (name, token),
            )

    @staticmethod
    def _fence(conn, name: str, token: str):
        row = conn.execute(
            "SELECT name FROM worker_leases WHERE name=%s AND token=%s AND expires_at>now() FOR UPDATE",
            (name, token),
        ).fetchone()
        if not row:
            raise LostLease("Worker lease expired; transaction not applied.")

    def next_job(self, token: str) -> dict | None:
        with self.connection() as conn:
            self._fence(conn, "domain", token)
            conn.execute(
                "UPDATE jobs SET status='failed', error_code='worker_interrupted' "
                "WHERE status='running' AND attempts>=5"
            )
            row = conn.execute(
                "SELECT j.* FROM jobs j JOIN learners l ON l.id=j.learner_id "
                "WHERE j.status IN ('pending','running','failed') AND j.available_at<=now() "
                "AND j.attempts < 5 AND l.status='active' AND l.generation=j.access_generation ORDER BY l.last_job_at, "
                "CASE WHEN j.payload->>'text' IN ('/cancel','/pause','/retry') THEN 0 ELSE 1 END, j.sequence "
                "LIMIT 1 FOR UPDATE OF l"
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE learners SET last_job_at=clock_timestamp() WHERE id=%s", (row["learner_id"],)
                )
                conn.execute(
                    "UPDATE jobs SET status='running', attempts=attempts+1 WHERE id=%s", (row["id"],)
                )
            return row

    def cached(self, job: str, operation: str):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT a.body FROM ai_results a JOIN jobs j ON j.id=a.job_id "
                "WHERE a.job_id=%s AND a.operation=%s AND j.learner_id=%s",
                (job, operation, self.learner_id),
            ).fetchone()
            return row["body"] if row else None

    def cache(self, job: str, operation: str, body: dict, token: str):
        with self.connection() as conn:
            self._fence(conn, "domain", token)
            self._job(conn, job)
            conn.execute(
                "INSERT INTO ai_results VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (job, operation, Jsonb(body)),
            )

    def reserve_ai(self, job: str, operation: str, local_date, limit: int):
        from skillcoach.clients import ExternalError

        with self.connection() as conn:
            self._job(conn, job)
            count = conn.execute(
                "SELECT count(*) AS n FROM ai_usage WHERE learner_id=%s AND local_date=%s",
                (self.learner_id, local_date),
            ).fetchone()["n"]
            if count >= limit:
                raise ExternalError("daily_ai_budget_exhausted", retryable=False)
            conn.execute(
                "INSERT INTO ai_usage(learner_id,job_id,operation,local_date) VALUES (%s,%s,%s,%s)",
                (self.learner_id, job, operation, local_date),
            )

    def finish(
        self,
        job: str,
        token: str,
        revision: int,
        state: State,
        messages: list[dict],
        answers: list[tuple[str, str]],
        control: str | None = None,
    ):
        with self.connection() as conn:
            self._fence(conn, "domain", token)
            authorized = self._job(conn, job)
            updated = conn.execute(
                "UPDATE coach_state SET body=%s, revision=revision+1 WHERE learner_id=%s "
                "AND revision=%s RETURNING id",
                (Jsonb(state.model_dump(mode="json")), self.learner_id, revision),
            ).fetchone()
            if not updated:
                raise LostLease("State revision changed; transaction not applied.")
            for task in state.tasks.values():
                conn.execute(
                    "INSERT INTO task_keys(id,origin,learner_id) VALUES (%s,%s,%s) "
                    "ON CONFLICT(learner_id,id) DO NOTHING",
                    (task.id, task.origin, self.learner_id),
                )
            for session, question in answers:
                conn.execute(
                    "INSERT INTO answer_keys(session_id,question_id,job_id,learner_id) VALUES (%s,%s,%s,%s)",
                    (session, question, job, self.learner_id),
                )
            for index, body in enumerate(messages):
                conn.execute(
                    "INSERT INTO outbox(id,job_id,body,learner_id,access_generation) "
                    "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (f"{job}:{index}", job, Jsonb(body), self.learner_id, authorized["access_generation"]),
                )
            if control == "retry":
                conn.execute(
                    "UPDATE jobs SET status='pending', attempts=0, available_at=now() "
                    "WHERE status='failed' AND learner_id=%s AND access_generation=%s",
                    (self.learner_id, authorized["access_generation"]),
                )
                conn.execute(
                    "UPDATE outbox SET status='pending', attempts=0, available_at=now() "
                    "WHERE status='failed' AND learner_id=%s AND access_generation=%s",
                    (self.learner_id, authorized["access_generation"]),
                )
            elif control == "cancel":
                conn.execute(
                    "UPDATE jobs SET status='cancelled' WHERE status IN ('pending','running','failed') "
                    "AND learner_id=%s AND id<>%s",
                    (self.learner_id, job),
                )
                conn.execute(
                    "UPDATE outbox SET status='suppressed' WHERE status IN ('failed','pending') AND learner_id=%s "
                    "AND (body->>'target' IS NOT NULL OR job_id IN "
                    "(SELECT id FROM jobs WHERE status='cancelled') OR job_id IN "
                    "(SELECT job_id FROM outbox WHERE status='failed' AND learner_id=%s))",
                    (self.learner_id, self.learner_id),
                )
            elif control == "pause":
                conn.execute(
                    "UPDATE outbox SET status='suppressed' WHERE status IN ('failed','pending') "
                    "AND body->>'scheduled'='true' AND learner_id=%s",
                    (self.learner_id,),
                )
                conn.execute(
                    "UPDATE jobs SET status='cancelled' WHERE status IN ('pending','failed','running') "
                    "AND payload->>'type'='schedule' AND learner_id=%s",
                    (self.learner_id,),
                )
            conn.execute("UPDATE jobs SET status='done', error_code=NULL WHERE id=%s", (job,))

    def defer(self, job: str, token: str):
        with self.connection() as conn:
            self._fence(conn, "domain", token)
            authorized = self._job(conn, job)
            conn.execute(
                "UPDATE jobs SET status='pending',attempts=greatest(attempts-1,0),available_at=now() "
                "WHERE id=%s",
                (job,),
            )
            notice = {
                "kind": "text",
                "text": "Preparing your full lesson and explanatory media. "
                "Validated steps are saved as I work. You can /cancel while it is being prepared.",
            }
            if authorized["payload"].get("type") == "schedule":
                notice.update(scheduled=True, scheduled_date=authorized["payload"]["date"])
            conn.execute(
                "INSERT INTO outbox(id,job_id,body,learner_id,access_generation) VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING",
                (job + ":preparing", job, Jsonb(notice), self.learner_id, authorized["access_generation"]),
            )

    def fail(self, job: str, token: str, code: str):
        with self.connection() as conn:
            self._fence(conn, "domain", token)
            authorized = self._job(conn, job)
            payload = authorized["payload"]
            notice = {
                "kind": "text",
                "recovery_notice": True,
                "text": "That operation is unavailable; it has not been applied. "
                "It is saved for retry (up to five attempts). Use /retry or /cancel. "
                "Assessment scores are not invented when a provider fails.",
            }
            if payload.get("type") == "schedule":
                notice.update(scheduled=True, scheduled_date=payload["date"])
            conn.execute(
                "UPDATE jobs SET status='failed', error_code=%s, "
                "available_at=now()+interval '5 minutes' WHERE id=%s",
                (code, job),
            )
            conn.execute(
                "INSERT INTO outbox(id,job_id,body,learner_id,access_generation) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (f"{job}:failure", job, Jsonb(notice), self.learner_id, authorized["access_generation"]),
            )

    def next_delivery(self, token: str, *, media: bool = True) -> dict | None:
        with self.connection() as conn:
            self._fence(conn, "delivery", token)
            conn.execute(
                "UPDATE outbox o SET status='suppressed' FROM learners l WHERE o.learner_id=l.id "
                "AND o.status IN ('pending','failed') AND (o.access_generation<>l.generation "
                "OR (l.status<>'active' AND NOT o.access_notice))"
            )
            # A failed item blocks only its own ordered message group, not unrelated commands.
            row = conn.execute(
                "SELECT o.* FROM outbox o JOIN learners l ON l.id=o.learner_id "
                "WHERE o.status IN ('pending','failed') "
                "AND o.available_at<=now() AND o.attempts < 5 "
                "AND (%s OR o.body->>'kind' <> 'media') AND (o.body->>'recovery_notice'='true' OR NOT EXISTS "
                "(SELECT 1 FROM outbox p WHERE p.job_id=o.job_id AND p.sequence<o.sequence "
                "AND p.status IN ('pending','failed'))) "
                "ORDER BY CASE WHEN o.body->>'kind'='media' THEN 1 ELSE 0 END, "
                "l.last_delivery_at,o.sequence LIMIT 1",
                (media,),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE learners SET last_delivery_at=clock_timestamp() WHERE id=%s", (row["learner_id"],)
                )
            return row

    def ensure_delivery_authorized(self, key: str, token: str):
        with self.connection() as conn:
            self._fence(conn, "delivery", token)
            row = conn.execute(
                "SELECT 1 FROM outbox o JOIN learners l ON l.id=o.learner_id "
                "WHERE o.id=%s AND o.learner_id=%s AND o.status IN ('pending','failed') "
                "AND o.access_generation=l.generation AND (l.status='active' OR o.access_notice)",
                (key, self.learner_id),
            ).fetchone()
            if not row:
                raise MembershipChanged("Queued delivery is no longer authorized")

    def prepare_delivery(self, key: str, token: str, body: dict):
        with self.connection() as conn:
            self._fence(conn, "delivery", token)
            conn.execute(
                "UPDATE outbox SET body=%s WHERE id=%s AND learner_id=%s", (Jsonb(body), key, self.learner_id)
            )

    def delivery_result(self, key: str, token: str, status: str, code: str | None = None):
        with self.connection() as conn:
            self._fence(conn, "delivery", token)
            updated = conn.execute(
                "UPDATE outbox SET status=%s, error_code=%s, attempts=attempts+1, "
                "available_at=now()+interval '5 minutes', "
                "delivered_at=CASE WHEN %s='sent' THEN now() ELSE NULL END WHERE id=%s AND learner_id=%s "
                "AND status IN ('pending','failed') RETURNING id",
                (status, code, status, key, self.learner_id),
            ).fetchone()
            if not updated:
                return
            if status == "sent":
                conn.execute(
                    "UPDATE outbox SET status='suppressed' WHERE id=%s AND learner_id=%s "
                    "AND status IN ('pending','failed') AND body->>'recovery_notice'='true'",
                    (key + ":delivery-error", self.learner_id),
                )
                conn.execute(
                    "UPDATE coach_state SET displayed_target=(SELECT body->'target' FROM outbox WHERE id=%s) "
                    "WHERE learner_id=%s AND (SELECT body ? 'target' FROM outbox WHERE id=%s)",
                    (key, self.learner_id, key),
                )
                conn.execute(
                    "UPDATE coach_state SET body=jsonb_set(body, "
                    "ARRAY['lessons',(SELECT body->>'lesson_key' FROM outbox WHERE id=%s),'delivered_at'], "
                    "to_jsonb(now())), revision=revision+1 WHERE learner_id=%s "
                    "AND (SELECT body ? 'lesson_key' FROM outbox WHERE id=%s)",
                    (key, self.learner_id, key),
                )
            elif status == "failed":
                item = conn.execute(
                    "SELECT * FROM outbox WHERE id=%s AND learner_id=%s", (key, self.learner_id)
                ).fetchone()
                if not key.endswith(":delivery-error"):
                    notice = {
                        "kind": "text",
                        "recovery_notice": True,
                        "text": "A delivery or dashboard publication failed and remains recoverable. "
                        "Use /status and /retry after fixing the cause. "
                        "A GitHub conflict requires reviewing the public file, then a new /publish.",
                    }
                    if item["body"].get("scheduled"):
                        notice.update(scheduled=True, scheduled_date=item["body"].get("scheduled_date"))
                    conn.execute(
                        "INSERT INTO outbox(id,job_id,body,learner_id,access_generation,access_notice) "
                        "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (
                            key + ":delivery-error",
                            item["job_id"],
                            Jsonb(notice),
                            self.learner_id,
                            item["access_generation"],
                            item["access_notice"],
                        ),
                    )

    def status(self, *, all_learners=False) -> dict:
        with self.connection() as conn:
            return {
                table: [
                    dict(row)
                    for row in conn.execute(
                        f"SELECT status, count(*) AS count FROM {table} WHERE (%s OR learner_id=%s) GROUP BY status",
                        (all_learners and self.is_owner, self.learner_id),
                    )
                ]
                for table in ("jobs", "outbox")
            }

    def needs_media(self) -> bool:
        with self.connection() as conn:
            return conn.execute(
                "SELECT EXISTS(SELECT 1 FROM outbox WHERE status IN ('pending','failed') "
                "AND attempts<5 AND body->>'kind'='media') OR EXISTS("
                "SELECT 1 FROM jobs WHERE status IN ('pending','failed','running') AND attempts<5 AND "
                "(payload->>'text' LIKE '/learn %' OR payload->>'kind'='lesson')) AS needed"
            ).fetchone()["needed"]

    def media_asset(self, key: str):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT file_id,kind,metadata FROM media_assets "
                "WHERE asset_key=%s AND (learner_id=%s OR learner_id IS NULL)",
                (key, self.learner_id),
            ).fetchone()
            return row

    def save_media_asset(self, key: str, artifact: dict, token: str, *, shared_reviewed=False):
        with self.connection() as conn:
            self._fence(conn, "delivery", token)
            self._ensure_access(conn)
            conn.execute(
                "INSERT INTO media_assets(asset_key,learner_id,file_id,kind,metadata) VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT(asset_key) DO NOTHING",
                (
                    key,
                    None if shared_reviewed else self.learner_id,
                    artifact["file_id"],
                    artifact["kind"],
                    Jsonb(artifact["metadata"]),
                ),
            )

    def forget_media_asset(self, key: str):
        with self.connection() as conn:
            conn.execute(
                "DELETE FROM media_assets WHERE asset_key=%s AND (learner_id=%s OR learner_id IS NULL)",
                (key, self.learner_id),
            )
