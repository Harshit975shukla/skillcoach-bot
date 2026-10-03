"""Web + email delivery for when Telegram is unavailable (DELIVERY_CHANNEL=web).

The coaching service runs unchanged. Learners sign in with a one-time code sent to their email,
send the same commands and buttons from the browser, and read delivered messages in a private web
inbox. Scheduled lessons, quizzes and mentor notes also send one email reminder with a link back.
Nothing here runs unless web mode is configured.
"""

import hashlib
import hmac
import logging
import re
import secrets
import time
from datetime import timedelta
from urllib.parse import parse_qsl, urlsplit

from skillcoach.clients import Budget, ExternalError
from skillcoach.config import normalize_email

log = logging.getLogger(__name__)
WEB_COOKIE = "__Host-skillcoach-web"
LOGIN_COOKIE = "__Host-skillcoach-web-login"
SESSION_SECONDS = 14 * 24 * 3600
# A device whose session expired can follow the learner's next sign-in on that browser for this
# long (it never delivers in between); after that it must be turned on again.
PUSH_RESUME_DAYS = 45
CODE_SECONDS = 600
CODE_ATTEMPTS = 5
# Every sign-in request takes at least this long, covering a typical SMTP send.
START_FLOOR_SECONDS = 4.0
MAX_SENDS_PER_HOUR = 60
MAX_UNKNOWN_PER_HOUR = 500
# Code emails from sign-in and from web invitations, as one list for the shared limits. A send is
# reserved (code_hash set) in the same owner-locked transaction that decides it, before any SMTP
# call, so concurrent requests cannot exceed the hourly cap. Failed or abandoned attempts keep their
# reservation until it leaves the hour; unregistered sign-in addresses never reserve one.
EMAIL_ATTEMPTS = (
    "SELECT 'login' AS kind, NULL AS ref, email_hash, requested_at AS at, code_hash IS NOT NULL AS reserved, "
    "learner_id IS NULL AS unknown FROM web_logins WHERE requested_at>%s UNION ALL "
    "SELECT 'join', invite_id, email_hash, requested_at, code_hash IS NOT NULL, false FROM web_joins "
    "WHERE requested_at>%s"
)
FEED_PAGE = 40
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
REQUEST_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
START_PAYLOAD = re.compile(r"[A-Za-z0-9_-]{1,64}")
MEDIA_NOTE = (
    "🎬 No video was made for this step in the web app. Use “Open lesson page” for the "
    "step-by-step walkthrough."
)
MEDIA_UNAVAILABLE = {
    "too_large": "🎬 Video unavailable: this step's video was too large to keep.",
    "storage_full": "🎬 Video unavailable: video storage is full, so this step's video was not kept.",
    "not_made": "🎬 Video unavailable: this step's video could not be made.",
}
MEDIA_EXPIRED = "🎬 This step's video is no longer kept."
MEDIA_FALLBACK = " Use “Open lesson page” for the step-by-step walkthrough."
MEDIA_PATH = re.compile(r"[0-9a-f]{32}")
SUBJECTS = {
    "lesson": "Today's SkillCoach lesson is ready",
    "quiz": "Your SkillCoach quiz is ready",
    "weekly": "Your weekly SkillCoach assessment is ready",
    "review": "Your SkillCoach weekly review",
}


class WebDenied(ValueError):
    pass


class WebCodeIncorrect(WebDenied):
    pass


class WebLimited(WebDenied):
    pass


class WebUnavailable(RuntimeError):
    """A code email could not be sent; nothing was granted and the request can be repeated."""


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def keyed(config, purpose: str, value: str) -> str:
    return hmac.new(
        config.webhook_secret.encode(), f"web-{purpose}:{value}".encode(), hashlib.sha256
    ).hexdigest()


def csrf_token(config, token: str) -> str:
    return keyed(config, "csrf", token)


