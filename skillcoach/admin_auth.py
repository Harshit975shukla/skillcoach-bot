"""Owner-only sessions using Telegram PINs, legacy approval or signed Mini App launch data."""

import hashlib
import hmac
import logging
import re
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from skillcoach.clients import Budget, ExternalError
from skillcoach.dashboard import MAX_AUTH_AGE, DashboardDenied, verify_init_data

log = logging.getLogger(__name__)
SESSION_COOKIE = "__Host-skillcoach-admin"
LOGIN_COOKIE = "__Host-skillcoach-login"
SESSION_SECONDS = 900
LOGIN_SECONDS = 300


class AdminDenied(ValueError):
    pass


class PinIncorrect(AdminDenied):
    pass


class PinRateLimited(AdminDenied):
    pass


class PinDeliveryFailed(RuntimeError):
    pass


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def csrf_token(token, config):
    return hmac.new(
        config.webhook_secret.encode(), ("admin-csrf:" + token).encode(), hashlib.sha256
    ).hexdigest()


def same_origin(request):
    origin = request.headers.get("Origin", "")
    if not origin:
        raise AdminDenied("This action must be started from the admin dashboard.")
    parsed, current = urlsplit(origin), urlsplit(request.host_url)
    if (parsed.scheme, parsed.netloc) != (current.scheme, current.netloc):
        raise AdminDenied("Cross-origin administration is not allowed.")
    if request.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
        raise AdminDenied("Cross-site administration is not allowed.")


def new_session(conn, config, now, *, telegram_issued=None):
    if config.owner_id <= 0:
        raise AdminDenied("Administrator identity is not configured.")
    token = secrets.token_urlsafe(32)
    seconds = SESSION_SECONDS
    if telegram_issued is not None:
        token = "tg_" + token
        seconds = min(MAX_AUTH_AGE, telegram_issued + MAX_AUTH_AGE - int(now.timestamp()))
        if seconds <= 0:
            raise AdminDenied("Reopen the admin panel from Telegram for a fresh launch.")
    expires = now + timedelta(seconds=seconds)
    conn.execute(
        "INSERT INTO admin_sessions(token_hash,owner_id,expires_at) VALUES (%s,%s,%s)",
        (digest(token), config.owner_id, expires),
    )
    return token, expires


def authenticate(request, runtime, *, mutate=False):
    if request.args:
        raise AdminDenied("Do not put identity or credentials in URL parameters.")
    cookie = request.cookies.get(SESSION_COOKIE, "")
    header = request.headers.get("X-Admin-Session", "")
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if header or init_data:
        if not re.fullmatch(r"tg_[A-Za-z0-9_-]{43}", header) or not init_data:
            raise AdminDenied("Reopen the admin panel using its Telegram button.")
        if cookie and cookie != header:
            raise AdminDenied("Conflicting authentication transports. Reopen the dashboard.")
        try:
            actor, _ = verify_init_data(
                init_data, runtime.config.telegram_token, int(runtime.clock().timestamp())
            )
        except DashboardDenied as exc:
            raise AdminDenied(str(exc)) from None
        if actor != runtime.config.owner_id:
            raise AdminDenied("Only the bot owner can use this admin panel.")
        token = header
    else:
        token = cookie
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise AdminDenied("Sign in as the owner to continue.")
    with runtime.repo.connection() as conn:
        session = conn.execute(
            "SELECT token_hash,owner_id,expires_at FROM admin_sessions "
            "WHERE token_hash=%s AND owner_id=%s AND expires_at>%s",
            (digest(token), runtime.config.owner_id, runtime.clock()),
        ).fetchone()
    if not session or runtime.config.owner_id <= 0:
        raise AdminDenied("Your admin session expired. Sign in again.")
    if mutate:
        same_origin(request)
        if not hmac.compare_digest(
            request.headers.get("X-CSRF-Token", ""), csrf_token(token, runtime.config)
        ):
            raise AdminDenied("The action could not be verified. Refresh the dashboard.")
    return session, token


