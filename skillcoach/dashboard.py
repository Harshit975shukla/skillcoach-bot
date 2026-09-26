"""Read-only Telegram Mini App authentication and learner-specific presentation."""

import hashlib
import hmac
import json
import math
import re
from urllib.parse import parse_qsl

from skillcoach.export import skill_summary, stats
from skillcoach.models import State
from skillcoach.timeutil import IST, monday

MAX_AUTH_AGE = 300


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


def learner_view(repo, actor: int, issued: int, now, auth_hash: str):
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
    return {
        "profile": {
            "name": profile.name if profile else "Your learning",
            "target_role": profile.target_role if profile else None,
            "level": profile.level if profile else None,
            "setup_complete": profile is not None,
        },
        "stats": stats(state, now),
        "preferences": {"paused": state.paused, "media": state.media, "voice": state.voice},
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
            return jsonify(learner_view(runtime.repo, actor, issued, runtime.clock(), digest))
        except DashboardDenied as exc:
            return jsonify(error=str(exc)), 403
        except (ConfigurationError, ValidationError, *STORAGE_ERRORS):
            return jsonify(error="Private progress is temporarily unavailable. Try Refresh shortly."), 503

    @app.after_request
    def private_headers(response):
        if request.path.startswith(("/app", "/static/dashboard")):
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
