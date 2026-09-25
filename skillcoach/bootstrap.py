"""Explicit fresh-project preparation; never called by webhooks or scheduled coaching."""

import logging
from urllib.parse import quote, urlsplit, urlunsplit

from psycopg import Error, sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from skillcoach.models import State
from skillcoach.storage import Repository

ROLE = "skillcoach_runtime"
ROLE_MARKER = "SkillCoach bot runtime; managed by explicit bootstrap-fresh"
TABLES = ("coach_state", "worker_leases", "jobs", "ai_results", "task_keys", "answer_keys", "outbox")
log = logging.getLogger(__name__)


def _execute(conn, stage, query, params=None):
    try:
        return conn.execute(query, params)
    except Error as exc:
        log.error("bootstrap_stage_failed stage=%s code=%s", stage, exc.sqlstate or type(exc).__name__)
        raise


def ensure_runtime_role(conn, password):
    existing = _execute(
        conn,
        "inspect_role",
        "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls, "
        "shobj_description(oid, 'pg_authid') AS marker FROM pg_roles WHERE rolname=%s",
        (ROLE,),
    ).fetchone()
    if existing and existing["marker"] != ROLE_MARKER:
        raise ValueError("Runtime role already exists without the SkillCoach ownership marker.")
    if existing and any(
        existing[key] for key in ("rolsuper", "rolcreatedb", "rolcreaterole", "rolbypassrls")
    ):
        raise ValueError("Existing runtime role has unexpected elevated capabilities.")
    action = "ALTER" if existing else "CREATE"
    # PostgreSQL defaults privileged attributes off; managed admins cannot explicitly alter all of them.
    _execute(
        conn,
        "configure_role",
        sql.SQL("{} ROLE {} LOGIN NOINHERIT CONNECTION LIMIT 10 PASSWORD {}").format(
            sql.SQL(action), sql.Identifier(ROLE), sql.Literal(password)
        ),
    )
    capabilities = _execute(
        conn,
        "verify_role_capabilities",
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls, rolinherit FROM pg_roles WHERE rolname=%s",
        (ROLE,),
    ).fetchone()
    if any(capabilities.values()):
        raise ValueError("Runtime role must have no elevated or inherited capabilities.")
    _execute(
        conn,
        "mark_role",
        sql.SQL("COMMENT ON ROLE {} IS {}").format(sql.Identifier(ROLE), sql.Literal(ROLE_MARKER)),
    )


def runtime_url(admin_url: str, password: str) -> str:
    parsed = urlsplit(admin_url)
    if parsed.scheme not in ("postgres", "postgresql") or not parsed.hostname or not parsed.username:
        raise ValueError("A PostgreSQL admin URL with explicit host and user is required.")
    if len(password) < 32:
        raise ValueError("The generated runtime password must contain at least 32 characters.")
    user = ROLE
    if parsed.hostname.endswith(".pooler.supabase.com"):
        if not parsed.username.startswith("postgres."):
            raise ValueError("Expected the API-provided Supabase admin pooler username.")
        user += "." + parsed.username.split(".", 1)[1]
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{quote(user, safe='')}:{quote(password, safe='')}@{host}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, ""))


def bootstrap_fresh(admin_url: str, password: str) -> dict:
    if conninfo_to_dict(admin_url).get("sslmode") != "verify-full":
        raise ValueError("Fresh production preparation requires verified TLS.")
    target_url = runtime_url(admin_url, password)
    admin = Repository(admin_url)
    admin.migrate()
    with admin.connection() as conn:
        row = conn.execute("SELECT body FROM coach_state WHERE id=1 FOR UPDATE").fetchone()
        if State.model_validate(row["body"]) != State():
            raise ValueError("Private learning state is not empty; fresh bootstrap refused.")
        for table in ("jobs", "outbox"):
            if conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(table))).fetchone()[
                "n"
            ]:
                raise ValueError("Existing processing history must be preserved; fresh bootstrap refused.")
        ensure_runtime_role(conn, password)
        _execute(
            conn,
            "grant_database",
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(conn.info.dbname), sql.Identifier(ROLE)
            ),
        )
        _execute(
            conn,
            "grant_schema",
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(admin.schema), sql.Identifier(ROLE)
            ),
        )
        for table in TABLES:
            _execute(
                conn,
                "grant_table",
                sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON {} TO {}").format(
                    sql.Identifier(admin.schema, table), sql.Identifier(ROLE)
                ),
            )
        _execute(
            conn,
            "grant_migration_read",
            sql.SQL("GRANT SELECT ON {} TO {}").format(
                sql.Identifier(admin.schema, "schema_migrations"), sql.Identifier(ROLE)
            ),
        )
        _execute(
            conn,
            "grant_sequences",
            sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(
                sql.Identifier(admin.schema), sql.Identifier(ROLE)
            ),
        )
    runtime = Repository(target_url)
    with runtime.connection() as conn:
        identity = conn.execute("SELECT current_user AS role, current_schema() AS schema").fetchone()
        if identity != {"role": ROLE, "schema": runtime.schema}:
            raise ValueError("Runtime connection identity/schema verification failed.")
        if not conn.pgconn.ssl_in_use:
            raise ValueError("Runtime connection did not negotiate TLS.")
        privileges = conn.execute(
            "SELECT has_schema_privilege(current_user,'public','CREATE') AS public_create, "
            "has_table_privilege(current_user,'schema_migrations','UPDATE') AS migration_write"
        ).fetchone()
        if privileges["public_create"] or privileges["migration_write"]:
            raise ValueError("Runtime role has unexpected public-schema or migration-write privileges.")
        conn.execute("SAVEPOINT permission_probe")
        _execute(
            conn,
            "runtime_write_probe",
            "INSERT INTO jobs(id,payload) VALUES (%s,%s)",
            ("bootstrap-permission-probe", Jsonb({"type": "permission-probe"})),
        )
        conn.execute("ROLLBACK TO SAVEPOINT permission_probe")
    return {
        "schema": runtime.schema,
        "runtime_role": ROLE,
        "verified_tls": True,
        "fresh_state": True,
        "private_write_permission": True,
        "learner_data_seeded": False,
    }