def masked(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    local, domain = email.split("@", 1)
    return local[:1] + "•••@" + domain


def same_origin(request):
    origin = request.headers.get("Origin", "")
    parsed, current = urlsplit(origin), urlsplit(request.host_url)
    if not origin or (parsed.scheme, parsed.netloc) != (current.scheme, current.netloc):
        raise WebDenied("Open SkillCoach from its own address to continue.")
    if request.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
        raise WebDenied("Cross-site requests are not allowed.")


# Sign-in ------------------------------------------------------------------------------------


def learner_for_email(conn, config, email: str):
    """The active learner who signs in with this address. The owner uses OWNER_EMAIL."""
    if config.owner_email and email == config.owner_email:
        row = conn.execute("SELECT * FROM learners WHERE id='owner'").fetchone()
    else:
        row = conn.execute("SELECT * FROM learners WHERE email=%s AND id<>'owner'", (email,)).fetchone()
    return row if row and row["status"] == "active" else None


def code_email(code: str, config) -> str:
    return (
        f"Your SkillCoach sign-in code is {code}\n\n"
        "Enter it in the browser where you asked for it. It expires in 10 minutes and works once. "
        "Never share it: SkillCoach will never ask you for this code.\n\n"
        f"If you did not try to sign in at {config.web_app_url}/web, ignore this email."
    )


def pad_response(started: float, floor: float, sleep=time.sleep):
    """Give every sign-in request the same minimum duration, so timing does not reveal whether an
    address is registered (an email is only sent for registered ones)."""
    remaining = floor - (time.monotonic() - started)
    if remaining > 0:
        sleep(remaining)


def start_login(runtime, raw_email):
    """Create a browser-bound login and email a six-digit code. Every valid address gets the same
    answer after at least the same time, with the same limits, and only registered, active
    learners receive an email, so the form does not reveal who is registered."""
    started = time.monotonic()
    config, now = runtime.config, runtime.clock()
    email = normalize_email(raw_email)
    if email is None:
        raise WebDenied("Enter a valid email address.")
    email_hash = keyed(config, "email", email)
    identifier, verifier = secrets.token_urlsafe(18), secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(10**6):06d}"
    expires = now + timedelta(seconds=CODE_SECONDS)
    hour = now - timedelta(hours=1)
    with runtime.repo.connection() as conn:
        # Serializes rate-limit checks across concurrent requests; no network call happens here.
        conn.execute("SELECT id FROM learners WHERE id='owner' FOR UPDATE")
        conn.execute("DELETE FROM web_logins WHERE requested_at<%s", (now - timedelta(days=2),))
        counts = conn.execute(
            "SELECT count(*) FILTER (WHERE email_hash=%s AND at>%s) AS hourly, "
            "count(*) FILTER (WHERE email_hash=%s) AS daily, "
            "max(at) FILTER (WHERE email_hash=%s) AS latest, "
            "count(*) FILTER (WHERE at>%s AND reserved) AS reserved, "
            f"count(*) FILTER (WHERE at>%s AND kind='login' AND unknown) AS unknown FROM ({EMAIL_ATTEMPTS}) r",
            (
                email_hash,
                hour,
                email_hash,
                email_hash,
                hour,
                hour,
                now - timedelta(days=1),
                now - timedelta(days=1),
            ),
        ).fetchone()
        if (
            (counts["latest"] and counts["latest"] > now - timedelta(seconds=60))
            or counts["hourly"] >= 5
            or counts["daily"] >= 10
        ):
            raise WebLimited(
                "Codes are limited to one a minute, five an hour and ten a day. Try again later."
            )
        if counts["unknown"] >= MAX_UNKNOWN_PER_HOUR:
            # Bounds storage during a flood of made-up addresses. Every address gets this answer, so
            # it reveals nothing; browsers that are already signed in keep working.
            log.warning("web_sign_in_flood_limit_reached")
            raise WebLimited("Too many sign-in requests right now. Try again in a few minutes.")
        member = learner_for_email(conn, config, email)
        # Only reserved sends count toward the overall email limit, so made-up addresses cannot use
        # it up. Past it, registered addresses get the usual answer but no email until it frees up.
        send = bool(member) and counts["reserved"] < MAX_SENDS_PER_HOUR
        if member and not send:
            log.warning("web_code_send_limit_reached")
        conn.execute(
            "UPDATE web_logins SET status='rejected' WHERE email_hash=%s AND status='pending'", (email_hash,)
        )
        conn.execute(
            "INSERT INTO web_logins(id,email_hash,learner_id,verifier_hash,code_hash,requested_at,expires_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                identifier,
                email_hash,
                member["id"] if member else None,
                digest(verifier),
                keyed(config, "code", f"{identifier}:{code}") if send else None,
                now,
                expires,
            ),
        )
    if send:
        # One bounded send outside all DB locks. A failed send invalidates the code and is never
        # retried; the response stays the same so a failure does not reveal the address.
        try:
            runtime.email.send(email, "Your SkillCoach sign-in code", code_email(code, config), Budget(15))
        except ExternalError as exc:
            with runtime.repo.connection() as conn:
                conn.execute("UPDATE web_logins SET status='rejected' WHERE id=%s", (identifier,))
            log.warning("web_code_delivery_failed code=%s", exc.code)
        else:
            with runtime.repo.connection() as conn:
                conn.execute("UPDATE web_logins SET notified=true WHERE id=%s", (identifier,))
    pad_response(started, START_FLOOR_SECONDS)
    return {
        "pending": True,
        "expires_at": expires.isoformat(),
        "resend_at": (now + timedelta(seconds=60)).isoformat(),
    }, verifier


