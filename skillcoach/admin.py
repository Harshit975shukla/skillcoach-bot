"""Owner-only admin views and confirmed, idempotent actions; no arbitrary command execution."""

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta
from functools import wraps
from uuid import UUID

from psycopg.types.json import Jsonb
from pydantic import ValidationError

from skillcoach.access import _admin, _audit, _job
from skillcoach.admin_auth import (
    LOGIN_COOKIE,
    SESSION_COOKIE,
    SESSION_SECONDS,
    AdminDenied,
    authenticate,
    csrf_token,
    exchange_login,
    login_from_telegram,
    same_origin,
    start_login,
)
from skillcoach.commands import COMMANDS
from skillcoach.models import State
from skillcoach.timeutil import IST, requested_quiz_payload

OWNER_COMMANDS = {
    key: value
    for key, value in COMMANDS.items()
    if key not in {"setup", "resume", "assess", "skip", "q", "complete"}
}
ACTIONS = {
    "invite": ("Create invitation", {"label"}),
    "revokeinvite": ("Cancel unused invitation", {"invite_id"}),
    "approve": ("Approve invited learner", set()),
    "reject": ("Reject pending request", set()),
    "revoke": ("Revoke learner access", set()),
    "pause": ("Pause scheduled coaching", set()),
    "unpause": ("Resume future scheduled coaching", set()),
    "cancel": ("Cancel unfinished work", set()),
    "retry": ("Retry failed work", set()),
    "send_lesson": ("Send a full lesson", {"topic"}),
    "schedule_quiz": ("Schedule one lesson-based quiz", {"topic", "at"}),
    "owner_command": ("Run a command in your own bot chat", {"command", "argument"}),
}


class AdminConflict(ValueError):
    pass


def _json_body(request, fields):
    body = request.get_json(silent=True)
    if request.args or not isinstance(body, dict) or set(body) != set(fields):
        raise AdminDenied("Unexpected request fields. Refresh the admin dashboard.")
    return body


