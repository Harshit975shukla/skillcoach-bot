"""Read-only Telegram Mini App authentication and learner-specific presentation."""

import hashlib
import hmac
import json
import math
import re
from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import parse_qsl

from skillcoach.clients import ExternalError
from skillcoach.export import skill_summary, stats
from skillcoach.lab_flow import lab_view
from skillcoach.models import State
from skillcoach.timeutil import IST, monday

MAX_AUTH_AGE = 300
# Learners read full lessons in the Mini App, so their signed launch stays valid for 30 minutes.
# Membership and revocation are still re-checked on every request.
LEARNER_AUTH_AGE = 1800


def learner_csrf(auth_hash, config):
    return hmac.new(
        config.webhook_secret.encode(), ("learner-documents:" + auth_hash).encode(), hashlib.sha256
    ).hexdigest()


class DashboardDenied(ValueError):
    pass


def verify_init_data(raw: str, bot_token: str, now: int, max_age: int = MAX_AUTH_AGE) -> tuple[int, int]:
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
        if issued > now + 15 or now - issued > max_age:
            raise ValueError("Authentication expired")
        user = json.loads(fields["user"])
        if not isinstance(user, dict) or type(user.get("id")) is not int or not 0 < user["id"] < 2**52:
            raise ValueError("Invalid authenticated user")
        return user["id"], issued
    except (ValueError, KeyError, TypeError):
        raise DashboardDenied(
            "Access could not be verified. Close and reopen the dashboard from Telegram."
        ) from None


def authorize_learner(repo, actor: int, issued: int, auth_hash: str):
    """Verify membership and bind the launch data to its access generation; returns (learner_id, state)."""
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
        launched = conn.execute(
            "INSERT INTO dashboard_sessions(auth_hash,learner_id,access_generation,expires_at) "
            "VALUES (%s,%s,%s,to_timestamp(%s)) ON CONFLICT DO NOTHING RETURNING auth_hash",
            (auth_hash, row["id"], row["generation"], issued + LEARNER_AUTH_AGE),
        ).fetchone()
        if launched:
            from skillcoach.adoption import record_usage

            # Counted once per Telegram launch; refreshes reuse the same launch.
            record_usage(conn, row["id"], "dashboard_open", datetime.fromtimestamp(issued, UTC))
        session = conn.execute(
            "SELECT learner_id,access_generation FROM dashboard_sessions WHERE auth_hash=%s", (auth_hash,)
        ).fetchone()
        if session["learner_id"] != row["id"] or session["access_generation"] != row["generation"]:
            raise DashboardDenied("Your access changed. Reopen the dashboard from Telegram.")
        return row["id"], State.model_validate(row["body"])


def learner_view(repo, actor: int, issued: int, now, auth_hash: str, *, narration_enabled=False, config=None):
    _, state = authorize_learner(repo, actor, issued, auth_hash)
    return progress_view(
        state, now, issued + LEARNER_AUTH_AGE, narration_enabled=narration_enabled, config=config
    )