def verify_login(runtime, verifier, code):
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        raise WebCodeIncorrect("Enter the six-digit code from your email.")
    if not TOKEN.fullmatch(verifier or ""):
        raise WebDenied("Ask for a code in this browser first. Cookies must be enabled.")
    config, now = runtime.config, runtime.clock()
    failure = result = None
    with runtime.repo.connection() as conn:
        row = conn.execute(
            "SELECT * FROM web_logins WHERE verifier_hash=%s FOR UPDATE", (digest(verifier),)
        ).fetchone()
        if (
            not row
            or row["status"] != "pending"
            or row["expires_at"] <= now
            or row["attempts"] >= CODE_ATTEMPTS
        ):
            raise WebDenied("This code expired or was replaced. Ask for a new code.")
        expected = row["code_hash"] or keyed(config, "code", secrets.token_hex(16))
        if (
            row["notified"]
            and row["learner_id"]
            and hmac.compare_digest(expected, keyed(config, "code", f"{row['id']}:{code}"))
        ):
            member = conn.execute(
                "SELECT * FROM learners WHERE id=%s FOR UPDATE", (row["learner_id"],)
            ).fetchone()
            if not member or member["status"] != "active":
                raise WebDenied("This account does not have coaching access.")
            conn.execute("UPDATE web_logins SET status='consumed' WHERE id=%s", (row["id"],))
            conn.execute("DELETE FROM web_sessions WHERE expires_at<%s", (now,))
            # Devices whose session ended long ago can no longer be resumed by signing in again.
            conn.execute(
                "DELETE FROM web_push_subscriptions s WHERE s.created_at<%s AND NOT EXISTS "
                "(SELECT 1 FROM web_sessions w WHERE w.token_hash=s.session_hash)",
                (now - timedelta(days=PUSH_RESUME_DAYS),),
            )
            token = secrets.token_urlsafe(32)
            expires = now + timedelta(seconds=SESSION_SECONDS)
            conn.execute(
                "INSERT INTO web_sessions(token_hash,learner_id,access_generation,email_hash,expires_at) "
                "VALUES (%s,%s,%s,%s,%s)",
                (digest(token), member["id"], member["generation"], row["email_hash"], expires),
            )
            result = token, expires, member
        else:
            remaining = CODE_ATTEMPTS - 1 - row["attempts"]
            conn.execute(
                "UPDATE web_logins SET attempts=attempts+1,status=%s WHERE id=%s",
                ("rejected" if remaining == 0 else "pending", row["id"]),
            )
            failure = (
                WebDenied("Too many incorrect codes. Ask for a new code.")
                if remaining == 0
                else WebCodeIncorrect(f"Incorrect code. {remaining} attempts remaining.")
            )
    # A wrong guess commits its counter before the error is returned.
    if failure:
        raise failure
    return result


