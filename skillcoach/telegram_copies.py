"""Telegram copies of coaching messages in both mode (DELIVERY_CHANNEL=both).

The web inbox stays the complete record: every message reaches it first, exactly as in web mode. When
a message of a scheduled lesson, quiz, review, mentor note or the learner's own Telegram request reaches
the inbox, the same transaction may add one Telegram copy, but only for a person who has messaged the
configured bot and only while neither the bot nor that person is paused. The learner's own web requests
are answered on the web only. Copies wait for the earlier messages of their job, go out in order among
themselves and never hold back the inbox, email or push.

Right before each copy is sent, the learner's access, the person's start of the configured bot, the bot's
and the person's health, whether the message still applies (current question, plan, pause, scheduled
day) and the current narration choice are checked again. Nothing is locked while sending. A stored
video or still is uploaded from its private copy; one that is no longer kept, was not made, or is
narrated while narration is now off becomes an honest text note instead.

Email reminders wait for the Telegram outcome of their job and go out only when no copy was accepted by
Telegram (accepted by Telegram is not the same as read by the learner).

Health: a rejected token (401) or an explicit frozen-bot error pauses the bot's copies; blocked, not
started, deactivated, unknown chat or an invalid peer pauses that one person. A person's pause ends when
they message the bot again; one person's message never ends the bot's pause. The bot's pause ends only
through an operator restoration, after the owner has messaged the bot, followed by a confirmed copy to
the owner. Copies skipped while paused are never re-sent.
"""

import logging
from datetime import timedelta

from psycopg.types.json import Jsonb

from skillcoach.clients import ExternalError
from skillcoach.storage import MembershipChanged
from skillcoach.timeutil import IST

log = logging.getLogger(__name__)

COPY = ":tg"
GLOBAL_CODES = frozenset({"credentials_rejected", "bot_frozen"})
RECIPIENT_CODES = frozenset(
    {"blocked", "deactivated", "not_started", "chat_not_found", "peer_invalid", "forbidden"}
)
HOLD_SECONDS = 1800  # an email reminder waits at most this long after its lesson for the Telegram copy
POSTPONE_SECONDS = 60
CAPTION_LIMIT = 1024
NOT_KEPT = "🎬 This step's video is no longer kept. Open SkillCoach for the lesson page walkthrough."
NARRATED = (
    "🎬 This step's video has synthetic narration, which is now turned off, so it is not sent here. "
    "Open SkillCoach for the lesson page walkthrough."
)
PAUSED = {
    "credentials_rejected": "Telegram rejected the bot's credentials",
    "bot_frozen": "Telegram reported the bot as frozen",
}


# Who and whether -------------------------------------------------------------------------------


def recipient(conn, config, learner_id: str) -> int | None:
    if learner_id == "owner":
        return config.owner_id if config.owner_id > 0 else None
    row = conn.execute("SELECT telegram_id FROM learners WHERE id=%s", (learner_id,)).fetchone()
    return row["telegram_id"] if row and row["telegram_id"] else None


def blocked(conn, config, learner_id: str) -> str | None:
    """None when a copy may go to this learner now, else why not (a fixed code)."""
    bot = config.telegram_namespace
    telegram_id = recipient(conn, config, learner_id)
    if not telegram_id:
        return "no_telegram"
    started = conn.execute(
        "SELECT 1 FROM telegram_starts WHERE bot_id=%s AND telegram_id=%s AND learner_id=%s",
        (bot, telegram_id, learner_id),
    ).fetchone()
    if not started:
        return "not_started"
    rows = conn.execute(
        "SELECT learner_id, state FROM telegram_pauses WHERE bot_id=%s AND state<>'cleared' "
        "AND (learner_id IS NULL OR learner_id=%s)",
        (bot, learner_id),
    ).fetchall()
    whole = next((row["state"] for row in rows if row["learner_id"] is None), None)
    # On probation only the owner gets copies, until one is confirmed.
    if whole == "paused" or (whole == "probation" and learner_id != "owner"):
        return "telegram_paused"
    if any(row["learner_id"] == learner_id for row in rows):
        return "recipient_paused"
    return None


def source_bot(job_id: str) -> int | None:
    """The receipt namespace of the bot a Telegram request came through (see access.telegram_key:
    'telegram:<update>' is namespace 0, 'telegram:<ns>:<update>' another bot), or None for work that
    did not come from Telegram (schedules, mentor notes, web requests)."""
    parts = (job_id or "").split(":")
    if len(parts) < 2 or parts[0] != "telegram" or not parts[1].isdigit():
        return None
    return int(parts[1]) if len(parts) >= 3 and parts[2].isdigit() else 0