def _confirm_token(config, row):
    value = json.dumps(
        {
            "id": row["id"],
            "session": row["session_hash"],
            "action": row["action"],
            "target": row["target_id"],
            "arguments": row["arguments"],
            "generation": row["expected_generation"],
        },
        sort_keys=True,
    )
    return hmac.new(config.webhook_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def _arguments(action, arguments):
    if (
        not isinstance(action, str)
        or action not in ACTIONS
        or not isinstance(arguments, dict)
        or set(arguments) != ACTIONS[action][1]
    ):
        raise AdminDenied("This action or its arguments are not supported.")
    if any(not isinstance(value, str) for value in arguments.values()):
        raise AdminDenied("Action arguments must be text.")
    if any(len(value) > 16000 for value in arguments.values()):
        raise AdminDenied("Action input is too long.")
    args = {key: value.strip() for key, value in arguments.items()}
    if action == "owner_command":
        args["command"] = args["command"].lstrip("/")
    if action == "schedule_quiz":
        try:
            due = datetime.fromisoformat(args["at"])
            if due.tzinfo is None or due.utcoffset() is None:
                raise ValueError("Quiz time requires a timezone")
            args["at"] = due.astimezone(IST).isoformat()
        except ValueError:
            raise AdminDenied("Use a valid quiz date and time including its timezone.") from None
    return args


def _validate_action(conn, action, target, arguments, config, now):
    args = _arguments(action, arguments)
    if not isinstance(target, str) or not re.fullmatch(r"owner|u_[a-f0-9]{12}", target):
        raise AdminDenied("Choose one valid recipient.")
    member = conn.execute("SELECT * FROM learners WHERE id=%s FOR UPDATE", (target,)).fetchone()
    if not member:
        raise AdminConflict("The selected learner no longer exists.")
    state_row = conn.execute(
        "SELECT body,revision FROM coach_state WHERE learner_id=%s", (target,)
    ).fetchone()
    state = State.model_validate(state_row["body"])
    details, warnings = [], []
    if action in ("invite", "revokeinvite", "owner_command") and target != "owner":
        raise AdminDenied("This action is restricted to the owner's account.")
    if action in ("approve", "reject", "revoke"):
        if target == "owner":
            raise AdminDenied("The owner's administrator access cannot be changed here.")
        permitted = ("pending", "active") if action == "revoke" else ("pending",)
        if member["status"] not in permitted:
            raise AdminConflict("The learner's status changed. Refresh before acting.")
        if action == "approve":
            count = conn.execute("SELECT count(*) AS n FROM learners WHERE status='active'").fetchone()["n"]
            if count >= config.max_learners:
                raise AdminConflict("The configured learner limit is reached. No paid capacity is enabled.")
            details.append("Grants private coaching access to this invited learner.")
        else:
            warnings.append("Queued coaching is cancelled. Private learning history is retained.")
    elif action == "invite":
        args["label"] = args["label"].strip()
        if len(args["label"]) > 100 or not config.bot_username:
            raise AdminConflict("Use a label up to 100 characters and configure the bot username.")
        count = conn.execute(
            "SELECT count(*) AS n FROM invitations WHERE status='open' AND expires_at>now()"
        ).fetchone()["n"]
        if count >= 50:
            raise AdminConflict("Cancel an unused invitation before creating another.")
        details.append("One-use link, expires in 24 hours. Joining still requires your approval.")
    elif action == "revokeinvite":
        if not re.fullmatch(r"i_[a-f0-9]{12}", args["invite_id"]):
            raise AdminDenied("Choose a valid invitation.")
        invite = conn.execute(
            "SELECT id FROM invitations WHERE id=%s AND status='open' AND expires_at>now()",
            (args["invite_id"],),
        ).fetchone()
        if not invite:
            raise AdminConflict("This invitation is no longer open.")
        details.append("The unused link will stop working. Existing members are unaffected.")
    else:
        if member["status"] != "active":
            raise AdminConflict("Only active learners can receive coaching commands.")
        if action == "owner_command":
            command = args["command"].lstrip("/")
            if command not in OWNER_COMMANDS:
                raise AdminDenied("Use Telegram for answers, task completion and private setup documents.")
            args["command"] = command
            argument = args["argument"].strip()
            args["argument"] = argument
            no_arguments = {
                "start",
                "help",
                "tasks",
                "today",
                "skills",
                "stats",
                "streak",
                "score",
                "gaps",
                "profile",
                "curriculum",
                "dashboard",
                "tip",
                "publish",
                "pause",
                "unpause",
                "cancel",
                "retry",
            }
            if command in no_arguments and argument:
                raise AdminDenied("This command does not accept arguments in the admin panel.")
            if command in {"learn", "ask", "nextweek"} and not argument:
                raise AdminDenied("This command requires a question, topic or preference.")
            if command == "media" and argument not in {"video", "static"}:
                raise AdminDenied("Media must be video or static.")
            if command == "voice" and (
                argument not in {"on", "off"} or argument == "on" and not config.narration_enabled
            ):
                raise AdminDenied("Narration is unavailable; use voice off.")
            details.append(f"/{command}" + (f" {argument}" if argument else ""))
            details.append("Runs only in your own Telegram chat, using your current learning state.")
            if command in ("cancel", "publish", "unpause"):
                warnings.append(COMMANDS[command])
        if action in ("send_lesson", "schedule_quiz"):
            args["topic"] = args["topic"].strip()
            if not args["topic"] or len(args["topic"]) > 300:
                raise AdminDenied("Choose a topic of 1-300 characters.")
            if state.paused:
                raise AdminConflict(
                    "This learner's scheduled notifications are paused. Do not bypass that preference."
                )
            details.append(args["topic"])
            warnings.append("This uses the learner's configured limits; delivery may be delayed.")
        if action == "schedule_quiz":
            try:
                due, _ = requested_quiz_payload(now, datetime.fromisoformat(args["at"]), args["topic"])
            except ValueError as exc:
                raise AdminDenied(str(exc)) from None
            args["at"] = due.isoformat()
            key = f"requested:quiz:{due.date().isoformat()}"
            if target != "owner":
                key = f"learner:{target}:{key}"
            if conn.execute("SELECT 1 FROM jobs WHERE id=%s", (key,)).fetchone():
                raise AdminConflict(
                    "This learner already has a quiz request for that date. It will not be overwritten."
                )
            details.append("Due " + due.strftime("%d %b %Y, %H:%M Asia/Kolkata"))
            warnings.append("Requires that day's topic to be delivered; never replaces an active assessment.")
        if action == "cancel":
            warnings.append(
                "Cancels this learner's unfinished flow and queued/failed work, not completed history."
            )
        if action == "unpause":
            warnings.append("Enables future scheduled notifications for this learner.")
        queued = conn.execute(
            "SELECT count(*) AS n FROM jobs WHERE learner_id=%s AND status IN ('pending','running','failed')",
            (target,),
        ).fetchone()["n"]
        if queued >= 100 and action not in ("pause", "cancel", "retry"):
            raise AdminConflict("This learner already has too much pending work.")
    preview = {
        "title": ACTIONS[action][0],
        "recipient": "You (owner)" if target == "owner" else member["display_name"] or member["id"],
        "recipient_id": target,
        "details": details,
        "warnings": warnings,
        "delivery": "Results appear here; required learner notices are queued."
        if action in ("invite", "revokeinvite", "approve", "reject", "revoke")
        else "Queued through the normal bot worker, not a promise of immediate delivery.",
    }
    return member, args, preview


def preview_action(runtime, session, body):
    try:
        identifier = str(UUID(body["request_id"]))
    except (ValueError, TypeError, AttributeError):
        raise AdminDenied("A valid action request identifier is required.") from None
    normalized = _arguments(body["action"], body["arguments"])
    with runtime.repo.connection() as conn:
        conn.execute("SELECT id FROM learners WHERE id='owner' FOR UPDATE")
        row = conn.execute("SELECT * FROM admin_requests WHERE id=%s", (identifier,)).fetchone()
        if row:
            if (
                row["session_hash"] != session["token_hash"]
                or row["action"] != body["action"]
                or row["target_id"] != body["target"]
                or row["arguments"] != normalized
            ):
                raise AdminConflict(
                    "That request identifier belongs to a different action. Start a new preview."
                )
            if row["expires_at"] <= runtime.clock():
                raise AdminConflict("This preview expired. Request a new one.")
        else:
            count = conn.execute(
                "SELECT count(*) AS n FROM admin_requests WHERE session_hash=%s "
                "AND created_at>now()-interval '1 minute'",
                (session["token_hash"],),
            ).fetchone()["n"]
            if count >= 20:
                raise AdminDenied("Too many actions. Wait one minute.")
            member, args, preview = _validate_action(
                conn, body["action"], body["target"], body["arguments"], runtime.config, runtime.clock()
            )
            row = conn.execute(
                "INSERT INTO admin_requests(id,session_hash,action,target_id,arguments,expected_generation,"
                "expected_status,preview,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (
                    identifier,
                    session["token_hash"],
                    body["action"],
                    body["target"],
                    Jsonb(args),
                    member["generation"],
                    member["status"],
                    Jsonb(preview),
                    runtime.clock() + timedelta(minutes=5),
                ),
            ).fetchone()
    return {
        "request_id": identifier,
        "confirmation": _confirm_token(runtime.config, row),
        "preview": row["preview"],
        "expires_at": row["expires_at"].isoformat(),
        "state": row["state"],
        "result": row["result"],
    }