def authenticate(request, runtime, *, mutate=False):
    if request.args:
        raise WebDenied("Do not put credentials in the address.")
    token = request.cookies.get(WEB_COOKIE, "")
    if not TOKEN.fullmatch(token):
        raise WebDenied("Sign in with your email to continue.")
    with runtime.repo.connection() as conn:
        row = conn.execute(
            "SELECT s.learner_id,s.expires_at,s.access_generation,s.email_hash,l.email,l.status,"
            "l.generation,l.display_name FROM web_sessions s JOIN learners l ON l.id=s.learner_id "
            "WHERE s.token_hash=%s AND s.expires_at>%s",
            (digest(token), runtime.clock()),
        ).fetchone()
    if not row or row["status"] != "active" or row["generation"] != row["access_generation"]:
        raise WebDenied("Your session ended. Sign in again with your email.")
    # A session only lasts while the address it signed in with is still the learner's address.
    address = runtime.config.owner_email if row["learner_id"] == "owner" else row["email"]
    if not address or not hmac.compare_digest(row["email_hash"], keyed(runtime.config, "email", address)):
        raise WebDenied("Your session ended. Sign in again with your email.")
    if mutate:
        same_origin(request)
        if not hmac.compare_digest(
            request.headers.get("X-CSRF-Token", ""), csrf_token(runtime.config, token)
        ):
            raise WebDenied("This page is out of date. Refresh and try again.")
    return row, token


def logout(runtime, token):
    if TOKEN.fullmatch(token or ""):
        with runtime.repo.connection() as conn:
            conn.execute("DELETE FROM web_sessions WHERE token_hash=%s", (digest(token),))
            # Signing out stops this browser's notifications too.
            conn.execute("DELETE FROM web_push_subscriptions WHERE session_hash=%s", (digest(token),))


# Inbound ------------------------------------------------------------------------------------


def accept_web(repo, session, request_id: str, payload: dict) -> tuple[str, str]:
    """Admit one browser message or button tap exactly like a Telegram update (same limits,
    same question binding). The request ID makes retries idempotent."""
    from skillcoach.access import ADMIN_COMMANDS, _job, _notice

    key = "web:" + request_id
    text = payload.get("text", "").strip()
    parts = text.split(None, 1)
    command = parts[0].split("@")[0].lstrip("/").lower() if parts and text.startswith("/") else ""
    argument = parts[1].strip() if len(parts) == 2 else ""
    with repo.connection() as conn:
        member = conn.execute(
            "SELECT * FROM learners WHERE id=%s FOR UPDATE", (session["learner_id"],)
        ).fetchone()
        if not member or member["status"] != "active" or member["generation"] != session["access_generation"]:
            return "denied", key
        if conn.execute("SELECT 1 FROM jobs WHERE id=%s", (key,)).fetchone():
            return "duplicate", key
        admin_only = (
            command in ADMIN_COMMANDS
            or (command in ("start", "join") and argument.startswith(("invite_", "admin_login_")))
            or payload.get("callback", "").startswith("adminlogin:")
        )
        if admin_only:
            _job(conn, key, member, {"type": "access_denied"}, done=True)
            _notice(
                conn,
                key,
                member,
                "Invitations and access are managed in the admin console at /admin while SkillCoach "
                "runs on the web.",
            )
            return "admin_elsewhere", key
        recent = conn.execute(
            "SELECT count(*) AS n FROM jobs WHERE learner_id=%s AND created_at>now()-interval '1 minute'",
            (member["id"],),
        ).fetchone()["n"]
        queued = conn.execute(
            "SELECT count(*) AS n FROM jobs WHERE learner_id=%s AND status IN ('pending','running','failed')",
            (member["id"],),
        ).fetchone()["n"]
        if (recent >= 20 or queued >= 100) and command not in ("pause", "cancel", "retry"):
            warned = conn.execute(
                "SELECT 1 FROM jobs WHERE learner_id=%s AND payload->>'type'='rate_limited' "
                "AND created_at>now()-interval '1 minute' LIMIT 1",
                (member["id"],),
            ).fetchone()
            if not warned:
                _job(conn, key, member, {"type": "rate_limited"}, done=True)
                _notice(
                    conn,
                    key,
                    member,
                    "Too much pending work. Wait a minute or /cancel failed work before sending more.",
                )
            return "rate_limited", key
        target = conn.execute(
            "SELECT displayed_target FROM coach_state WHERE learner_id=%s", (member["id"],)
        ).fetchone()["displayed_target"]
        data = {"type": "telegram", "channel": "web", "target": target}
        if "callback" in payload:
            data["callback"] = payload["callback"]
        else:
            data["text"] = text
        _job(conn, key, member, data)
        return "queued", key