def login_from_telegram(runtime, init_data, *, memory=False):
    try:
        actor, issued = verify_init_data(
            init_data, runtime.config.telegram_token, int(runtime.clock().timestamp())
        )
    except DashboardDenied as exc:
        raise AdminDenied(str(exc)) from None
    if actor != runtime.config.owner_id:
        raise AdminDenied("This dashboard is only available to the bot owner.")
    with runtime.repo.connection() as conn:
        conn.execute("SELECT id FROM learners WHERE id='owner' FOR UPDATE")
        count = conn.execute(
            "SELECT count(*) AS n FROM admin_sessions WHERE owner_id=%s "
            "AND created_at>now()-interval '5 minutes'",
            (runtime.config.owner_id,),
        ).fetchone()["n"]
        if count >= 20:
            raise AdminDenied("Too many recent admin sign-ins. Wait five minutes.")
        return new_session(conn, runtime.config, runtime.clock(), telegram_issued=issued if memory else None)


def start_login(runtime):
    if not runtime.config.bot_username:
        raise AdminDenied("The bot username is not configured.")
    now = runtime.clock()
    with runtime.repo.connection() as conn:
        conn.execute("SELECT id FROM learners WHERE id='owner' FOR UPDATE")
        count = conn.execute("SELECT count(*) AS n FROM admin_logins WHERE expires_at>%s", (now,)).fetchone()[
            "n"
        ]
        if count >= 20:
            raise AdminDenied("Too many recent sign-in requests. Wait five minutes and try again.")
        identifier, verifier = secrets.token_urlsafe(18), secrets.token_urlsafe(32)
        code = secrets.token_hex(3).upper()
        expires = now + timedelta(seconds=LOGIN_SECONDS)
        conn.execute(
            "INSERT INTO admin_logins(id,verifier_hash,owner_id,display_code,expires_at) VALUES (%s,%s,%s,%s,%s)",
            (identifier, digest(verifier), runtime.config.owner_id, code, expires),
        )
    return _challenge(runtime.config, identifier, code, expires), verifier


def _challenge(config, identifier, code, expires):
    return {
        "telegram_url": f"https://t.me/{config.bot_username}?start=admin_login_{identifier}",
        "code": code,
        "expires_at": expires.isoformat(),
    }


def _pin_challenge(row):
    return {
        "authenticated": False,
        "pending": True,
        "method": "pin",
        "expires_at": row["expires_at"].isoformat(),
        "resend_at": (row["requested_at"] + timedelta(seconds=60)).isoformat(),
        "attempts_remaining": 3 - row["pin_attempts"],
    }


def _pin_digest(config, identifier, pin):
    return hmac.new(
        config.webhook_secret.encode(), f"admin-pin:{identifier}:{pin}".encode(), hashlib.sha256
    ).hexdigest()


def _pin_limits(conn, config, now, *, sending=False):
    owner = conn.execute("SELECT id FROM learners WHERE id='owner' FOR UPDATE").fetchone()
    if not owner or config.owner_id <= 0 or not config.webhook_secret:
        raise AdminDenied("Administrator identity is not configured.")
    counts = conn.execute(
        "SELECT count(*) FILTER (WHERE requested_at>%s) AS hourly, count(*) AS daily, "
        "max(requested_at) AS latest, "
        "COALESCE(sum(pin_attempts) FILTER (WHERE pin_last_failed_at>%s),0) AS hourly_failures, "
        "COALESCE(sum(pin_attempts),0) AS daily_failures "
        "FROM admin_logins WHERE owner_id=%s AND pin_hash IS NOT NULL AND requested_at>%s",
        (
            now - timedelta(hours=1),
            now - timedelta(hours=1),
            config.owner_id,
            now - timedelta(days=1, minutes=5),
        ),
    ).fetchone()
    hint = "Try later." if config.web_mode else "Try later or use /admin inside Telegram."
    if counts["hourly_failures"] >= 5 or counts["daily_failures"] >= 10:
        raise PinRateLimited("Too many incorrect PIN attempts. " + hint)
    if sending and (
        counts["hourly"] >= 5
        or counts["daily"] >= 10
        or (counts["latest"] and counts["latest"] > now - timedelta(seconds=60))
    ):
        raise PinRateLimited(
            "PIN requests are limited to one per minute, five per hour and ten per day. " + hint
        )


