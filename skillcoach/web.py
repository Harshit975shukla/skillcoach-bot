import hmac
import logging

from flask import Flask, jsonify, request
from pydantic import ValidationError

from skillcoach.clients import Budget, ExternalError
from skillcoach.config import ConfigurationError
from skillcoach.runtime import STORAGE_ERRORS, Runtime

log = logging.getLogger(__name__)


def authorized_update(update, owner: int | None = None):
    if not isinstance(update, dict) or type(update.get("update_id")) is not int:
        return "invalid", None
    if update["update_id"] < 0:
        return "invalid", None
    if "edited_message" in update or "edited_channel_post" in update:
        return "ignored", None
    callback = update.get("callback_query")
    message = update.get("message")
    if callback is not None:
        if not isinstance(callback, dict):
            return "invalid", None
        message = callback.get("message")
        sender = callback.get("from", {})
    elif isinstance(message, dict):
        sender = message.get("from", {})
    else:
        return "ignored", None
    if not isinstance(message, dict) or not isinstance(sender, dict):
        return "denied", None
    chat = message.get("chat", {})
    if (
        not isinstance(chat, dict)
        or type(sender.get("id")) is not int
        or sender["id"] <= 0
        or chat.get("id") != sender["id"]
        or (owner is not None and sender["id"] != owner)
        or chat.get("type") != "private"
    ):
        return "denied", None
    if callback is not None:
        if not isinstance(callback.get("data"), str) or not isinstance(callback.get("id"), str):
            return "invalid", None
        if len(callback["data"].encode()) > 64:
            return "invalid", None
        return "action", {
            "type": "telegram",
            "callback": callback["data"],
            "callback_id": callback["id"],
            "actor_id": sender["id"],
        }
    text = message.get("text")
    if not isinstance(text, str):
        return "ignored", None
    if not text.strip() or len(text) > 16000:
        return "invalid", None
    return "action", {
        "type": "telegram",
        "text": text,
        "actor_id": sender["id"],
        "display_name": str(sender.get("first_name") or sender.get("username") or "")[:100],
    }


def create_app(runtime=None):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 128 * 1024

    @app.before_request
    def upload_limit():
        if request.path == "/app/documents/preview":
            request.max_content_length = 280 * 1024

    @app.errorhandler(413)
    def content_too_large(error):
        return jsonify(error="Request is too large. Document files must be at most 256 KB."), 413

    from skillcoach.admin import register_admin
    from skillcoach.dashboard import register_dashboard
    from skillcoach.web_routes import register_web

    register_dashboard(app, lambda: runtime or Runtime.from_env(webhook=True))
    register_admin(app, lambda: runtime or Runtime.from_env(webhook=True))
    register_web(app, lambda: runtime or Runtime.from_env(webhook=True))

    @app.get("/join")
    def join_page():
        return app.send_static_file("join.html")

    @app.get("/join/config")
    def join_config():
        from skillcoach.config import Config

        try:
            config = runtime.config if runtime else Config.from_env(webhook=True)
            # Public requests open the Telegram bot; in web mode people join only by invitation.
            if not config.access_requests_enabled or not config.bot_username or config.web_mode:
                return jsonify(available=False, telegram_url=None)
            return jsonify(available=True, telegram_url=f"https://t.me/{config.bot_username}?start=request")
        except ConfigurationError:
            return jsonify(error="Access requests are temporarily unavailable. Try again later."), 503

    @app.get("/")
    def health():
        return jsonify(service="skillcoach", live=True)

    @app.get("/cron/<kind>")
    def cron(kind):
        from skillcoach.scheduler import trigger

        body, status = trigger(kind, request.headers.get("Authorization", ""))
        return jsonify(body), status

    @app.get("/health/ready")
    def readiness():
        try:
            current = runtime or Runtime.from_env(webhook=True)
            supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if not current.config.webhook_secret or not hmac.compare_digest(
                current.config.webhook_secret.encode(), supplied.encode()
            ):
                return jsonify(error="unauthorized"), 403
            if current.config.owner_id <= 0:
                return jsonify(error="not_configured"), 503
            current.repo.read()
            from skillcoach.course_library import index

            courses = index()
            return jsonify(
                service="skillcoach",
                ready=True,
                private_storage=True,
                courses={
                    "version": courses["version"],
                    "topics": courses["total"],
                    "modules": len(courses["modules"]),
                },
            )
        except ConfigurationError:
            log.error("configuration_unavailable")
            return jsonify(error="not_configured"), 503
        except STORAGE_ERRORS:
            log.error("private_storage_unavailable")
            return jsonify(error="storage_unavailable"), 503
        except ValidationError:
            log.error("private_state_invalid")
            return jsonify(error="state_unavailable"), 503
        except ExternalError:
            log.error("course_content_unavailable")
            return jsonify(error="course_content_unavailable"), 503

    @app.post("/")
    @app.post("/api/webhook")
    def webhook():
        budget = Budget(20)
        try:
            current = runtime or Runtime.from_env(webhook=True)
            secret = current.config.webhook_secret
            supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if not secret or not hmac.compare_digest(secret.encode(), supplied.encode()):
                return jsonify(error="unauthorized"), 403
            if current.config.owner_id <= 0:
                return jsonify(error="not_configured"), 503
            update = request.get_json(silent=True)
            status, payload = authorized_update(update)
            if status == "invalid":
                return jsonify(error="invalid_update"), 400
            if status == "denied":
                return jsonify(error="unauthorized"), 403
            if status == "ignored":
                return jsonify(status="ignored"), 200
            with current.repo.session():
                admission = current.repo.accept_update(update["update_id"], payload, current.config)
                if payload.get("callback_id"):
                    try:
                        # Keep the optional callback toast from consuming the answer-processing budget.
                        current.telegram.acknowledge(payload["callback_id"], Budget(3))
                    except ExternalError as exc:
                        log.warning("callback_ack_failed code=%s", exc.code)
                current.process_one(budget)
                for _ in range(3):
                    if not current.deliver_one(budget, media=False):
                        break
                if admission == "queued":
                    current.followup_proposal(update["update_id"], budget)
            return jsonify(status="persisted", access=admission, recovery="scheduled-worker-or-retry"), 202
        except ConfigurationError:
            log.error("configuration_unavailable")
            return jsonify(error="not_configured"), 503
        except STORAGE_ERRORS:
            log.error("private_storage_unavailable")
            return jsonify(error="storage_unavailable"), 503
        except ExternalError as exc:
            log.warning("webhook_budget_or_transport code=%s", exc.code)
            return jsonify(error="retry_required"), 503

    return app