def web_payload(body: dict) -> dict:
    """Validate the browser's message: exactly one of text (commands or answers) or a button."""
    if set(body) not in ({"request_id", "text"}, {"request_id", "callback"}):
        raise WebDenied("Unexpected request fields. Refresh the page.")
    if not isinstance(body["request_id"], str) or not REQUEST_ID.fullmatch(body["request_id"]):
        raise WebDenied("A valid request identifier is required.")
    if "callback" in body:
        value = body["callback"]
        if not isinstance(value, str) or not value or len(value.encode()) > 64:
            raise WebDenied("That button is no longer valid.")
        return {"callback": value}
    value = body["text"]
    if not isinstance(value, str) or not value.strip() or len(value) > 16000:
        raise WebDenied("Write a message of 1-16000 characters.")
    return {"text": value}


# Outbound -----------------------------------------------------------------------------------


def web_button(raw, config):
    """Map a Telegram inline button to its web equivalent, or drop it."""
    from skillcoach.catalog import TOPICS
    from skillcoach.lesson_delivery import LESSON_ID

    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text", ""))[:80]
    data = raw.get("callback_data")
    if isinstance(data, str) and data and len(data.encode()) <= 64:
        return {"kind": "callback", "text": text, "data": data}
    app = raw.get("web_app") if isinstance(raw.get("web_app"), dict) else None
    url = (app or {}).get("url") or raw.get("url")
    if not isinstance(url, str):
        return None
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    if LESSON_ID.fullmatch(query.get("lesson", "")):
        return {"kind": "lesson", "text": text, "lesson": query["lesson"]}
    if query.get("topic") in TOPICS:
        return {"kind": "topic", "text": text, "topic": query["topic"]}
    if app:
        if parts.path.rstrip("/").endswith("/admin"):
            return {"kind": "link", "text": text, "url": "/admin"}
        # The Telegram-only dashboard's progress and plan views are commands in the web app.
        return {"kind": "command", "text": "📊 My progress", "command": "/progress"}
    if parts.scheme != "https" or not parts.hostname or parts.username:
        return None
    if parts.hostname == "t.me":
        start = query.get("start", "")
        if START_PAYLOAD.fullmatch(start):
            return {"kind": "command", "text": text, "command": "/start " + start}
        return None
    return {"kind": "link", "text": text, "url": url}


def media_item(media: dict) -> dict | None:
    """The browser's view of stored media: same-origin paths and display facts only."""
    kind = media.get("type")
    if kind not in ("video", "image") or not MEDIA_PATH.fullmatch(str(media.get(kind, ""))):
        return None
    item = {"type": kind, "src": f"/web/media/{media[kind]}"}
    if kind == "video" and MEDIA_PATH.fullmatch(str(media.get("poster", ""))):
        item["poster"] = f"/web/media/{media['poster']}"
    for key in ("width", "height", "duration"):
        if isinstance(media.get(key), (int, float)) and not isinstance(media.get(key), bool):
            item[key] = media[key]
    return item