def web_identity(runtime, request):
    """The learner signed in to /web, for the dashboard in web mode: the same cookie, CSRF token,
    same-origin check, access generation and email binding as /web. A learner ID in a URL or body
    is never accepted. Returns the learner, access generation, an identity hash bound to this browser
    session (for document previews), the session expiry and the learner's state."""
    from skillcoach.adoption import record_usage
    from skillcoach.web_channel import WebDenied, authenticate, csrf_token, digest

    if not runtime.config.web_mode:
        raise DashboardDenied("Open this dashboard from the bot.")
    try:
        session, token = authenticate(request, runtime, mutate=True)
    except WebDenied as exc:
        raise DashboardDenied(str(exc)) from None
    auth_hash = "web:" + digest(token)
    now = runtime.clock()
    with runtime.repo.connection() as conn:
        row = conn.execute(
            "SELECT l.id,l.status,l.generation,c.body FROM learners l JOIN coach_state c ON c.learner_id=l.id "
            "WHERE l.id=%s FOR SHARE OF l",
            (session["learner_id"],),
        ).fetchone()
        if not row or row["status"] != "active" or row["generation"] != session["access_generation"]:
            raise DashboardDenied("Your session ended. Sign in again with your email.")
        conn.execute("DELETE FROM dashboard_sessions WHERE expires_at<%s", (now,))
        opened = conn.execute(
            "INSERT INTO dashboard_sessions(auth_hash,learner_id,access_generation,expires_at) "
            "VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING auth_hash",
            (auth_hash, row["id"], row["generation"], session["expires_at"]),
        ).fetchone()
        if opened:
            # Counted once per web session, like once per Telegram launch.
            record_usage(conn, row["id"], "dashboard_open", now)

    return SimpleNamespace(
        learner=row["id"],
        generation=row["generation"],
        auth_hash=auth_hash,
        expires_at=int(session["expires_at"].timestamp()),
        state=State.model_validate(row["body"]),
        csrf=csrf_token(runtime.config, token),
    )


