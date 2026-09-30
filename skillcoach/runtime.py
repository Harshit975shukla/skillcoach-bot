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


WORKER_STEP_SECONDS = 90
QUIET_HOURS = (22, 7)


def silent_delivery(item_id: str, state, now) -> bool:
    """Only the first message of a job makes a sound, and nothing does during 22:00-07:00 local time."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    first = item_id.rsplit(":", 1)[-1] in ("0", "preparing", "failure")
    zone = IST
    if state.journey and state.journey.timezone:
        try:
            zone = ZoneInfo(state.journey.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            zone = IST
    hour = now.astimezone(zone).hour
    return not first or hour >= QUIET_HOURS[0] or hour < QUIET_HOURS[1]


def _left(budget: Budget) -> float:
    try:
        return budget.remaining()
    except ExternalError:
        return 0


class DeliveryDeferred(Exception):
    """Leave unsent work pending when the request lacks time for a safe network attempt."""


def require_send_budget(budget: Budget):
    try:
        if budget.remaining() < 8:
            raise DeliveryDeferred()
    except ExternalError as exc:
        if exc.code == "request_budget_exhausted":
            raise DeliveryDeferred() from None
        raise


class Runtime:
    def __init__(
        self,
        config,
        repository=None,
        ai=None,
        telegram=None,
        publisher=None,
        clock=now_ist,
        labs=None,
        email=None,
    ):
        from skillcoach.email_client import Email

        self.config = config
        self.repo = repository or Repository(config.database_url)
        self.repo.owner_id = config.owner_id
        self.ai = ai or AI(config)
        self.telegram = telegram or Telegram(config)
        self.publisher = publisher or Publisher(config)
        self.clock = clock
        self.labs = labs
        self.email = email or Email(config)

    @classmethod
    def from_env(cls, *, webhook=False):
        return cls(Config.from_env(webhook=webhook))

    def process_one(
        self, budget: Budget, *, proposal_for: str | None = None, document_job: str | None = None
    ) -> bool:
        # The fenced lease must outlive the step's network budget so validated work is never lost.
        token = self.repo.acquire("domain", max(60, int(_left(budget)) + 40))
        if not token:
            return False
        job = None
        scoped = self.repo
        try:
            job = (
                self.repo.next_job(token, document_job=document_job)
                if document_job is not None
                else (
                    self.repo.next_job(token, proposal_for=proposal_for)
                    if proposal_for is not None
                    else self.repo.next_job(token)
                )
            )
            if job is None:
                return False
            scoped = self.repo.for_learner(job.get("learner_id", "owner"))
            revision, state = scoped.read()
            result = Service(scoped, self.ai, self.config, self.clock, labs=self.labs).apply(
                job, state, token, budget
            )
            if self.config.web_mode:
                from skillcoach.web_channel import notification

                # In web mode, scheduled and mentor messages also send one email reminder.
                note = notification(job, result[1], self.config)
                if note:
                    result = (result[0], [*result[1], note], *result[2:])
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

    def followup_proposal(self, update_id: int, budget: Budget):
        self.followup(f"telegram:{update_id}", budget)

    def followup(self, key: str, budget: Budget):
        """Prepare a queued plan proposal that belongs to this interaction, if time allows."""
        try:
            if budget.remaining() < 12:
                return
        except ExternalError as exc:
            if exc.code == "request_budget_exhausted":
                return
            raise
        if self.process_one(budget, proposal_for=key):
            for _ in range(3):
                if not self.deliver_one(budget, media=False):
                    break

    def deliver_one(self, budget: Budget, *, media=False) -> bool:
        try:
            require_send_budget(budget)
        except DeliveryDeferred:
            return False
        web = self.config.web_mode
        token = self.repo.acquire("delivery", 240 if media else 60)
        if not token:
            return False
        try:
            # Web mode never renders video, so media placeholders are always ready.
            item = self.repo.next_delivery(token, media=media or web)
            if item is None:
                return False
            body = dict(item["body"])
            scoped = self.repo.for_learner(item.get("learner_id", "owner"))
            member = scoped.member()
            if member["generation"] != item.get("access_generation", 1) or (
                member["status"] != "active" and not item.get("access_notice")
            ):
                scoped.delivery_result(item["id"], token, "suppressed")
                return True
            _, state = scoped.read()
            if body.get("journey_plan_id"):
                from skillcoach.journey import approved_plan

                active = approved_plan(state)
                if not active or active.id != body["journey_plan_id"]:
                    # A revised plan carries already prepared lessons forward; their outbox remains valid.
                    if not active or body.get("journey_lesson_key") not in {
                        a.lesson_key for a in active.sessions if a.lesson_key
                    }:
                        scoped.delivery_result(item["id"], token, "suppressed")
                        return True
            if body["kind"] == "media" and "storyboard" in body:
                body["voice"] = bool(
                    body.get("voice", False) and state.voice and self.config.narration_enabled
                )
            if (
                body.get("scheduled")
                and (
                    state.paused
                    or body.get("scheduled_date") != self.clock().astimezone(IST).date().isoformat()
                )
            ) or (body.get("target") and body["target"] != state.target()):
                scoped.delivery_result(item["id"], token, "suppressed")
                return True
            if body["kind"] == "email":
                return self._deliver_email(scoped, item, body, token, budget)
            if web and body["kind"] in ("text", "media"):
                # The learner's private web inbox shows sent messages; nothing goes to Telegram.
                try:
                    scoped.ensure_delivery_authorized(item["id"], token)
                except MembershipChanged:
                    scoped.delivery_result(item["id"], token, "suppressed")
                    return True
                scoped.delivery_result(item["id"], token, "sent")
                return True
            telegram = self.telegram if scoped.is_owner else self.telegram.for_chat(scoped.recipient())
            # One sound per lesson, quiz or reply: follow-up parts and quiet-hour messages arrive silently.
            quiet = {"silent": True} if silent_delivery(item["id"], state, self.clock()) else {}
            if quiet and body["kind"] == "media":
                body["silent"] = True

            def authorize_send():
                scoped.ensure_delivery_authorized(item["id"], token)
                if body.get("voice") and not scoped.read()[1].voice:
                    raise DeliveryDeferred()
                require_send_budget(budget)

            try:
                if body["kind"] == "text":
                    authorize_send()
                    if body.get("format") == "md":
                        from skillcoach.formatting import plain, telegram_html

                        try:
                            telegram.send(
                                telegram_html(body["text"]),
                                budget,
                                body.get("buttons"),
                                parse_mode="HTML",
                                **quiet,
                            )
                        except ExternalError as exc:
                            # Telegram's 400 means nothing was sent, so one plain resend cannot duplicate.
                            if exc.code != "http_400":
                                raise
                            authorize_send()
                            telegram.send(plain(body["text"]), budget, body.get("buttons"), **quiet)
                    else:
                        telegram.send(body["text"], budget, body.get("buttons"), **quiet)
                elif body["kind"] == "media":
                    if "storyboard" in body:
                        from skillcoach.storyboard import Storyboard, asset_key

                        key = asset_key(
                            Storyboard.model_validate(body["storyboard"]),
                            scoped.learner_id,
                            voice=body.get("voice", False) and body["mode"] == "video",
                            shared_reviewed=body.get("shared_reviewed", False),
                            shared_library=body.get("shared_library", False),
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
                                key,
                                artifact,
                                token,
                                shared_reviewed=body.get("shared_reviewed", False),
                                shared_library=body.get("shared_library", False),
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
            except DeliveryDeferred:
                return False
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

    def _deliver_email(self, scoped, item, body, token, budget) -> bool:
        address = scoped.email_address(self.config.owner_email)
        if not address or not self.email.configured:
            scoped.delivery_result(item["id"], token, "suppressed")
            return True
        try:
            scoped.ensure_delivery_authorized(item["id"], token)
            require_send_budget(budget)
            self.email.send(address, body["subject"], body["text"], budget)
        except DeliveryDeferred:
            return False
        except MembershipChanged:
            scoped.delivery_result(item["id"], token, "suppressed")
            return True
        except ExternalError as exc:
            log.warning("delivery_failed kind=email code=%s", exc.code)
            scoped.delivery_result(item["id"], token, "failed", exc.code)
            return True
        scoped.delivery_result(item["id"], token, "sent")
        return True

    def recover(self, *, limit=200, media=True, max_seconds=900):
        deadline = time.monotonic() + max_seconds
        for _ in range(limit):
            if time.monotonic() + WORKER_STEP_SECONDS >= deadline:
                break
            with self.repo.session():
                # Background steps may wait for provider windows, repair invalid JSON and fall back.
                worked = self.process_one(Budget(WORKER_STEP_SECONDS))
                for _ in range(3):
                    can_render = media and time.monotonic() + 210 < deadline
                    # Background workers need room for DB authorization plus transport. Webhooks
                    # still use their own 20-second request budget and leave unsent work pending.
                    seconds = 210 if can_render else 45
                    if time.monotonic() + seconds >= deadline:
                        break
                    if not self.deliver_one(Budget(seconds), media=can_render):
                        break
                    worked = True
            if not worked:
                break


STORAGE_ERRORS = (psycopg.Error, LostLease)
