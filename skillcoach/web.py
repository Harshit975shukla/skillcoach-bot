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

    @app.get("/")
    def health():
        return jsonify(service="skillcoach", live=True)

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
            return jsonify(service="skillcoach", ready=True, private_storage=True)
        except ConfigurationError:
            log.error("configuration_unavailable")
            return jsonify(error="not_configured"), 503
        except STORAGE_ERRORS:
            log.error("private_storage_unavailable")
            return jsonify(error="storage_unavailable"), 503
        except ValidationError:
            log.error("private_state_invalid")
            return jsonify(error="state_unavailable"), 503

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
            admission = current.repo.accept_update(update["update_id"], payload, current.config)
            if payload.get("callback_id"):
                try:
                    current.telegram.acknowledge(payload["callback_id"], budget)
                except ExternalError as exc:
                    log.warning("callback_ack_failed code=%s", exc.code)
            current.process_one(budget)
            for _ in range(3):
                if not current.deliver_one(budget, media=False):
                    break
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