def execute_action(runtime, session, body):
    if not isinstance(body["request_id"], str) or len(body["request_id"]) > 36:
        raise AdminDenied("A valid preview request is required.")
    with runtime.repo.connection() as conn:
        owner = conn.execute("SELECT * FROM learners WHERE id='owner' FOR UPDATE").fetchone()
        if not conn.execute(
            "SELECT 1 FROM admin_sessions WHERE token_hash=%s AND owner_id=%s AND expires_at>%s FOR SHARE",
            (session["token_hash"], runtime.config.owner_id, runtime.clock()),
        ).fetchone():
            raise AdminDenied("Your session ended before this action. Sign in again.")
        row = conn.execute(
            "SELECT * FROM admin_requests WHERE id=%s FOR UPDATE", (body["request_id"],)
        ).fetchone()
        if not row or row["session_hash"] != session["token_hash"]:
            raise AdminDenied("This preview does not belong to your current session.")
        if not isinstance(body["confirmation"], str) or not hmac.compare_digest(
            body["confirmation"], _confirm_token(runtime.config, row)
        ):
            raise AdminDenied("The action confirmation is invalid.")
        if row["state"] == "completed":
            return {**row["result"], "duplicate": True}
        if row["expires_at"] <= runtime.clock():
            raise AdminConflict("The preview expired. Review a fresh preview.")
        member, args, _ = _validate_action(
            conn, row["action"], row["target_id"], row["arguments"], runtime.config, runtime.clock()
        )
        if member["generation"] != row["expected_generation"] or member["status"] != row["expected_status"]:
            raise AdminConflict("Recipient access changed after preview. Refresh and review again.")
        key = "admin:" + row["id"]
        if row["action"] in ("invite", "revokeinvite", "approve", "reject", "revoke"):
            response = []
            argument = args.get("label", args.get("invite_id", member["id"]))
            _admin(
                conn, row["id"], key, owner, row["action"], argument, runtime.config, owner_output=response
            )
            result = {"state": "handled", "messages": response, "request_id": row["id"]}
        else:
            if row["action"] == "schedule_quiz":
                due, payload = requested_quiz_payload(
                    runtime.clock(), datetime.fromisoformat(args["at"]), args["topic"]
                )
                key = f"requested:quiz:{due.date().isoformat()}"
                if member["id"] != "owner":
                    key = f"learner:{member['id']}:{key}"
                conn.execute(
                    "INSERT INTO jobs(id,payload,learner_id,access_generation,available_at) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (key, Jsonb(payload), member["id"], member["generation"], due),
                )
            else:
                text = {
                    "send_lesson": "/learn " + args.get("topic", ""),
                    "owner_command": "/" + args.get("command", "") + " " + args.get("argument", ""),
                }.get(row["action"], "/" + row["action"])
                target = conn.execute(
                    "SELECT displayed_target FROM coach_state WHERE learner_id=%s", (member["id"],)
                ).fetchone()["displayed_target"]
                _job(
                    conn,
                    key,
                    member,
                    {
                        "type": "telegram",
                        "text": text.strip(),
                        "target": target,
                        "requested_by": "owner_admin",
                    },
                )
            audit_action = "command_" + args["command"] if row["action"] == "owner_command" else row["action"]
            _audit(conn, row["id"], audit_action, member["id"])
            result = {
                "state": "queued",
                "messages": ["Action queued for the selected learner. Check delivery health for completion."],
                "request_id": row["id"],
            }
        conn.execute(
            "UPDATE admin_requests SET state='completed',result=%s WHERE id=%s", (Jsonb(result), row["id"])
        )
        return result


