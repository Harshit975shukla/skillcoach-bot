"""PostgreSQL is authoritative; short transactions never contain external calls."""

import re
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from skillcoach.models import State


class LostLease(RuntimeError):
    pass


class Repository:
    def __init__(self, url: str, *, schema: str = "skillcoach_private"):
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", schema):
            raise ValueError("Invalid private schema identifier")
        self.url = url
        self.schema = schema

    @contextmanager
    def connection(self):
        with psycopg.connect(
            self.url,
            connect_timeout=5,
            row_factory=dict_row,
        ) as conn:
            # Transaction-local settings also work with session/transaction poolers.
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
            row = conn.execute("SELECT revision, body FROM coach_state WHERE id=1").fetchone()
            return row["revision"], State.model_validate(row["body"])

    def enqueue(self, key: str, payload: dict) -> bool:
        with self.connection() as conn:
            row = conn.execute("SELECT displayed_target FROM coach_state WHERE id=1 FOR UPDATE").fetchone()
            body = dict(payload)
            if body.get("type") == "telegram":
                body["target"] = row["displayed_target"]
            result = conn.execute(
                "INSERT INTO jobs(id, payload) VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING id",
                (key, Jsonb(body)),
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
                "SELECT * FROM jobs WHERE status IN ('pending','running','failed') AND available_at<=now() "
                "AND attempts < 5 ORDER BY "
                "CASE WHEN payload->>'text' IN ('/cancel','/pause','/retry') THEN 0 ELSE 1 END, sequence "
                "LIMIT 1 FOR UPDATE"
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE jobs SET status='running', attempts=attempts+1 WHERE id=%s", (row["id"],)
                )
            return row

    def cached(self, job: str, operation: str):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT body FROM ai_results WHERE job_id=%s AND operation=%s", (job, operation)
            ).fetchone()
            return row["body"] if row else None

    def cache(self, job: str, operation: str, body: dict, token: str):
        with self.connection() as conn:
            self._fence(conn, "domain", token)
            conn.execute(
                "INSERT INTO ai_results VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (job, operation, Jsonb(body)),
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
            updated = conn.execute(
                "UPDATE coach_state SET body=%s, revision=revision+1 WHERE id=1 AND revision=%s RETURNING id",
                (Jsonb(state.model_dump(mode="json")), revision),
            ).fetchone()
            if not updated:
                raise LostLease("State revision changed; transaction not applied.")
            for task in state.tasks.values():
                conn.execute(
                    "INSERT INTO task_keys VALUES (%s,%s) ON CONFLICT(id) DO NOTHING", (task.id, task.origin)
                )
            for session, question in answers:
                conn.execute("INSERT INTO answer_keys VALUES (%s,%s,%s)", (session, question, job))
            for index, body in enumerate(messages):
                conn.execute(
                    "INSERT INTO outbox(id,job_id,body) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                    (f"{job}:{index}", job, Jsonb(body)),
                )
            if control == "retry":
                conn.execute(
                    "UPDATE jobs SET status='pending', attempts=0, available_at=now() WHERE status='failed'"
                )
                conn.execute(
                    "UPDATE outbox SET status='pending', attempts=0, available_at=now() WHERE status='failed'"
                )
            elif control == "cancel":
                conn.execute("UPDATE jobs SET status='cancelled' WHERE status='failed'")
                conn.execute(
                    "UPDATE outbox SET status='suppressed' WHERE status IN ('failed','pending') "
                    "AND (body->>'target' IS NOT NULL OR job_id IN "
                    "(SELECT id FROM jobs WHERE status='cancelled') OR job_id IN "
                    "(SELECT job_id FROM outbox WHERE status='failed'))"
                )
            elif control == "pause":
                conn.execute(
                    "UPDATE outbox SET status='suppressed' WHERE status IN ('failed','pending') "
                    "AND body->>'scheduled'='true'"
                )
                conn.execute(
                    "UPDATE jobs SET status='cancelled' WHERE status IN ('pending','failed','running') "
                    "AND payload->>'type'='schedule'"
                )
            conn.execute("UPDATE jobs SET status='done', error_code=NULL WHERE id=%s", (job,))

    def fail(self, job: str, token: str, code: str):
        with self.connection() as conn:
            self._fence(conn, "domain", token)
            payload = conn.execute("SELECT payload FROM jobs WHERE id=%s", (job,)).fetchone()["payload"]
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
                "INSERT INTO outbox(id,job_id,body) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (f"{job}:failure", job, Jsonb(notice)),
            )

    def next_delivery(self, token: str, *, media: bool = True) -> dict | None:
        with self.connection() as conn:
            self._fence(conn, "delivery", token)
            # A failed item blocks only its own ordered message group, not unrelated commands.
            return conn.execute(
                "SELECT o.* FROM outbox o WHERE o.status IN ('pending','failed') "
                "AND o.available_at<=now() AND o.attempts < 5 "
                "AND (%s OR o.body->>'kind' <> 'media') AND (o.body->>'recovery_notice'='true' OR NOT EXISTS "
                "(SELECT 1 FROM outbox p WHERE p.job_id=o.job_id AND p.sequence<o.sequence "
                "AND p.status IN ('pending','failed'))) ORDER BY o.sequence LIMIT 1",
                (media,),
            ).fetchone()

    def prepare_delivery(self, key: str, token: str, body: dict):
        with self.connection() as conn:
            self._fence(conn, "delivery", token)
            conn.execute("UPDATE outbox SET body=%s WHERE id=%s", (Jsonb(body), key))

    def delivery_result(self, key: str, token: str, status: str, code: str | None = None):
        with self.connection() as conn:
            self._fence(conn, "delivery", token)
            conn.execute(
                "UPDATE outbox SET status=%s, error_code=%s, attempts=attempts+1, "
                "available_at=now()+interval '5 minutes', "
                "delivered_at=CASE WHEN %s='sent' THEN now() ELSE NULL END WHERE id=%s",
                (status, code, status, key),
            )
            if status == "sent":
                conn.execute(
                    "UPDATE coach_state SET displayed_target=(SELECT body->'target' FROM outbox WHERE id=%s) "
                    "WHERE id=1 AND (SELECT body ? 'target' FROM outbox WHERE id=%s)",
                    (key, key),
                )
                conn.execute(
                    "UPDATE coach_state SET body=jsonb_set(body, "
                    "ARRAY['lessons',(SELECT body->>'lesson_key' FROM outbox WHERE id=%s),'delivered_at'], "
                    "to_jsonb(now())), revision=revision+1 WHERE id=1 "
                    "AND (SELECT body ? 'lesson_key' FROM outbox WHERE id=%s)",
                    (key, key),
                )
            elif status == "failed":
                item = conn.execute("SELECT job_id, body FROM outbox WHERE id=%s", (key,)).fetchone()
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
                        "INSERT INTO outbox(id,job_id,body) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                        (key + ":delivery-error", item["job_id"], Jsonb(notice)),
                    )

    def status(self) -> dict:
        with self.connection() as conn:
            return {
                table: [
                    dict(row)
                    for row in conn.execute(f"SELECT status, count(*) AS count FROM {table} GROUP BY status")
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