def start_pin(runtime):
    now = runtime.clock()
    identifier, verifier = secrets.token_urlsafe(18), secrets.token_urlsafe(32)
    pin = f"{secrets.randbelow(10000):04d}"
    expires = now + timedelta(seconds=LOGIN_SECONDS)
    with runtime.repo.connection() as conn:
        _pin_limits(conn, runtime.config, now, sending=True)
        conn.execute(
            "UPDATE admin_logins SET status='rejected' WHERE owner_id=%s "
            "AND pin_hash IS NOT NULL AND status='pending'",
            (runtime.config.owner_id,),
        )
        row = conn.execute(
            "INSERT INTO admin_logins(id,verifier_hash,owner_id,display_code,expires_at,pin_hash,requested_at) "
            "VALUES (%s,%s,%s,'',%s,%s,%s) RETURNING *",
            (
                identifier,
                digest(verifier),
                runtime.config.owner_id,
                expires,
                _pin_digest(runtime.config, identifier, pin),
                now,
            ),
        ).fetchone()
    # Authentication delivery is a single bounded attempt, outside all DB locks. Never persist
    # plaintext PINs in the learning outbox or retry an uncertain send with a still-valid PIN.
    web = runtime.config.web_mode
    text = (
        f"SkillCoach Admin sign-in PIN: {pin}\n\n"
        "Enter this four-digit PIN only in the browser where you requested it. "
        "It expires in five minutes and works once. Never share it. "
        "If you did not request it, ignore this message."
    )
    try:
        if web:
            runtime.email.send(runtime.config.owner_email, "Your SkillCoach admin PIN", text, Budget(12))
        else:
            runtime.telegram.for_chat(runtime.config.owner_id).send(text, Budget(12))
    except ExternalError as exc:
        with runtime.repo.connection() as conn:
            conn.execute("UPDATE admin_logins SET status='rejected' WHERE id=%s", (identifier,))
        log.warning("admin_pin_delivery_failed code=%s", exc.code)
        raise PinDeliveryFailed(
            ("The email could not be sent" if web else "Telegram could not confirm delivery")
            + ". Any PIN from this attempt is invalid. Wait one minute, then request a new PIN."
        ) from None
    with runtime.repo.connection() as conn:
        conn.execute("UPDATE admin_logins SET notified=true WHERE id=%s", (identifier,))
    return _pin_challenge(row), verifier


def verify_pin(runtime, verifier, pin):
    if not isinstance(pin, str) or not re.fullmatch(r"[0-9]{4}", pin):
        raise PinIncorrect(
            "Enter exactly four digits from your "
            + ("PIN email." if runtime.config.web_mode else "Telegram message.")
        )
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", verifier or ""):
        raise AdminDenied("Request a PIN from this browser first. Cookies must be enabled.")
    now = runtime.clock()
    failure = None
    with runtime.repo.connection() as conn:
        _pin_limits(conn, runtime.config, now)
        row = conn.execute(
            "SELECT * FROM admin_logins WHERE verifier_hash=%s AND owner_id=%s FOR UPDATE",
            (digest(verifier), runtime.config.owner_id),
        ).fetchone()
        if (
            not row
            or not row["pin_hash"]
            or row["status"] != "pending"
            or not row["notified"]
            or row["expires_at"] <= now
            or row["pin_attempts"] >= 3
        ):
            raise AdminDenied("This PIN expired, was replaced or was already used. Request a new PIN.")
        if hmac.compare_digest(row["pin_hash"], _pin_digest(runtime.config, row["id"], pin)):
            conn.execute("UPDATE admin_logins SET status='consumed' WHERE id=%s", (row["id"],))
            result = new_session(conn, runtime.config, now)
        else:
            remaining = 2 - row["pin_attempts"]
            conn.execute(
                "UPDATE admin_logins SET pin_attempts=pin_attempts+1,pin_last_failed_at=%s,status=%s WHERE id=%s",
                (now, "rejected" if remaining == 0 else "pending", row["id"]),
            )
            failure = (
                AdminDenied("PIN attempt limit reached. Request a new PIN after the cooldown.")
                if remaining == 0
                else PinIncorrect(f"Incorrect PIN. {remaining} attempts remaining.")
            )
    # A rejected guess must commit its counter before returning an error.
    if failure:
        raise failure
    return result