def progress_view(state, now, auth_expires_at: int, *, narration_enabled=False, config=None):
    from skillcoach.capstones import CAPSTONES
    from skillcoach.certifications import cert_view
    from skillcoach.course_library import index
    from skillcoach.formatting import md_blocks
    from skillcoach.lesson_delivery import display_name, recent_lessons
    from skillcoach.mastery import mastery_view
    from skillcoach.progress import summary, today_view
    from skillcoach.quizzes import catalogue
    from skillcoach.resources import library_view
    from skillcoach.timeutil import study_day

    profile = state.profile
    today = now.astimezone(IST).date()
    plan = state.plans.get(monday(today).isoformat())
    # Newest practice first; exercises older than a week stay available as optional practice.
    pending = sorted(
        (t for t in state.tasks.values() if t.status == "pending"),
        key=lambda t: (t.assigned_date, t.origin),
        reverse=True,
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
        "progress": summary(state, now),
        "today": today_view(state, now),
        "mastery": mastery_view(state, now),
        "certification": cert_view(state, now),
        "capstones": [
            {
                "id": c.id,
                "title": c.title,
                "hours": c.hours,
                "goal": c.goal,
                "status": state.capstones[c.id].status if c.id in state.capstones else "not_started",
                "verified_at": state.capstones[c.id].verified_at.isoformat()
                if c.id in state.capstones and state.capstones[c.id].verified_at
                else None,
            }
            for c in CAPSTONES.values()
        ],
        "portfolio": {
            "enabled": bool(state.portfolio and state.portfolio.enabled and state.portfolio.slug),
            "path": f"/portfolio/{state.portfolio.slug}"
            if state.portfolio and state.portfolio.enabled and state.portfolio.slug
            else None,
        },
        "preferences": {
            "paused": state.paused,
            "media": state.media,
            "voice": state.voice and narration_enabled,
            "narration_available": narration_enabled,
        },
        "tasks": [
            {
                "id": t.id,
                "title": display_name(t.title),
                "skill": t.skill,
                "detail": t.detail,
                "detail_blocks": md_blocks(t.detail),
                "assigned_date": t.assigned_date.isoformat(),
                "estimated_minutes": t.estimated_minutes,
                "earlier": (study_day(now) - t.assigned_date).days > 7,
            }
            for t in pending[:30]
        ],
        "plan": [{"date": day.isoformat(), "topic": topic} for day, topic in sorted(plan.days.items())]
        if plan
        else [],
        "skills": skill_summary(state, public=False),
        "lessons": recent_lessons(state),
        "quizzes": catalogue(state, now)[:30],
        "resources": library_view(),
        "courses": index(),
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
        "auth_expires_at": auth_expires_at,
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

    def identify(runtime, body):
        """(learner, state, expiry) from Telegram launch data in the body, or else, in web mode only,
        from the signed-in /web session. Telegram mode keeps requiring launch data."""
        if "init_data" in body:
            actor, issued = verify_init_data(
                body["init_data"],
                runtime.config.telegram_token,
                int(runtime.clock().timestamp()),
                LEARNER_AUTH_AGE,
            )
            digest = hashlib.sha256(body["init_data"].encode()).hexdigest()
            learner, state = authorize_learner(runtime.repo, actor, issued, digest)
            return learner, state, issued + LEARNER_AUTH_AGE
        who = web_identity(runtime, request)
        return who.learner, who.state, who.expires_at

    @app.post("/app/data")
    def dashboard_data():
        try:
            runtime = runtime_factory()
            body = request.get_json(silent=True)
            if request.args or not isinstance(body, dict) or set(body) not in ({"init_data"}, set()):
                raise DashboardDenied("Open this dashboard from the bot.")
            if not body:
                # Web mode: the learner signed in to /web; nothing in the request says who.
                with runtime.repo.session():
                    who = web_identity(runtime, request)
                    data = progress_view(
                        who.state,
                        runtime.clock(),
                        who.expires_at,
                        narration_enabled=runtime.config.narration_enabled,
                        config=runtime.config,
                    )
                data.update(bot_url=None, web=True, document_csrf=who.csrf)
                return jsonify(data)
            actor, issued = verify_init_data(
                body["init_data"],
                runtime.config.telegram_token,
                int(runtime.clock().timestamp()),
                LEARNER_AUTH_AGE,
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
        except (ConfigurationError, ValidationError, ExternalError, *STORAGE_ERRORS):
            return jsonify(error="Private progress is temporarily unavailable. Try Refresh shortly."), 503

    def count_open(runtime, learner, event):
        runtime.repo.for_learner(learner).record_usage(event, runtime.clock())

    @app.post("/app/course")
    def dashboard_course():
        from skillcoach.catalog import TOPICS
        from skillcoach.course_library import page

        try:
            runtime = runtime_factory()
            body = request.get_json(silent=True)
            if (
                request.args
                or not isinstance(body, dict)
                or set(body) not in ({"init_data", "topic"}, {"topic"})
            ):
                raise DashboardDenied("Open this course from the bot.")
            with runtime.repo.session():
                learner, _, expires_at = identify(runtime, body)
                if not isinstance(body["topic"], str) or body["topic"] not in TOPICS:
                    return jsonify(error="Choose a topic from the lesson library."), 404
                count_open(runtime, learner, "course_page")
            return jsonify(lesson=page(body["topic"]), auth_expires_at=expires_at, private=True)
        except DashboardDenied as exc:
            return jsonify(error=str(exc)), 403
        except (ConfigurationError, ValidationError, ExternalError, *STORAGE_ERRORS):
            return jsonify(error="This stored course is unavailable. Try again shortly."), 503

    @app.post("/app/lesson")
    def dashboard_lesson():
        from skillcoach.lesson_delivery import LESSON_ID, page

        try:
            runtime = runtime_factory()
            body = request.get_json(silent=True)
            if (
                request.args
                or not isinstance(body, dict)
                or set(body) not in ({"init_data", "lesson"}, {"lesson"})
            ):
                raise DashboardDenied("Open this lesson from the bot.")
            if not isinstance(body["lesson"], str) or not LESSON_ID.fullmatch(body["lesson"]):
                return jsonify(error="That lesson link is not valid."), 404
            with runtime.repo.session():
                learner, state, expires_at = identify(runtime, body)
                data = page(runtime.repo.for_learner(learner), state, body["lesson"], runtime.clock())
                if data is None:
                    return jsonify(error="This lesson is not in your learning history."), 404
                count_open(runtime, learner, "lesson_page")
            return jsonify(lesson=data, auth_expires_at=expires_at, private=True)
        except DashboardDenied as exc:
            return jsonify(error=str(exc)), 403
        except (ConfigurationError, ValidationError, ExternalError, *STORAGE_ERRORS):
            return jsonify(error="This lesson is temporarily unavailable. Try again shortly."), 503

    def document_identity(runtime):
        from skillcoach.admin_auth import same_origin

        raw = request.headers.get("X-Telegram-Init-Data", "")
        if not raw and runtime.config.web_mode:
            # Web mode: the /web session, its CSRF token and same-origin check, bound to this browser.
            who = web_identity(runtime, request)
            return who.learner, who.generation, who.auth_hash
        same_origin(request)
        if request.args:
            raise DashboardDenied("Document requests cannot contain URL parameters.")
        actor, issued = verify_init_data(
            raw, runtime.config.telegram_token, int(runtime.clock().timestamp()), LEARNER_AUTH_AGE
        )
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

    @app.post("/app/exercise")
    def exercise_action():
        from skillcoach.admin_auth import AdminDenied
        from skillcoach.clients import Budget, ExternalError
        from skillcoach.exercises import ExerciseError, queue

        budget = Budget(20)
        try:
            runtime = runtime_factory()
            with runtime.repo.session():
                identity = document_identity(runtime)
                body = request.get_json(silent=True)
                if not isinstance(body, dict) or set(body) != {"request_id", "task_id", "action"}:
                    raise ExerciseError("Unexpected exercise fields.")
                if any(not isinstance(value, str) for value in body.values()):
                    raise ExerciseError("Invalid exercise update.")
                result = queue(runtime, identity, body["request_id"], body["task_id"], body["action"])
                if not result["duplicate"] and budget.remaining() >= 8:
                    runtime.process_one(budget, document_job=result["job"])
            return jsonify(queued=True, duplicate=result["duplicate"])
        except (AdminDenied, DashboardDenied) as exc:
            return jsonify(error=str(exc)), 403
        except ExerciseError as exc:
            return jsonify(error=str(exc)), 409
        except (ConfigurationError, ValidationError, ExternalError, *STORAGE_ERRORS):
            return jsonify(error="Exercise update temporarily unavailable. Retry the same tap."), 503

    @app.get("/portfolio/<slug>")
    def public_portfolio(slug):
        from skillcoach.capstones import portfolio_data, portfolio_html

        if not re.fullmatch(r"[A-Za-z0-9_-]{16}", slug):
            return "Not found", 404
        try:
            runtime = runtime_factory()
            with runtime.repo.connection() as conn:
                row = conn.execute(
                    "SELECT c.body FROM learners l JOIN coach_state c ON c.learner_id=l.id "
                    "WHERE l.status='active' AND c.body->'portfolio'->>'slug'=%s "
                    "AND c.body->'portfolio'->>'enabled'='true'",
                    (slug,),
                ).fetchone()
            if row is None:
                return "Not found", 404
            state = State.model_validate(row["body"])
            return (
                portfolio_html(portfolio_data(state, runtime.clock())),
                200,
                {"Content-Type": "text/html; charset=utf-8"},
            )
        except (ConfigurationError, ValidationError, *STORAGE_ERRORS):
            return "Portfolio temporarily unavailable.", 503

    @app.after_request
    def private_headers(response):
        if request.path.startswith(
            (
                "/app",
                "/admin",
                "/join",
                "/static/join",
                "/static/dashboard",
                "/static/admin",
                "/portfolio",
                "/web",
                "/static/web",
            )
        ):
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["Pragma"] = "no-cache"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Content-Type-Options"] = "nosniff"
            # The web app is never framed and runs no third-party script; Telegram Mini App pages may
            # be embedded by Telegram only and load Telegram's script.
            web = request.path.startswith(("/web", "/static/web"))
            ancestors = "'none'" if web else "https://web.telegram.org https://*.telegram.org"
            scripts = "'self'" if web else "'self' https://telegram.org"
            response.headers["Content-Security-Policy"] = (
                f"default-src 'self'; script-src {scripts}; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
                "frame-ancestors " + ancestors
            )
        return response
