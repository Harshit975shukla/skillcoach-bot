"""Owner-only browser sessions approved through Telegram or signed Mini App launch data."""

import hashlib
import hmac
import re
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from skillcoach.dashboard import MAX_AUTH_AGE, DashboardDenied, verify_init_data

SESSION_COOKIE = "__Host-skillcoach-admin"
LOGIN_COOKIE = "__Host-skillcoach-login"
SESSION_SECONDS = 900
LOGIN_SECONDS = 300


class AdminDenied(ValueError):
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
    return {
        "telegram_url": f"https://t.me/{runtime.config.bot_username}?start=admin_login_{identifier}",
        "code": code,
        "expires_at": expires.isoformat(),
    }, verifier


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
            return None
        if row["status"] != "approved":
            raise AdminDenied("Sign-in was rejected or already used. Start again.")
        conn.execute("UPDATE admin_logins SET status='consumed' WHERE id=%s", (row["id"],))
        return new_session(conn, runtime.config, runtime.clock())


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
    if not row or row["status"] != "pending":
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
