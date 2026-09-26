import logging
import time

import psycopg
from pydantic import ValidationError

from skillcoach.clients import AI, Budget, ExternalError, Publisher, Telegram, WorkDeferred
from skillcoach.config import Config
from skillcoach.media import deliver_media, deliver_storyboard
from skillcoach.service import Service
from skillcoach.storage import LostLease, MembershipChanged, Repository
from skillcoach.timeutil import IST, now_ist

log = logging.getLogger(__name__)


class Runtime:
    def __init__(self, config, repository=None, ai=None, telegram=None, publisher=None, clock=now_ist):
        self.config = config
        self.repo = repository or Repository(config.database_url)
        self.repo.owner_id = config.owner_id
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
        scoped = self.repo
        try:
            job = self.repo.next_job(token)
            if job is None:
                return False
            scoped = self.repo.for_learner(job.get("learner_id", "owner"))
            revision, state = scoped.read()
            result = Service(scoped, self.ai, self.config, self.clock).apply(job, state, token, budget)
            scoped.finish(job["id"], token, revision, *result)
            return True
        except WorkDeferred:
            try:
                scoped.defer(job["id"], token)
            except MembershipChanged:
                log.info("learner_access_changed_partial_work_cancelled")
            return True
        except MembershipChanged:
            log.info("learner_access_changed_work_cancelled")
            return job is not None
        except (ExternalError, ValidationError, ValueError) as exc:
            code = exc.code if isinstance(exc, ExternalError) else "invalid_operation"
            log.warning("operation_failed code=%s", code)
            if job:
                try:
                    scoped.fail(job["id"], token, code)
                except MembershipChanged:
                    log.info("learner_access_changed_failed_work_cancelled")
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
            scoped = self.repo.for_learner(item.get("learner_id", "owner"))
            member = scoped.member()
            if member["generation"] != item.get("access_generation", 1) or (
                member["status"] != "active" and not item.get("access_notice")
            ):
                scoped.delivery_result(item["id"], token, "suppressed")
                return True
            _, state = scoped.read()
            if (
                body.get("scheduled")
                and (
                    state.paused
                    or body.get("scheduled_date") != self.clock().astimezone(IST).date().isoformat()
                )
            ) or (body.get("target") and body["target"] != state.target()):
                scoped.delivery_result(item["id"], token, "suppressed")
                return True
            telegram = self.telegram if scoped.is_owner else self.telegram.for_chat(scoped.recipient())

            def authorize_send():
                scoped.ensure_delivery_authorized(item["id"], token)

            try:
                if body["kind"] == "text":
                    authorize_send()
                    telegram.send(body["text"], budget, body.get("buttons"))
                elif body["kind"] == "media":
                    if "storyboard" in body:
                        from skillcoach.storyboard import Storyboard, asset_key

                        key = asset_key(
                            Storyboard.model_validate(body["storyboard"]),
                            scoped.learner_id,
                            voice=body.get("voice", True) and body["mode"] == "video",
                            shared_reviewed=body.get("shared_reviewed", False),
                        )
                        key += ":" + body["mode"]
                        cached = scoped.media_asset(key)
                        try:
                            artifact = deliver_storyboard(
                                telegram, body, budget, before_send=authorize_send, cached=cached
                            )
                        except ExternalError as exc:
                            if cached and exc.code == "http_400":
                                scoped.forget_media_asset(key)
                            raise
                        if not cached:
                            scoped.save_media_asset(
                                key, artifact, token, shared_reviewed=body.get("shared_reviewed", False)
                            )
                    else:
                        deliver_media(telegram, body, budget, before_send=authorize_send)
                elif body["kind"] == "export":
                    if not scoped.is_owner:
                        raise ExternalError("publication_requires_owner", retryable=False)
                    if "base" not in body:
                        authorize_send()
                        body["base"] = self.publisher.prepare(budget)
                        scoped.prepare_delivery(item["id"], token, body)
                    authorize_send()
                    self.publisher.publish(body["document"], budget, body["base"])
                else:
                    raise ExternalError("invalid_outbox_kind", retryable=False)
            except MembershipChanged:
                scoped.delivery_result(item["id"], token, "suppressed")
                return True
            except ExternalError as exc:
                log.warning("delivery_failed kind=%s code=%s", body["kind"], exc.code)
                scoped.delivery_result(item["id"], token, "failed", exc.code)
                return True
            scoped.delivery_result(item["id"], token, "sent")
            return True
        finally:
            self.repo.release("delivery", token)

    def recover(self, *, limit=200, media=True, max_seconds=900):
        deadline = time.monotonic() + max_seconds
        for _ in range(limit):
            if time.monotonic() + 20 >= deadline:
                break
            worked = self.process_one(Budget(20))
            for _ in range(3):
                can_render = media and time.monotonic() + 210 < deadline
                seconds = 210 if can_render else 20
                if time.monotonic() + seconds >= deadline:
                    break
                if not self.deliver_one(Budget(seconds), media=can_render):
                    break
                worked = True
            if not worked:
                break


STORAGE_ERRORS = (psycopg.Error, LostLease)
