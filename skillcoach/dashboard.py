"""Read-only Telegram Mini App authentication and learner-specific presentation."""

import hashlib
import hmac
import json
import math
import re
from urllib.parse import parse_qsl

from skillcoach.export import skill_summary, stats
from skillcoach.lab_flow import lab_view
from skillcoach.models import State
from skillcoach.timeutil import IST, monday

MAX_AUTH_AGE = 300


def learner_csrf(auth_hash, config):
    return hmac.new(
        config.webhook_secret.encode(), ("learner-documents:" + auth_hash).encode(), hashlib.sha256
    ).hexdigest()


class DashboardDenied(ValueError):
    pass


def verify_init_data(raw: str, bot_token: str, now: int) -> tuple[int, int]:
    if not isinstance(raw, str) or not raw or len(raw) > 8192:
        raise DashboardDenied("Open the dashboard from Telegram.")
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=20)
        fields = dict(pairs)
        if len(fields) != len(pairs):
            raise ValueError("Duplicate authentication fields")
        signature = fields.pop("hash")
        if not re.fullmatch(r"[0-9a-f]{64}", signature):
            raise ValueError("Invalid authentication signature")
        data = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid authentication signature")
        issued = int(fields["auth_date"])
        if issued > now + 15 or now - issued > MAX_AUTH_AGE:
            raise ValueError("Authentication expired")
        user = json.loads(fields["user"])
        if not isinstance(user, dict) or type(user.get("id")) is not int or not 0 < user["id"] < 2**52:
            raise ValueError("Invalid authenticated user")
        return user["id"], issued
    except (ValueError, KeyError, TypeError):
        raise DashboardDenied(
            "Access could not be verified. Close and reopen the dashboard from Telegram."
        ) from None


def learner_view(repo, actor: int, issued: int, now, auth_hash: str, *, narration_enabled=False, config=None):
    with repo.connection() as conn:
        row = conn.execute(
            "SELECT l.id,l.status,l.generation,l.updated_at,c.body FROM learners l "
            "JOIN coach_state c ON c.learner_id=l.id "
            "WHERE (l.id='owner' AND %s=%s) OR (l.telegram_id=%s AND l.id<>'owner') FOR SHARE OF l",
            (actor, repo.owner_id, actor),
        ).fetchone()
        if not row or row["status"] != "active":
            raise DashboardDenied("Access is not approved or has been revoked.")
        if row["id"] != "owner" and issued < math.ceil(row["updated_at"].timestamp()):
            raise DashboardDenied("Access changed. Close and reopen the dashboard from Telegram.")
        conn.execute("DELETE FROM dashboard_sessions WHERE expires_at<now()")
        conn.execute(
            "INSERT INTO dashboard_sessions(auth_hash,learner_id,access_generation,expires_at) "
            "VALUES (%s,%s,%s,to_timestamp(%s)) ON CONFLICT DO NOTHING",
            (auth_hash, row["id"], row["generation"], issued + MAX_AUTH_AGE),
        )
        session = conn.execute(
            "SELECT learner_id,access_generation FROM dashboard_sessions WHERE auth_hash=%s", (auth_hash,)
        ).fetchone()
        if session["learner_id"] != row["id"] or session["access_generation"] != row["generation"]:
            raise DashboardDenied("Your access changed. Reopen the dashboard from Telegram.")
        state = State.model_validate(row["body"])
    profile = state.profile
    today = now.astimezone(IST).date()
    plan = state.plans.get(monday(today).isoformat())
    pending = sorted(
        (t for t in state.tasks.values() if t.status == "pending"), key=lambda t: (t.assigned_date, t.id)
    )
    recent = sorted(
        (i for i in state.interviews.values() if i.completed_at and i.feedback),
        key=lambda i: i.completed_at,
        reverse=True,
    )
    from skillcoach.catalog import TOPICS

    journey = state.journey
    learning_plan = journey.plans.get(journey.proposed_id or journey.active_id) if journey else None
    return {
        "profile": {
            "name": profile.name if profile else "Your learning",
            "target_role": profile.target_role if profile else None,
            "level": profile.level if profile else None,
            "setup_complete": profile is not None,
        },
        "stats": stats(state, now),
        "preferences": {
            "paused": state.paused,
            "media": state.media,
            "voice": state.voice and narration_enabled,
            "narration_available": narration_enabled,
        },
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "skill": t.skill,
                "detail": t.detail,
                "assigned_date": t.assigned_date.isoformat(),
                "estimated_minutes": t.estimated_minutes,
            }
            for t in pending[:30]
        ],
        "plan": [{"date": day.isoformat(), "topic": topic} for day, topic in sorted(plan.days.items())]
        if plan
        else [],
        "skills": skill_summary(state, public=False),
        "recent_interviews": [
            {
                "question": i.question.question,
                "score": i.feedback.score,
                "feedback": i.feedback.feedback,
                "date": i.completed_at.isoformat(),
            }
            for i in recent[:5]
        ],
        "generated_at": now.isoformat(),
        "auth_expires_at": issued + MAX_AUTH_AGE,
        "private": True,
        "documents": {
            "resume_saved": bool(profile and profile.resume_text),
            "jd_saved": bool(profile and profile.jd_text),
            "can_update": profile is not None and state.focus is None,
        },
        "learning": {
            "stage": journey.stage if journey else "legacy",
            "shared": bool(journey and journey.consent_at),
            "active_plan_id": journey.active_id if journey else None,
            "plan": {
                "id": learning_plan.id,
                "version": learning_plan.version,
                "approved": learning_plan.approved_at is not None,
                "minutes": learning_plan.minutes,
                "rationale": learning_plan.rationale,
                "sessions": [
                    {
                        "day": i + 1,
                        "date": d.date.isoformat() if d.date else None,
                        "topic": TOPICS[d.topic_id][1],
                        "objective": d.objective,
                        "practice": d.practice,
                    }
                    for i, d in enumerate(learning_plan.sessions)
                ],
            }
            if learning_plan
            else None,
        },
        "labs": lab_view(state, config, now) if config is not None else None,
    }