def create_copy(conn, config, learner_id: str, key: str) -> bool:
    """Inside the transaction that puts message `key` in the web inbox: add its Telegram copy if due."""
    if not config.telegram_copies:
        return False
    item = conn.execute(
        "SELECT o.*, j.payload->>'channel' AS channel FROM outbox o JOIN jobs j ON j.id=o.job_id "
        "WHERE o.id=%s AND o.learner_id=%s",
        (key, learner_id),
    ).fetchone()
    if not item or item["body"].get("kind") not in ("text", "media") or item["channel"] == "web":
        return False
    # A reply to a request made through another bot stays on the web: it never moves to this bot.
    origin = source_bot(item["job_id"])
    if origin is not None and origin != config.telegram_namespace:
        return False
    if blocked(conn, config, learner_id):
        return False
    created = conn.execute(
        "INSERT INTO outbox(id,job_id,body,learner_id,access_generation,access_notice) "
        "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id",
        (
            key + COPY,
            item["job_id"],
            # Pinned to the bot it was made for: a later, different bot never sends it.
            Jsonb({"kind": "telegram", "copy_of": key, "bot": config.telegram_namespace}),
            learner_id,
            item["access_generation"],
            item["access_notice"],
        ),
    ).fetchone()
    return created is not None


def telegram_prompt(value, config):
    """The last question shown in Telegram, if it was shown by the configured bot."""
    if isinstance(value, dict) and value.get("bot") == config.telegram_namespace:
        return value.get("target")
    return None


# Health -----------------------------------------------------------------------------------------


def pause(conn, config, learner_id: str | None, code: str) -> int | None:
    """Pause copies for the whole bot (learner_id None) or one person. Returns a new pause's ID."""
    bot = config.telegram_namespace
    if learner_id is None:
        # A failed confirmation sends a restoration back to paused.
        conn.execute(
            "UPDATE telegram_pauses SET state='paused', code=%s, since=now() "
            "WHERE bot_id=%s AND learner_id IS NULL AND state='probation'",
            (code, bot),
        )
    row = conn.execute(
        "INSERT INTO telegram_pauses(bot_id,learner_id,code,state) SELECT %s,%s,%s,'paused' "
        "WHERE NOT EXISTS (SELECT 1 FROM telegram_pauses WHERE bot_id=%s "
        "AND coalesce(learner_id,'')=coalesce(%s,'') AND state<>'cleared') "
        "ON CONFLICT DO NOTHING RETURNING id",
        (bot, learner_id, code, bot, learner_id),
    ).fetchone()
    return row["id"] if row else None


def notify_owner(conn, pause_id: int, code: str):
    """One web inbox notice to the owner per bot-wide pause; it states only what Telegram reported."""
    owner = conn.execute("SELECT generation FROM learners WHERE id='owner'").fetchone()
    if not owner:
        return
    job = f"telegram-health:{pause_id}"
    conn.execute(
        "INSERT INTO jobs(id,payload,learner_id,access_generation,status) VALUES (%s,%s,'owner',%s,'done') "
        "ON CONFLICT DO NOTHING",
        (job, Jsonb({"type": "telegram_health", "code": code}), owner["generation"]),
    )
    text = (
        f"Telegram copies are paused: {PAUSED.get(code, 'Telegram refused the bot')}. "
        "Lessons, quizzes and replies continue here, and email reminders go out instead. Nothing missed "
        "is re-sent to Telegram. Copies resume only after an operator restoration and a confirmed reply "
        "to you in Telegram."
    )
    conn.execute(
        "INSERT INTO outbox(id,job_id,body,learner_id,access_generation) VALUES (%s,%s,%s,'owner',%s) "
        "ON CONFLICT DO NOTHING",
        (job + ":0", job, Jsonb({"kind": "text", "text": text}), owner["generation"]),
    )


def may_acknowledge(repo, config, actor: int) -> bool:
    """Whether the webhook may answer a button tap's loading indicator through Telegram. Optional
    transport only: the tap itself is always processed. No contact during a bot-wide pause, and only
    the owner's taps while a restoration is on probation."""
    if not config.telegram_copies:
        return True
    with repo.connection(readonly=True) as conn:
        whole = conn.execute(
            "SELECT state FROM telegram_pauses WHERE bot_id=%s AND learner_id IS NULL AND state<>'cleared'",
            (config.telegram_namespace,),
        ).fetchone()
    if not whole:
        return True
    return whole["state"] == "probation" and actor == config.owner_id