def exchange_login(runtime, verifier):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", verifier or ""):
        raise AdminDenied("Start a sign-in request from this browser first.")
    with runtime.repo.connection() as conn:
        row = conn.execute(
            "SELECT * FROM admin_logins WHERE verifier_hash=%s AND owner_id=%s AND expires_at>%s FOR UPDATE",
            (digest(verifier), runtime.config.owner_id, runtime.clock()),
        ).fetchone()
        if not row:
            raise AdminDenied("Sign-in expired. Start again.")
        if row["status"] == "pending":
            if row["pin_hash"]:
                if not row["notified"]:
                    raise AdminDenied(
                        "PIN delivery was not confirmed. Wait one minute and request a new PIN."
                    )
                return _pin_challenge(row)
            return {
                "authenticated": False,
                "pending": True,
                **_challenge(runtime.config, row["id"], row["display_code"], row["expires_at"]),
            }
        if row["status"] != "approved" or row["pin_hash"]:
            raise AdminDenied("Sign-in was rejected or already used. Start again.")
        conn.execute("UPDATE admin_logins SET status='consumed' WHERE id=%s", (row["id"],))
        token, expires = new_session(conn, runtime.config, runtime.clock())
        return {"token": token, "expires_at": expires}


def telegram_login_action(conn, key, actor, owner, payload, config):
    """Called only within authenticated Telegram admission; never trusts a claimed role."""
    from skillcoach.access import _job, _notice

    if actor != config.owner_id:
        return "denied"
    text = payload.get("text", "")
    callback = payload.get("callback", "")
    if callback:
        match = re.fullmatch(r"adminlogin:(approve|reject):([A-Za-z0-9_-]{24})", callback)
        if not match:
            return "invalid_admin_login"
        action, identifier = match.groups()
    else:
        match = re.fullmatch(r"/start(?:@[A-Za-z0-9_]+)?\s+admin_login_([A-Za-z0-9_-]{24})", text)
        if not match:
            return "invalid_admin_login"
        identifier, action = match.group(1), "request"
    _job(conn, key, owner, {"type": "admin_login", "action": action}, done=True)
    row = conn.execute(
        "SELECT * FROM admin_logins WHERE id=%s AND owner_id=%s AND expires_at>now() FOR UPDATE",
        (identifier, config.owner_id),
    ).fetchone()
    if not row or row["status"] != "pending" or row["pin_hash"]:
        _notice(conn, key, owner, "This admin sign-in request expired or has already been handled.")
        return "admin_login_closed"
    if action == "request":
        if not row["notified"]:
            _notice(
                conn,
                key,
                owner,
                f"Admin browser sign-in request\nCode: {row['display_code']}\n\n"
                "Approve only if YOU opened /admin and this code matches your browser. "
                "Never approve a code sent by someone else.",
                buttons=[
                    [
                        {
                            "text": "Approve matching sign-in",
                            "callback_data": "adminlogin:approve:" + identifier,
                        },
                        {"text": "Reject", "callback_data": "adminlogin:reject:" + identifier},
                    ]
                ],
            )
            conn.execute("UPDATE admin_logins SET notified=true WHERE id=%s", (identifier,))
        return "admin_login_requested"
    status = "approved" if action == "approve" else "rejected"
    conn.execute("UPDATE admin_logins SET status=%s WHERE id=%s", (status, identifier))
    _notice(
        conn,
        key,
        owner,
        f"Admin sign-in {status}. "
        + (
            "Return to the browser where you started it."
            if status == "approved"
            else "No session was granted."
        ),
    )
    return "admin_login_" + status