def feed_item(row, config) -> dict:
    from skillcoach.formatting import md_blocks

    body = row["body"]
    item = {
        "id": row["delivered_seq"],
        "at": row["delivered_at"].isoformat() if row["delivered_at"] else None,
    }
    if body.get("kind") == "media":
        stored = body.get("web_media") or {}
        if stored.get("status") == "ready":
            media = media_item(stored) if row.get("media_kept") else None
            if media:
                labels = [str(label)[:160] for label in stored.get("labels") or []][:4]
                return {**item, "kind": "media", "text": str(stored.get("text", "")), "labels": labels,
                        "media": media, "buttons": []}
            return {**item, "kind": "text", "text": MEDIA_EXPIRED + MEDIA_FALLBACK, "buttons": []}
        if stored.get("status") == "unavailable":
            text = MEDIA_UNAVAILABLE.get(stored.get("reason"), MEDIA_UNAVAILABLE["not_made"])
            return {**item, "kind": "text", "text": text + MEDIA_FALLBACK, "buttons": []}
        return {**item, "kind": "text", "text": MEDIA_NOTE, "buttons": []}
    text = str(body.get("text", ""))
    item["kind"] = "text"
    if body.get("format") == "md":
        item["blocks"] = md_blocks(text)
    else:
        item["text"] = text
    rows = []
    for line in body.get("buttons") or []:
        if not isinstance(line, list):
            continue
        mapped = [b for b in (web_button(raw, config) for raw in line) if b]
        if mapped:
            rows.append(mapped)
    item["buttons"] = rows
    return item


def feed(repo, session, config, *, after=None, before=None) -> dict:
    """The learner's delivered messages in delivery order, from the current access generation
    only. Cursors are delivery positions, so a message that is retried or recovered after newer
    ones still appears after the cursor the browser already has."""
    from skillcoach.web_media import waiting

    params = [session["learner_id"], session["access_generation"]]
    where = (
        "learner_id=%s AND access_generation=%s AND status='sent' AND delivered_seq IS NOT NULL "
        "AND body->>'kind' IN ('text','media')"
    )
    # Whether a delivered video or still is still stored (retention may have removed it).
    columns = (
        "delivered_seq,body,delivered_at,(body->>'kind'='media' AND EXISTS (SELECT 1 FROM web_media_refs r "
        "JOIN web_media m ON m.id=r.media_id AND m.state='ready' WHERE r.outbox_id=o.id "
        "AND r.role IN ('video','image'))) AS media_kept"
    )
    with repo.connection(readonly=True) as conn:
        if after is not None:
            rows = conn.execute(
                f"SELECT {columns} FROM outbox o WHERE {where} AND delivered_seq>%s "
                "ORDER BY delivered_seq LIMIT %s",
                (*params, after, FEED_PAGE),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT {columns} FROM outbox o WHERE {where} "
                + ("AND delivered_seq<%s " if before is not None else "")
                + "ORDER BY delivered_seq DESC LIMIT %s",
                (*params, *([before] if before is not None else []), FEED_PAGE),
            ).fetchall()[::-1]
        working = conn.execute(
            "SELECT count(*) AS n FROM jobs WHERE learner_id=%s AND access_generation=%s "
            "AND status IN ('pending','running') AND available_at<=now()",
            params,
        ).fetchone()["n"]
        preparing = waiting(conn, *params)
    return {
        "messages": [feed_item(row, config) for row in rows],
        "working": working > 0,
        "preparing": preparing,
        "older": after is None and len(rows) == FEED_PAGE,
    }


def notification(job, messages, config):
    """One email reminder for a scheduled lesson, quiz, assessment, review or mentor note."""
    from skillcoach.formatting import plain

    if not config.web_mode or not messages:
        return None
    payload = job.get("payload") or {}
    if payload.get("type") == "schedule":
        subject = SUBJECTS.get(payload.get("kind"), "SkillCoach update")
    elif payload.get("type") == "encouragement":
        subject = "A note from your SkillCoach mentor"
    elif payload.get("requested_by") == "owner_admin":
        subject = "New from SkillCoach"
    else:
        return None
    visible = [m for m in messages if m.get("kind") == "text" and m.get("text")]
    if not visible:
        return None
    first = visible[0]
    text = plain(first["text"]) if first.get("format") == "md" else first["text"]
    if len(text) > 1500:
        text = text[:1500].rsplit(" ", 1)[0] + " …"
    body = {
        "kind": "email",
        "subject": subject,
        "text": f"{text}\n\nContinue in SkillCoach: {config.web_app_url}/web\n\n"
        "You get this reminder because SkillCoach runs in the web app. SkillCoach does not process email "
        f"replies. Privacy policy and requests: {config.privacy_policy_url}",
    }
    for key in ("scheduled", "scheduled_date"):
        if key in first:
            body[key] = first[key]
    return body