def learner_view(repo, config, learner_id: str) -> str | None:
    """One line for the learner's own /status: their Telegram copies and the bot's state, nothing about
    anyone else. None outside both mode."""
    if not config.telegram_copies:
        return None
    with repo.connection(readonly=True) as conn:
        reason = blocked(conn, config, learner_id)
        own = conn.execute(
            "SELECT code FROM telegram_pauses WHERE bot_id=%s AND learner_id=%s AND state<>'cleared'",
            (config.telegram_namespace, learner_id),
        ).fetchone()
    if reason is None:
        return (
            "Telegram copies: on. Everything also stays here; email reminders go out if Telegram misses one."
        )
    if reason == "telegram_paused":
        return "Telegram copies: paused for everyone. Everything continues here and by email reminders."
    if reason == "recipient_paused":
        return (
            f"Telegram copies: paused for you (Telegram reported: {own['code'] if own else 'a delivery problem'}). "
            "Send the bot any message to resume them; meanwhile email reminders go out."
        )
    if reason == "not_started":
        return "Telegram copies: off until you send the bot a message. Email reminders go out meanwhile."
    return "Telegram copies: off (no Telegram account is linked). Email reminders go out instead."


def status(repo, config) -> dict:
    """Non-sensitive Telegram copy health for operators: states and counts, never IDs or text."""
    bot = config.telegram_namespace
    with repo.connection(readonly=True) as conn:
        whole = conn.execute(
            "SELECT code, state, since FROM telegram_pauses WHERE bot_id=%s AND learner_id IS NULL "
            "AND state<>'cleared'",
            (bot,),
        ).fetchone()
        people = conn.execute(
            "SELECT code, count(*) AS n FROM telegram_pauses WHERE bot_id=%s AND learner_id IS NOT NULL "
            "AND state<>'cleared' GROUP BY code ORDER BY code",
            (bot,),
        ).fetchall()
        started = conn.execute(
            "SELECT count(*) AS n FROM telegram_starts s JOIN learners l ON l.id=s.learner_id "
            "WHERE s.bot_id=%s AND l.status='active'",
            (bot,),
        ).fetchone()["n"]
        copies = conn.execute(
            "SELECT status, count(*) AS n FROM outbox WHERE body->>'kind'='telegram' "
            "AND body->>'bot'=%s GROUP BY status ORDER BY status",
            (str(bot),),
        ).fetchall()
    return {
        "copies_enabled": config.telegram_copies,
        "bot": {"state": whole["state"], "code": whole["code"], "since": whole["since"].isoformat()}
        if whole
        else {"state": "active"},
        "people_paused": {row["code"]: row["n"] for row in people},
        "active_learners_started": started,
        "copies": {row["status"]: row["n"] for row in copies},
    }


def restore(repo, config) -> dict:
    """Operator restoration of a bot-wide pause, after the owner has messaged the configured bot since
    it began. Copies then go to the owner only, until one is accepted by Telegram ('probation')."""
    bot = config.telegram_namespace
    with repo.connection() as conn:
        whole = conn.execute(
            "SELECT * FROM telegram_pauses WHERE bot_id=%s AND learner_id IS NULL AND state='paused' FOR UPDATE",
            (bot,),
        ).fetchone()
        if not whole:
            return {"restored": False, "reason": "no_bot_pause"}
        inbound = conn.execute(
            "SELECT last_inbound_at FROM telegram_starts WHERE bot_id=%s AND learner_id='owner' "
            "ORDER BY last_inbound_at DESC LIMIT 1",
            (bot,),
        ).fetchone()
        if not inbound or inbound["last_inbound_at"] <= whole["since"]:
            return {"restored": False, "reason": "owner_message_to_bot_required_after_pause"}
        conn.execute("UPDATE telegram_pauses SET state='probation' WHERE id=%s", (whole["id"],))
    return {"restored": True, "state": "probation", "next": "the next copy to the owner confirms it"}


# Email reminders in both mode -------------------------------------------------------------------


