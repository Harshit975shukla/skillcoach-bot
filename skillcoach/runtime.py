import logging
import time

import psycopg
from pydantic import ValidationError

from skillcoach.clients import AI, Budget, ExternalError, Publisher, Telegram
from skillcoach.config import Config
from skillcoach.media import deliver_media
from skillcoach.service import Service
from skillcoach.storage import LostLease, Repository
from skillcoach.timeutil import IST, now_ist

log = logging.getLogger(__name__)


class Runtime:
    def __init__(self, config, repository=None, ai=None, telegram=None, publisher=None, clock=now_ist):
        self.config = config
        self.repo = repository or Repository(config.database_url)
        self.ai = ai or AI(config)
        self.telegram = telegram or Telegram(config)
        self.publisher = publisher or Publisher(config)
        self.clock = clock

    @classmethod
    def from_env(cls, *, webhook=False):
        return cls(Config.from_env(webhook=webhook))

    def process_one(self, budget: Budget) -> bool:
        token = self.repo.acquire("domain", 60)
        if not token:
            return False
        job = None
        try:
            job = self.repo.next_job(token)
            if job is None:
                return False
            revision, state = self.repo.read()
            result = Service(self.repo, self.ai, self.config, self.clock).apply(job, state, token, budget)
            self.repo.finish(job["id"], token, revision, *result)
            return True
        except (ExternalError, ValidationError, ValueError) as exc:
            code = exc.code if isinstance(exc, ExternalError) else "invalid_operation"
            log.warning("operation_failed code=%s", code)
            if job:
                self.repo.fail(job["id"], token, code)
            return job is not None
        finally:
            self.repo.release("domain", token)

    def deliver_one(self, budget: Budget, *, media=False) -> bool:
        token = self.repo.acquire("delivery", 240 if media else 60)
        if not token:
            return False
        try:
            item = self.repo.next_delivery(token, media=media)
            if item is None:
                return False
            body = item["body"]
            _, state = self.repo.read()
            if (
                body.get("scheduled")
                and (
                    state.paused
                    or body.get("scheduled_date") != self.clock().astimezone(IST).date().isoformat()
                )
            ) or (body.get("target") and body["target"] != state.target()):
                self.repo.delivery_result(item["id"], token, "suppressed")
                return True
            try:
                if body["kind"] == "text":
                    self.telegram.send(body["text"], budget, body.get("buttons"))
                elif body["kind"] == "media":
                    deliver_media(self.telegram, body, budget)
                elif body["kind"] == "export":
                    if "base" not in body:
                        body["base"] = self.publisher.prepare(budget)
                        self.repo.prepare_delivery(item["id"], token, body)
                    self.publisher.publish(body["document"], budget, body["base"])
                else:
                    raise ExternalError("invalid_outbox_kind", retryable=False)
            except ExternalError as exc:
                log.warning("delivery_failed kind=%s code=%s", body["kind"], exc.code)
                self.repo.delivery_result(item["id"], token, "failed", exc.code)
                return True
            self.repo.delivery_result(item["id"], token, "sent")
            return True
        finally:
            self.repo.release("delivery", token)

    def recover(self, *, limit=200, media=True, max_seconds=900):
        deadline = time.monotonic() + max_seconds
        for _ in range(limit):
            if time.monotonic() + 20 >= deadline:
                break
            if not self.process_one(Budget(20)):
                break
        for _ in range(limit):
            seconds = 210 if media else 20
            if time.monotonic() + seconds >= deadline:
                break
            if not self.deliver_one(Budget(seconds), media=media):
                break


STORAGE_ERRORS = (psycopg.Error, LostLease)