def register_dashboard(app, runtime_factory):
    from flask import jsonify, request
    from pydantic import ValidationError

    from skillcoach.config import ConfigurationError
    from skillcoach.runtime import STORAGE_ERRORS

    @app.get("/app")
    def dashboard_page():
        return app.send_static_file("dashboard.html")

    @app.post("/app/data")
    def dashboard_data():
        try:
            runtime = runtime_factory()
            body = request.get_json(silent=True)
            if request.args or not isinstance(body, dict) or set(body) != {"init_data"}:
                raise DashboardDenied("Open this dashboard from the bot.")
            actor, issued = verify_init_data(
                body["init_data"], runtime.config.telegram_token, int(runtime.clock().timestamp())
            )
            digest = hashlib.sha256(body["init_data"].encode()).hexdigest()
            with runtime.repo.session():
                data = learner_view(
                    runtime.repo,
                    actor,
                    issued,
                    runtime.clock(),
                    digest,
                    narration_enabled=runtime.config.narration_enabled,
                    config=runtime.config,
                )
            data["bot_url"] = (
                f"https://t.me/{runtime.config.bot_username}" if runtime.config.bot_username else None
            )
            data["document_csrf"] = learner_csrf(digest, runtime.config)
            return jsonify(data)
        except DashboardDenied as exc:
            return jsonify(error=str(exc)), 403
        except (ConfigurationError, ValidationError, *STORAGE_ERRORS):
            return jsonify(error="Private progress is temporarily unavailable. Try Refresh shortly."), 503

    def document_identity(runtime):
        from skillcoach.admin_auth import same_origin

        same_origin(request)
        if request.args:
            raise DashboardDenied("Document requests cannot contain URL parameters.")
        raw = request.headers.get("X-Telegram-Init-Data", "")
        actor, issued = verify_init_data(raw, runtime.config.telegram_token, int(runtime.clock().timestamp()))
        digest = hashlib.sha256(raw.encode()).hexdigest()
        if not hmac.compare_digest(
            request.headers.get("X-CSRF-Token", ""), learner_csrf(digest, runtime.config)
        ):
            raise DashboardDenied("Refresh your personal dashboard before uploading.")
        # This also binds old launch data to the membership generation across revocation.
        learner_view(runtime.repo, actor, issued, runtime.clock(), digest)
        with runtime.repo.connection() as conn:
            row = conn.execute(
                "SELECT learner_id,access_generation FROM dashboard_sessions WHERE auth_hash=%s", (digest,)
            ).fetchone()
        return row["learner_id"], row["access_generation"], digest

    @app.post("/app/documents/preview")
    def preview_document():
        from skillcoach.admin_auth import AdminDenied
        from skillcoach.document_upload import preview
        from skillcoach.documents import MAX_FILE, DocumentError

        try:
            runtime = runtime_factory()
            with runtime.repo.session():
                identity = document_identity(runtime)
                if set(request.form) != {"request_id", "kind"} or set(request.files) != {"file"}:
                    raise DocumentError("Choose one PDF/TXT file and its document type.")
                if (
                    any(len(request.form.getlist(key)) != 1 for key in request.form)
                    or len(request.files.getlist("file")) != 1
                ):
                    raise DocumentError("Duplicate upload fields are not supported.")
                file = request.files["file"]
                result = preview(
                    runtime,
                    identity,
                    request.form["request_id"],
                    request.form["kind"],
                    file.stream.read(MAX_FILE + 1),
                    file.filename or "",
                )
            return jsonify(result)
        except (AdminDenied, DashboardDenied) as exc:
            return jsonify(error=str(exc)), 403
        except DocumentError as exc:
            return jsonify(error=str(exc)), 409
        except (ConfigurationError, ValidationError, *STORAGE_ERRORS):
            return jsonify(
                error="Upload temporarily unavailable. Retry with the same request, not a duplicate confirmation."
            ), 503

    @app.post("/app/documents/confirm")
    def confirm_document():
        from skillcoach.admin_auth import AdminDenied
        from skillcoach.clients import Budget, ExternalError
        from skillcoach.document_upload import confirm
        from skillcoach.documents import DocumentError

        budget = Budget(20)
        try:
            runtime = runtime_factory()
            with runtime.repo.session():
                identity = document_identity(runtime)
                body = request.get_json(silent=True)
                if not isinstance(body, dict) or set(body) != {"request_id", "confirmation", "choice"}:
                    raise DocumentError("Unexpected confirmation fields.")
                if any(not isinstance(value, str) for value in body.values()):
                    raise DocumentError("Invalid document confirmation.")
                result = confirm(runtime, identity, body["request_id"], body["confirmation"], body["choice"])
                if result.get("queued") and not result.get("duplicate") and budget.remaining() >= 8:
                    runtime.process_one(budget, document_job=f"document:{identity[0]}:{body['request_id']}")
                    for _ in range(3):
                        if not runtime.deliver_one(budget, media=False):
                            break
            return jsonify(result)
        except (AdminDenied, DashboardDenied) as exc:
            return jsonify(error=str(exc)), 403
        except DocumentError as exc:
            return jsonify(error=str(exc)), 409
        except (ConfigurationError, ValidationError, ExternalError, *STORAGE_ERRORS):
            return jsonify(
                error="Confirmation temporarily unavailable. Retry the same confirmation to check its result."
            ), 503

    @app.post("/app/labs/submit")
    def submit_lab():
        from skillcoach.admin_auth import AdminDenied
        from skillcoach.clients import Budget, ExternalError
        from skillcoach.lab_flow import LabSubmitError, queue_submission

        budget = Budget(20)
        try:
            runtime = runtime_factory()
            with runtime.repo.session():
                identity = document_identity(runtime)
                body = request.get_json(silent=True)
                if not isinstance(body, dict) or set(body) != {"request_id", "assignment_id", "url"}:
                    raise LabSubmitError("Unexpected lab submission fields.")
                if any(not isinstance(value, str) for value in body.values()):
                    raise LabSubmitError("Invalid lab submission.")
                result = queue_submission(
                    runtime, identity, body["request_id"], body["assignment_id"], body["url"].strip()
                )
                if not result["duplicate"] and budget.remaining() >= 8:
                    runtime.process_one(budget, document_job=f"labsubmit:{identity[0]}:{body['request_id']}")
                    for _ in range(3):
                        if not runtime.deliver_one(budget, media=False):
                            break
            return jsonify(result)
        except (AdminDenied, DashboardDenied) as exc:
            return jsonify(error=str(exc)), 403
        except LabSubmitError as exc:
            return jsonify(error=str(exc)), 409
        except (ConfigurationError, ValidationError, ExternalError, *STORAGE_ERRORS):
            return jsonify(
                error="Lab check temporarily unavailable. Retry the same submission to see its result."
            ), 503

    @app.after_request
    def private_headers(response):
        if request.path.startswith(
            ("/app", "/admin", "/join", "/static/join", "/static/dashboard", "/static/admin")
        ):
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["Pragma"] = "no-cache"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' https://telegram.org; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
                "frame-ancestors https://web.telegram.org https://*.telegram.org"
            )
        return response