def email_decision(repo, item, now) -> str:
    """The job's one email reminder in both mode, decided from what happened to its Telegram copies:
    'suppress' only when every message of the job that reached the inbox also reached Telegram (or its
    copy was skipped because the learner had already moved on); 'wait' while a copy may still be
    accepted; otherwise 'send'. One accepted introduction is not delivery of the whole lesson or quiz."""
    with repo.connection(readonly=True) as conn:
        content = conn.execute(
            "SELECT id, delivered_at FROM outbox WHERE job_id=%s AND learner_id=%s "
            "AND body->>'kind' IN ('text','media') AND status='sent'",
            (item["job_id"], item["learner_id"]),
        ).fetchall()
        copies = {
            row["copy_of"]: row
            for row in conn.execute(
                "SELECT body->>'copy_of' AS copy_of, status, attempts, error_code FROM outbox "
                "WHERE job_id=%s AND learner_id=%s AND body->>'kind'='telegram'",
                (item["job_id"], item["learner_id"]),
            )
        }
    if not copies:
        return "send"
    if any(
        copy["status"] == "pending" or (copy["status"] == "failed" and copy["attempts"] < 5)
        for copy in copies.values()
    ):
        last = max((row["delivered_at"] for row in content if row["delivered_at"]), default=None)
        return "send" if last is not None and last < now - timedelta(seconds=HOLD_SECONDS) else "wait"
    covered = all(
        row["id"] in copies
        and (
            copies[row["id"]]["status"] == "sent"
            or (copies[row["id"]]["status"] == "suppressed" and copies[row["id"]]["error_code"] == "outdated")
        )
        for row in content
    )
    accepted = any(copy["status"] == "sent" for copy in copies.values())
    return "suppress" if covered and accepted else "send"


# Sending ----------------------------------------------------------------------------------------


def _lock(conn, scoped):
    """Take the learner's locks in domain order (learner, coaching state) before touching outbox rows,
    as /retry and /cancel do, so finalizing a copy can wait for them but never deadlock with them."""
    conn.execute("SELECT 1 FROM learners WHERE id=%s FOR UPDATE", (scoped.learner_id,))
    conn.execute("SELECT 1 FROM coach_state WHERE learner_id=%s FOR UPDATE", (scoped.learner_id,))


def _release_email(conn, item):
    """A copy reached its final outcome: let the job's held email reminder decide now."""
    conn.execute(
        "UPDATE outbox SET available_at=now() WHERE job_id=%s AND learner_id=%s AND body->>'kind'='email' "
        "AND status IN ('pending','failed')",
        (item["job_id"], item["learner_id"]),
    )


def _finish(scoped, item, token, status, code=None, *, final=True):
    with scoped.connection() as conn:
        scoped._fence(conn, "delivery", token)
        _lock(conn, scoped)
        scoped._finish_delivery(conn, item["id"], status, code, final=final)
        spent = conn.execute(
            "SELECT attempts >= 5 AS spent FROM outbox WHERE id=%s AND learner_id=%s",
            (item["id"], scoped.learner_id),
        ).fetchone()
        if status != "failed" or final or (spent and spent["spent"]):
            _release_email(conn, item)


def _caption(note: dict) -> str:
    text = "\n".join(
        part for part in [str(note.get("text", "")), *map(str, note.get("labels") or [])] if part
    )
    return text[:CAPTION_LIMIT]