def admin_overview(runtime):
    now = runtime.clock()
    with runtime.repo.connection() as conn:
        rows = conn.execute(
            "SELECT l.id,l.display_name,l.status,l.joined_at,c.body,"
            "(SELECT max(r.created_at) FROM telegram_receipts r WHERE r.learner_id=l.id "
            "AND r.disposition='queued') AS last_interaction FROM learners l "
            "JOIN coach_state c ON c.learner_id=l.id ORDER BY l.joined_at,l.id LIMIT 100"
        ).fetchall()
        invites = conn.execute(
            "SELECT id,label,status,claimed_by,expires_at FROM invitations ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        queue = conn.execute(
            "SELECT learner_id,status,error_code,attempts,available_at,payload->>'type' AS kind,"
            "payload->>'kind' AS scheduled_kind,payload->>'text' AS submitted "
            "FROM jobs WHERE status IN ('pending','running','failed') "
            "ORDER BY available_at,sequence LIMIT 50"
        ).fetchall()
        deliveries = conn.execute(
            "SELECT learner_id,status,error_code,attempts,body->>'kind' AS kind "
            "FROM outbox WHERE status IN ('pending','failed') ORDER BY sequence LIMIT 50"
        ).fetchall()
        audit = conn.execute(
            "SELECT action,subject_id,created_at,'Telegram' AS source FROM access_audit "
            "UNION ALL SELECT action,subject_id,created_at,'Admin dashboard' AS source FROM admin_audit "
            "ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
        usage = {
            r["learner_id"]: r["n"]
            for r in conn.execute(
                "SELECT learner_id,count(*) AS n FROM ai_usage WHERE local_date=%s GROUP BY learner_id",
                (now.astimezone(IST).date(),),
            )
        }
    learners = []
    for row in rows:
        try:
            state = State.model_validate(row["body"])
            tasks = list(state.tasks.values())
            progress = {
                "assigned": len(tasks),
                "done": sum(t.status == "done" for t in tasks),
                "pending": sum(t.status == "pending" for t in tasks),
                "lessons_delivered": sum(bool(x.get("delivered_at")) for x in state.lessons.values()),
                "quizzes_completed": sum(a.status == "completed" for a in state.assessments.values()),
                "answers_recorded": sum(len(a.answers) for a in state.assessments.values()),
                "interviews_completed": sum(i.status == "completed" for i in state.interviews.values()),
                "minutes_logged": sum(t.actual_minutes for t in tasks if t.status == "done"),
                "paused": state.paused,
            }
        except ValidationError:
            progress = None
        learners.append(
            {
                "id": row["id"],
                "name": "You (owner)" if row["id"] == "owner" else row["display_name"] or "Learner",
                "status": row["status"],
                "joined_at": row["joined_at"].isoformat(),
                "last_interaction": row["last_interaction"].isoformat() if row["last_interaction"] else None,
                "progress": progress,
                "ai_operations_today": usage.get(row["id"], 0),
            }
        )

    for item in queue:
        submitted = item.pop("submitted") or ""
        name = (
            submitted.split(None, 1)[0].split("@")[0].removeprefix("/") if submitted.startswith("/") else ""
        )
        item["command"] = "/" + name if name in COMMANDS else None

    def dated(items):
        return [
            {k: v.isoformat() if isinstance(v, datetime) else v for k, v in item.items()} for item in items
        ]

    return {
        "learners": learners,
        "invitations": dated(invites),
        "jobs": dated(queue),
        "deliveries": deliveries,
        "audit": dated(audit),
        "owner_commands": OWNER_COMMANDS,
        "actions": {key: value[0] for key, value in ACTIONS.items()},
        "limits": {
            "members": runtime.config.max_learners,
            "ai_operations_per_learner": runtime.config.daily_ai_operations,
        },
        "generated_at": now.isoformat(),
        "privacy": "Only admission metadata and activity counts are shown. Private documents, questions, answers "
        "and feedback are excluded. Delivered videos are not measured as watched.",
    }


def register_admin(app, runtime_factory):
    from flask import jsonify, request

    from skillcoach.config import ConfigurationError
    from skillcoach.runtime import STORAGE_ERRORS

    def endpoint(function):
        @wraps(function)
        def handled(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except AdminDenied as exc:
                return jsonify(error=str(exc)), 403
            except AdminConflict as exc:
                return jsonify(error=str(exc)), 409
            except (ConfigurationError, ValidationError, *STORAGE_ERRORS):
                return jsonify(
                    error="Administration is temporarily unavailable. No unconfirmed action should be repeated with a new request ID."
                ), 503

        return handled

    def session_response(runtime, token, expires):
        result = jsonify(
            authenticated=True, csrf=csrf_token(token, runtime.config), expires_at=expires.isoformat()
        )
        result.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=SESSION_SECONDS,
            secure=True,
            httponly=True,
            samesite="Strict",
            path="/",
        )
        return result

    @app.get("/admin")
    def page():
        return app.send_static_file("admin.html")

    @app.get("/admin/session")
    @endpoint
    def current_session():
        runtime = runtime_factory()
        session, token = authenticate(request, runtime)
        return jsonify(
            authenticated=True,
            csrf=csrf_token(token, runtime.config),
            expires_at=session["expires_at"].isoformat(),
        )

    @app.post("/admin/session")
    @endpoint
    def telegram_session():
        same_origin(request)
        body = _json_body(request, {"init_data"})
        runtime = runtime_factory()
        token, expires = login_from_telegram(runtime, body["init_data"])
        return session_response(runtime, token, expires)

    @app.post("/admin/login/start")
    @endpoint
    def begin_login():
        same_origin(request)
        _json_body(request, set())
        runtime = runtime_factory()
        data, verifier = start_login(runtime)
        response = jsonify(data)
        response.set_cookie(
            LOGIN_COOKIE, verifier, max_age=300, secure=True, httponly=True, samesite="Strict", path="/"
        )
        return response

    @app.post("/admin/login/status")
    @endpoint
    def login_status():
        same_origin(request)
        _json_body(request, set())
        runtime = runtime_factory()
        result = exchange_login(runtime, request.cookies.get(LOGIN_COOKIE, ""))
        if result is None:
            return jsonify(authenticated=False, pending=True)
        response = session_response(runtime, *result)
        response.delete_cookie(LOGIN_COOKIE, secure=True, httponly=True, samesite="Strict", path="/")
        return response

    @app.post("/admin/logout")
    @endpoint
    def logout():
        runtime = runtime_factory()
        session, _ = authenticate(request, runtime, mutate=True)
        _json_body(request, set())
        with runtime.repo.connection() as conn:
            conn.execute(
                "UPDATE admin_sessions SET expires_at=now() WHERE token_hash=%s", (session["token_hash"],)
            )
        response = jsonify(logged_out=True)
        response.delete_cookie(SESSION_COOKIE, secure=True, httponly=True, samesite="Strict", path="/")
        return response

    @app.post("/admin/data")
    @endpoint
    def data():
        runtime = runtime_factory()
        authenticate(request, runtime, mutate=True)
        _json_body(request, set())
        return jsonify(admin_overview(runtime))

    @app.post("/admin/action/preview")
    @endpoint
    def preview():
        runtime = runtime_factory()
        session, _ = authenticate(request, runtime, mutate=True)
        body = _json_body(request, {"request_id", "action", "target", "arguments"})
        return jsonify(preview_action(runtime, session, body))

    @app.post("/admin/action/execute")
    @endpoint
    def execute():
        runtime = runtime_factory()
        session, _ = authenticate(request, runtime, mutate=True)
        body = _json_body(request, {"request_id", "confirmation"})
        return jsonify(execute_action(runtime, session, body))