class _Skip(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _check(runtime, scoped, item, body, token, today):
    """The current context for this copy, or raise _Skip / MembershipChanged. Run immediately before
    every network call, so each send uses the newest state."""
    from skillcoach.models import State
    from skillcoach.runtime import stale_delivery

    config = runtime.config
    with scoped.connection() as conn:
        scoped._fence(conn, "delivery", token)
        row = conn.execute(
            "SELECT o.status, o.access_generation, o.access_notice, l.status AS member, l.generation "
            "FROM outbox o JOIN learners l ON l.id=o.learner_id WHERE o.id=%s AND o.learner_id=%s",
            (item["id"], scoped.learner_id),
        ).fetchone()
        if (
            not row
            or row["status"] not in ("pending", "failed")
            or row["generation"] != row["access_generation"]
            or (row["member"] != "active" and not row["access_notice"])
        ):
            raise MembershipChanged("Queued Telegram copy is no longer authorized")
        # A copy made for another bot is never sent through the configured one.
        if body.get("bot") != config.telegram_namespace:
            raise _Skip("other_bot")
        original = conn.execute(
            "SELECT status, body FROM outbox WHERE id=%s AND learner_id=%s",
            (body["copy_of"], scoped.learner_id),
        ).fetchone()
        if not original or original["status"] != "sent":
            raise _Skip("outdated")
        raw = conn.execute(
            "SELECT body FROM coach_state WHERE learner_id=%s", (scoped.learner_id,)
        ).fetchone()
        if not raw:
            raise MembershipChanged("Learner state is unavailable")
        state = State.model_validate(raw["body"])
        # A copy of an earlier question, a replaced plan, a paused or past scheduled day is skipped.
        if stale_delivery(state, original["body"], today):
            raise _Skip("outdated")
        reason = blocked(conn, config, scoped.learner_id)
        if reason:
            raise _Skip(reason)
        return {
            "original": original["body"],
            "state": state,
            "to": recipient(conn, config, scoped.learner_id),
        }


def _media_plan(note: dict, state, config):
    """What a media copy shows for this note and the learner's current choices: ("media", None) for
    the stored file, or ("text", note) when only an honest note may be sent."""
    from skillcoach.web_channel import MEDIA_FALLBACK, MEDIA_NOTE, MEDIA_UNAVAILABLE

    if note.get("status") == "unavailable":
        return "text", MEDIA_UNAVAILABLE.get(
            note.get("reason"), MEDIA_UNAVAILABLE["not_made"]
        ) + MEDIA_FALLBACK
    if note.get("status") != "ready" or note.get("type") not in ("video", "image"):
        return "text", MEDIA_NOTE
    if note.get("voice") and not (state.voice and config.narration_enabled):
        return "text", NARRATED
    return "media", None


def _send_text(telegram, text, buttons, fmt, budget, quiet, fresh):
    """Send one text, each attempt right after a fresh check."""
    from skillcoach.formatting import plain, telegram_html

    extra = {"silent": True} if quiet else {}
    fresh()
    if fmt != "md":
        telegram.send(text, budget, buttons, **extra)
        return
    try:
        telegram.send(telegram_html(text), budget, buttons, parse_mode="HTML", **extra)
    except ExternalError as exc:
        # A plain 400 means Telegram could not parse the formatting and sent nothing; recipient and
        # bot problems (also 400s) are not retried as plain text.
        if exc.code != "http_400" or exc.telegram:
            raise
        fresh()
        telegram.send(plain(text), budget, buttons, **extra)


def _send_media(runtime, scoped, telegram, original, budget, quiet, fresh):
    """Send the stored media of `original`, or the honest note the newest state calls for. Returns a
    Telegram file ID to cache, or None."""
    from skillcoach import web_media

    config = runtime.config
    note = original.get("web_media") or {}
    kind, text = _media_plan(note, fresh()["state"], config)
    if kind == "text":
        _send_text(telegram, text, None, None, budget, quiet, fresh)
        return None
    field = "video" if note["type"] == "video" else "photo"
    method = "sendVideo" if field == "video" else "sendPhoto"
    media_id = note[note["type"]]
    cache_key = f"copy:{config.telegram_namespace}:{media_id}"
    caption = _caption(note)
    # Database reads first, then a fresh check and plan right before the network call.
    stored = web_media.read_all(scoped, media_id)
    cached = scoped.media_asset(cache_key) if stored is not None else None

    def ready():
        kind, text = _media_plan(note, fresh()["state"], config)
        if kind == "text":
            # The newest state (e.g. narration turned off meanwhile) allows only the honest note.
            _send_text(telegram, text, None, None, budget, quiet, fresh)
            return False
        return True

    if stored is None:
        # Retention removed the video: Telegram gets the same honest note as the web inbox.
        _send_text(telegram, NOT_KEPT, None, None, budget, quiet, fresh)
        return None
    if cached:
        if not ready():
            return None
        try:
            telegram.call(
                method,
                budget,
                data={
                    field: cached["file_id"],
                    "caption": caption,
                    **({"disable_notification": True} if quiet else {}),
                },
            )
            return None
        except ExternalError as exc:
            if exc.code != "http_400" or exc.telegram:
                raise
            scoped.forget_media_asset(cache_key)
    if not ready():
        return None
    mime, data = stored
    result = telegram.call(
        method,
        budget,
        data={
            "caption": caption,
            **({"supports_streaming": "true"} if field == "video" else {}),
            **({"disable_notification": "true"} if quiet else {}),
        },
        files={field: ("lesson.mp4" if field == "video" else "lesson.png", data, mime)},
    )
    sent = result.get("video") if field == "video" else (result.get("photo") or [{}])[-1]
    file_id = (sent or {}).get("file_id")
    return (field, cache_key, file_id) if isinstance(file_id, str) else None


def deliver(runtime, scoped, item, body, token, budget) -> bool:
    """Send one Telegram copy (deliver_one's kind 'telegram')."""
    from skillcoach.runtime import DeliveryDeferred, require_send_budget, silent_delivery

    config = runtime.config
    today = runtime.clock().astimezone(IST).date().isoformat()
    chat = {}

    def fresh():
        context = _check(runtime, scoped, item, body, token, today)
        # The recipient must still be the person this client writes to.
        if chat and context["to"] != chat["to"]:
            raise _Skip("recipient_changed")
        require_send_budget(budget)
        return context

    try:
        context = fresh()
        chat["to"] = context["to"]
        original = context["original"]
        telegram = runtime.telegram if scoped.is_owner else runtime.telegram.for_chat(context["to"])
        quiet = silent_delivery(body["copy_of"], context["state"], runtime.clock())
        cache = None
        if original.get("kind") == "media":
            cache = _send_media(runtime, scoped, telegram, original, budget, quiet, fresh)
        else:
            _send_text(
                telegram,
                original.get("text", ""),
                original.get("buttons"),
                original.get("format"),
                budget,
                quiet,
                fresh,
            )
    except DeliveryDeferred:
        return False
    except _Skip as skip:
        _finish(scoped, item, token, "suppressed", skip.reason)
        return True
    except MembershipChanged:
        _finish(scoped, item, token, "suppressed")
        return True
    except ExternalError as exc:
        if exc.code == "request_budget_exhausted":
            return False
        return _failed(runtime, scoped, item, token, exc)
    # Finalize after the send, never holding locks over it, in the domain's lock order: a concurrent
    # /cancel that withdrew the copy wins (the row is no longer open), a /retry only waits.
    with scoped.connection() as conn:
        scoped._fence(conn, "delivery", token)
        _lock(conn, scoped)
        if scoped._finish_delivery(conn, item["id"], "sent"):
            _release_email(conn, item)
            if original.get("target") is not None:
                # Typed replies to this bot now bind to this question; the web conversation is unchanged.
                conn.execute(
                    "UPDATE coach_state SET telegram_target=%s WHERE learner_id=%s",
                    (
                        Jsonb({"bot": config.telegram_namespace, "target": original["target"]}),
                        scoped.learner_id,
                    ),
                )
            if scoped.is_owner:
                conn.execute(
                    "UPDATE telegram_pauses SET state='cleared', cleared_at=now(), cleared_by='confirmed' "
                    "WHERE bot_id=%s AND learner_id IS NULL AND state='probation'",
                    (config.telegram_namespace,),
                )
            if cache:
                field, cache_key, file_id = cache
                conn.execute(
                    "INSERT INTO media_assets(asset_key,learner_id,file_id,kind,metadata) "
                    "VALUES (%s,NULL,%s,%s,'{}'::jsonb) ON CONFLICT (asset_key) DO NOTHING",
                    (cache_key, file_id, field),
                )
    return True


def _failed(runtime, scoped, item, token, exc) -> bool:
    category = exc.telegram
    if category in GLOBAL_CODES or (exc.code == "http_401" and not category):
        code = category or "credentials_rejected"
        log.warning("telegram_copies_paused scope=bot code=%s", code)
        with scoped.connection() as conn:
            scoped._fence(conn, "delivery", token)
            _lock(conn, scoped)
            pause_id = pause(conn, runtime.config, None, code)
            if pause_id:
                notify_owner(conn, pause_id, code)
            scoped._finish_delivery(conn, item["id"], "suppressed", "telegram_paused")
            _release_email(conn, item)
        return True
    if category in RECIPIENT_CODES or (exc.code == "http_403" and not category):
        code = category or "forbidden"
        log.warning("telegram_copies_paused scope=recipient code=%s", code)
        with scoped.connection() as conn:
            scoped._fence(conn, "delivery", token)
            _lock(conn, scoped)
            pause(conn, runtime.config, scoped.learner_id, code)
            scoped._finish_delivery(conn, item["id"], "suppressed", "recipient_paused")
            _release_email(conn, item)
        return True
    code = "telegram_" + category if category else exc.code
    log.warning("delivery_failed kind=telegram code=%s", code)
    # Passing faults are retried within the usual attempts; anything else is final for this copy.
    _finish(scoped, item, token, "failed", code, final=not exc.retryable)
    return True
