"""Web push for the installable web app (web mode with a VAPID key pair; off otherwise).

A learner turns notifications on per device with an explicit tap. The browser's push subscription
is stored as one binding to the learner, their access generation, their sign-in address and the
web session that turned it on; it can deliver only while all four are still current. A reminder
that also goes by email queues one push row naming the bindings that were deliverable then, and
each binding is checked again right before its send. Cleanup only ever touches that exact binding,
so a device that was rebound to someone else is never sent an older notification or deleted.

Encryption is RFC 8291 (aes128gcm) via http-ece and the signature RFC 8292 (VAPID) via py-vapid.
The HTTPS transport is ours: allowlisted push services only, port 443, no redirects, short
timeouts and response bodies are never read. Payloads name only a reminder kind; the service worker
shows fixed text, so no lesson topic, name or score ever reaches a lock screen. Endpoints and keys
are capabilities and are never logged. The push service accepting a message does not mean it was
shown or seen, and nothing here claims exactly-once display.
"""

import base64
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import time
from urllib.parse import urlsplit

import requests

from skillcoach.clients import Budget, ExternalError

log = logging.getLogger(__name__)
MAX_DEVICES = 5
RECORD_SIZE = 4096
# Reminders are only useful for a few hours; a short TTL also bounds how long the push service
# keeps a message that can no longer be recalled.
TTL_SECONDS = 3 * 3600
CONNECT_SECONDS = 2
READ_SECONDS = 4
# One push row never holds the single delivery lease longer than this, so email and the web
# inbox keep moving while a push service is slow.
ROW_SECONDS = 12
MAX_ENDPOINT = 1024
KINDS = ("lesson", "quiz", "weekly", "review", "mentor", "update")
B64URL = re.compile(r"[A-Za-z0-9_-]+")
_TOKEN = r"[A-Za-z0-9_=%.~:-]{16,800}"
# Push services that browsers use: (name, host, subdomains only, path, query or None).
PROVIDERS = (
    ("fcm", "fcm.googleapis.com", False, re.compile(r"/(?:fcm/send|wp)/" + _TOKEN), None),
    ("mozilla", "updates.push.services.mozilla.com", False, re.compile(r"/wpush/v[12]/" + _TOKEN), None),
    ("apple", "push.apple.com", True, re.compile(r"/" + _TOKEN), None),
    (
        "windows",
        "notify.windows.com",
        True,
        re.compile(r"/w/"),
        re.compile(r"token=[A-Za-z0-9_=%.~+/-]{16,800}"),
    ),
)
# A binding delivers only while its learner, access generation, sign-in address and web session
# are all still current. The address is compared in Python (keyed hash of the current address).
DELIVERABLE = (
    "SELECT s.* FROM web_push_subscriptions s JOIN learners l ON l.id=s.learner_id "
    "JOIN web_sessions w ON w.token_hash=s.session_hash AND w.learner_id=s.learner_id "
    "WHERE s.learner_id=%s AND l.status='active' AND s.access_generation=l.generation "
    "AND w.access_generation=l.generation AND w.email_hash=s.email_hash AND w.expires_at>%s"
)


class PushConflict(ValueError):
    """This browser's subscription still belongs to another signed-in account."""


def b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def b64d(value, size: int) -> bytes:
    if not isinstance(value, str):
        raise ValueError("not base64url")
    value = value.rstrip("=")
    if not B64URL.fullmatch(value):
        raise ValueError("not base64url")
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if len(raw) != size:
        raise ValueError("wrong length")
    return raw


def provider(url) -> str | None:
    """The push service an endpoint belongs to, or None. HTTPS on port 443 to one of the listed
    hosts (or, for Apple and Windows, a real subdomain of them) with that service's path shape;
    no user info, IP literal, fragment or other query. Nothing is resolved or fetched here."""
    if not isinstance(url, str) or not 0 < len(url) <= MAX_ENDPOINT or not url.isascii():
        return None
    if any(ch.isspace() or ord(ch) < 33 or ch in '\\"<>^`{|}' for ch in url):
        return None
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname or ""
    if parts.scheme != "https" or port not in (None, 443) or parts.fragment or "@" in parts.netloc:
        return None
    if parts.netloc.lower() not in (host, host + ":443"):
        return None
    if not re.fullmatch(r"[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63})+", host):
        return None
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    for name, base, subdomains, path, query in PROVIDERS:
        if (host.endswith("." + base) if subdomains else host == base) and path.fullmatch(parts.path):
            if query.fullmatch(parts.query) if query else not parts.query:
                return name
    return None


def receiver_keys(p256dh, auth) -> tuple[str, str]:
    """Canonical base64url keys of a browser subscription. ValueError unless p256dh is an
    uncompressed point on P-256 and auth is 16 bytes."""
    from cryptography.hazmat.primitives.asymmetric import ec

    point = b64d(p256dh, 65)
    if point[0] != 4:
        raise ValueError("not an uncompressed point")
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
    return b64e(point), b64e(b64d(auth, 16))


def _private_key(private: str):
    from cryptography.hazmat.primitives.asymmetric import ec

    return ec.derive_private_key(int.from_bytes(b64d(private, 32), "big"), ec.SECP256R1())


def _public_of(key) -> str:
    from cryptography.hazmat.primitives import serialization

    return b64e(
        key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )


def generate_keys() -> tuple[str, str]:
    """A new VAPID key pair as (public, private), base64url. Store the private key as a secret."""
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    return _public_of(key), b64e(key.private_numbers().private_value.to_bytes(32, "big"))


def check_keys(public, private) -> bool:
    """True when the private key is a valid P-256 scalar and the public key is exactly its point."""
    try:
        return hmac.compare_digest(_public_of(_private_key(private)), b64e(b64d(public, 65)))
    except (ValueError, TypeError):
        return False


def encrypt(payload: bytes, p256dh: str, auth: str, *, salt: bytes | None = None, sender=None) -> bytes:
    """RFC 8291 aes128gcm in one record. Every message gets a fresh sender key and salt; the two
    keyword arguments exist only so tests can reproduce the RFC's published example."""
    import http_ece
    from cryptography.hazmat.primitives.asymmetric import ec

    if len(payload) > 512:
        raise ExternalError("push_payload_too_large", retryable=False)
    return http_ece.encrypt(
        payload,
        salt=salt or os.urandom(16),
        private_key=sender or ec.generate_private_key(ec.SECP256R1()),
        dh=b64d(p256dh, 65),
        auth_secret=b64d(auth, 16),
        version="aes128gcm",
        rs=RECORD_SIZE,
    )


def authorization(endpoint: str, config, now: float) -> str:
    """RFC 8292 header for this push service: audience is the endpoint's origin, expiry 12 hours."""
    from py_vapid import Vapid02

    claims = {
        "aud": "https://" + urlsplit(endpoint).hostname,
        "exp": int(now) + 12 * 3600,
        "sub": config.web_app_url,
    }
    return Vapid02.from_raw(config.web_push_private_key.encode()).sign(dict(claims))["Authorization"]


class WebPush:
    """HTTPS delivery to a browser's push service. Returns "accepted" (the service took the
    message; it may still never be shown) or "gone" (the subscription no longer exists); raises
    ExternalError otherwise. Redirects are refused and response bodies are never read."""

    def __init__(self, config, session=None):
        self.config = config
        self.session = session or requests.Session()
        # No proxy or .netrc credentials from the environment for capability URLs.
        self.session.trust_env = False

    def send(self, target, kind: str, budget: Budget, *, ttl: int = TTL_SECONDS) -> str:
        if kind not in KINDS:
            raise ExternalError("invalid_push_kind", retryable=False)
        if provider(target["endpoint"]) is None:
            raise ExternalError("push_endpoint_not_allowed", retryable=False)
        try:
            body = encrypt(
                json.dumps({"push": kind}, separators=(",", ":")).encode(), target["p256dh"], target["auth"]
            )
        except ValueError:
            raise ExternalError("push_subscription_keys_invalid", retryable=False) from None
        headers = {
            "Authorization": authorization(target["endpoint"], self.config, time.time()),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(ttl),
            "Urgency": "normal",
        }
        remaining = budget.remaining()
        try:
            with self.session.post(
                target["endpoint"],
                data=body,
                headers=headers,
                allow_redirects=False,
                stream=True,
                timeout=(min(CONNECT_SECONDS, remaining / 3), min(READ_SECONDS, remaining / 2)),
            ) as response:
                status = response.status_code
        except requests.RequestException:
            raise ExternalError("push_network_unavailable") from None
        if status in (200, 201, 202):
            return "accepted"
        if status in (404, 410):
            return "gone"
        if 300 <= status < 400:
            raise ExternalError("push_redirect_refused", retryable=False)
        raise ExternalError(f"push_http_{status}", retryable=status in (408, 429, 500, 502, 503, 504))


# Bindings ------------------------------------------------------------------------------------


def _address_hash(scoped, config) -> str | None:
    from skillcoach.web_channel import keyed

    address = scoped.email_address(config.owner_email)
    return keyed(config, "email", address) if address else None


def targets(scoped, config, now) -> list[str]:
    """Bindings that may receive this learner's reminder now, newest first."""
    if not config.push_enabled:
        return []
    expected = _address_hash(scoped, config)
    if not expected:
        return []
    with scoped.connection(readonly=True) as conn:
        rows = conn.execute(
            DELIVERABLE + " ORDER BY s.created_at DESC LIMIT %s", (scoped.learner_id, now, MAX_DEVICES)
        ).fetchall()
    return [row["id"] for row in rows if hmac.compare_digest(row["email_hash"], expected)]


def current(scoped, config, ident: str, now):
    """Binding `ident` if it may still receive this learner's notifications, else None."""
    expected = _address_hash(scoped, config)
    if not expected:
        return None
    with scoped.connection(readonly=True) as conn:
        row = conn.execute(DELIVERABLE + " AND s.id=%s", (scoped.learner_id, now, ident)).fetchone()
    return row if row and hmac.compare_digest(row["email_hash"], expected) else None


def reminder(job, note, scoped, config, now) -> dict | None:
    """The push row that accompanies a reminder email, naming today's deliverable bindings."""
    if not config.push_enabled or not note:
        return None
    payload = job.get("payload") or {}
    if payload.get("type") == "schedule":
        kind = payload.get("kind")
    elif payload.get("type") == "encouragement":
        kind = "mentor"
    elif payload.get("requested_by") == "owner_admin":
        kind = "update"
    else:
        return None
    if kind not in KINDS:
        return None
    ids = targets(scoped, config, now)
    if not ids:
        return None
    body = {"kind": "push", "push": kind, "targets": ids}
    for key in ("scheduled", "scheduled_date"):
        if key in note:
            body[key] = note[key]
    return body


def deliver(sender, scoped, config, item, token, budget: Budget, clock) -> tuple[str, str | None]:
    """Send one push row to the devices it names: ("sent" | "failed" | "suppressed" | "deferred",
    code). Each device is checked again just before its own send, and its result is recorded on the
    row at once under the delivery lease: accepted, gone (binding removed), stale (no longer
    deliverable) or a permanent error code. Recorded devices are never sent this notification
    again; a transient error or running out of time leaves the rest for the next attempt. The row
    is sent only when every device has an outcome. Delivery is at least once per device: a crash
    between a push service's answer and its record can repeat that one device."""
    body = item["body"]
    kind = body.get("push")
    if kind not in KINDS:
        return "failed", "invalid_push_kind"
    outcomes = dict(body.get("outcomes") or {})
    devices = [ident for ident in (body.get("targets") or [])[:MAX_DEVICES] if isinstance(ident, str)]
    window = Budget(min(ROW_SECONDS, budget.remaining()))
    transient = []
    for ident in devices:
        if ident in outcomes:
            continue
        try:
            if window.remaining() < CONNECT_SECONDS + READ_SECONDS / 2:
                break
        except ExternalError:
            break
        target = current(scoped, config, ident, clock())
        if target is None:
            scoped.record_push_outcome(item["id"], token, ident, "stale")
            outcomes[ident] = "stale"
            continue
        try:
            answer = sender.send(target, kind, window)
        except ExternalError as exc:
            if exc.code == "request_budget_exhausted":
                break
            log.warning(
                "push_failed provider=%s code=%s", provider(target["endpoint"]) or "unknown", exc.code
            )
            if exc.retryable:
                transient.append(exc.code)
            else:
                scoped.record_push_outcome(item["id"], token, ident, exc.code)
                outcomes[ident] = exc.code
            continue
        scoped.record_push_outcome(
            item["id"], token, ident, answer, forget=answer == "gone", sent=answer == "accepted"
        )
        outcomes[ident] = answer
    if transient:
        return "failed", transient[0]
    if any(ident not in outcomes for ident in devices):
        return "deferred", None
    rejected = [value for value in outcomes.values() if value not in ("accepted", "gone", "stale")]
    if rejected:
        return "failed", rejected[0]
    return ("sent" if "accepted" in outcomes.values() else "suppressed"), None


# Browser requests ----------------------------------------------------------------------------


def subscription_body(body) -> tuple[str, str, str]:
    if set(body) != {"endpoint", "p256dh", "auth"} or not all(isinstance(v, str) for v in body.values()):
        raise ValueError("fields")
    if provider(body["endpoint"]) is None:
        raise ValueError("endpoint")
    p256dh, auth = receiver_keys(body["p256dh"], body["auth"])
    return body["endpoint"], p256dh, auth


def _current(conn, session, token_hash, config, now):
    """Inside the binding transaction: the learner, locked FOR UPDATE like revocation and address
    changes, and this exact web session, still live and bound to the learner's current address,
    locked FOR SHARE so that a sign-out waits for this commit and then removes what it made.
    (None, None) when either has ended since the request was authenticated."""
    from skillcoach.web_channel import keyed

    member = conn.execute(
        "SELECT * FROM learners WHERE id=%s FOR UPDATE", (session["learner_id"],)
    ).fetchone()
    if not member or member["status"] != "active" or member["generation"] != session["access_generation"]:
        return None, None
    live = conn.execute(
        "SELECT * FROM web_sessions WHERE token_hash=%s AND learner_id=%s AND access_generation=%s "
        "AND expires_at>%s FOR SHARE",
        (token_hash, member["id"], member["generation"], now),
    ).fetchone()
    address = config.owner_email if member["id"] == "owner" else member.get("email")
    if (
        not live
        or not address
        or not hmac.compare_digest(live["email_hash"], keyed(config, "email", address))
    ):
        return None, None
    return member, live


def _endpoint_row(conn, endpoint):
    from skillcoach.web_channel import digest

    return conn.execute(
        "SELECT * FROM web_push_subscriptions WHERE endpoint_hash=%s FOR UPDATE", (digest(endpoint),)
    ).fetchone()


def _deliverable(conn, row, config, now) -> bool:
    """Whether another learner's binding could still deliver (its session is live and current)."""
    from skillcoach.web_channel import keyed

    live = conn.execute(DELIVERABLE + " AND s.id=%s", (row["learner_id"], now, row["id"])).fetchone()
    if not live:
        return False
    member = conn.execute("SELECT email FROM learners WHERE id=%s", (row["learner_id"],)).fetchone()
    address = config.owner_email if row["learner_id"] == "owner" else (member or {}).get("email")
    return bool(address) and hmac.compare_digest(live["email_hash"], keyed(config, "email", address))


def _bind(conn, member, live, token_hash, endpoint, p256dh, auth) -> bool:
    """A new binding under a new identifier; False if this subscription was bound concurrently."""
    from skillcoach.web_channel import digest

    return (
        conn.execute(
            "INSERT INTO web_push_subscriptions(id,endpoint_hash,endpoint,p256dh,auth,learner_id,"
            "access_generation,email_hash,session_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (endpoint_hash) DO NOTHING RETURNING id",
            (
                secrets.token_hex(16),
                digest(endpoint),
                endpoint,
                p256dh,
                auth,
                member["id"],
                member["generation"],
                live["email_hash"],
                token_hash,
            ),
        ).fetchone()
        is not None
    )


def _same(row, member, live, token_hash, p256dh, auth) -> bool:
    return bool(row) and (
        row["learner_id"] == member["id"]
        and row["session_hash"] == token_hash
        and row["access_generation"] == member["generation"]
        and row["email_hash"] == live["email_hash"]
        and (row["p256dh"], row["auth"]) == (p256dh, auth)
    )


def subscribe(runtime, session, token, body) -> dict:
    """Explicit opt-in from this signed-in browser. A new binding gets a new identifier; a repeat
    of the same request is a no-op. A subscription still deliverable for another account is never
    taken over: the page then replaces the browser's subscription with a fresh one."""
    from skillcoach.web_channel import WebDenied, digest

    try:
        endpoint, p256dh, auth = subscription_body(body)
    except ValueError:
        raise WebDenied("This browser's notification service is not supported.") from None
    token_hash, now = digest(token), runtime.clock()
    conflict = "Notifications could not be turned on in this browser. Try again."
    with runtime.repo.connection() as conn:
        member, live = _current(conn, session, token_hash, runtime.config, now)
        if member is None:
            raise WebDenied("Your session ended. Sign in again with your email.")
        row = _endpoint_row(conn, endpoint)
        if row and row["learner_id"] != member["id"]:
            if _deliverable(conn, row, runtime.config, now):
                raise PushConflict(conflict)
            conn.execute("DELETE FROM web_push_subscriptions WHERE id=%s", (row["id"],))
            row = None
        if row:
            if _same(row, member, live, token_hash, p256dh, auth):
                return {"subscribed": True}
            conn.execute("DELETE FROM web_push_subscriptions WHERE id=%s", (row["id"],))
        # At most MAX_DEVICES per learner: the oldest bindings make room.
        conn.execute(
            "DELETE FROM web_push_subscriptions WHERE id IN (SELECT id FROM web_push_subscriptions "
            "WHERE learner_id=%s ORDER BY created_at DESC, id OFFSET %s)",
            (member["id"], MAX_DEVICES - 1),
        )
        if not _bind(conn, member, live, token_hash, endpoint, p256dh, auth):
            # Bound at the same moment by another request: the same opt-in, or another account's.
            if _same(_endpoint_row(conn, endpoint), member, live, token_hash, p256dh, auth):
                return {"subscribed": True}
            raise PushConflict(conflict)
    return {"subscribed": True}


def sync(runtime, session, token, body) -> dict:
    """On sign-in or page load: keep this browser's notifications only if its binding already
    belongs to this learner, access generation and sign-in address; it then follows the current
    session under a new identifier. Nothing is created and no other account is touched."""
    from skillcoach.web_channel import WebDenied, digest

    try:
        endpoint, p256dh, auth = subscription_body(body)
    except ValueError:
        return {"subscribed": False}
    token_hash = digest(token)
    with runtime.repo.connection() as conn:
        member, live = _current(conn, session, token_hash, runtime.config, runtime.clock())
        if member is None:
            raise WebDenied("Your session ended. Sign in again with your email.")
        row = _endpoint_row(conn, endpoint)
        if (
            not row
            or row["learner_id"] != member["id"]
            or row["access_generation"] != member["generation"]
            or row["email_hash"] != live["email_hash"]
        ):
            if row and row["learner_id"] == member["id"]:
                conn.execute("DELETE FROM web_push_subscriptions WHERE id=%s", (row["id"],))
            return {"subscribed": False}
        if _same(row, member, live, token_hash, p256dh, auth):
            return {"subscribed": True}
        conn.execute("DELETE FROM web_push_subscriptions WHERE id=%s", (row["id"],))
        if not _bind(conn, member, live, token_hash, endpoint, p256dh, auth):
            return {"subscribed": False}
    return {"subscribed": True}


def unsubscribe(runtime, session, body) -> dict:
    """Turn this browser's notifications off. Only this learner's own binding can be removed, and
    the answer is the same whether or not one existed."""
    from skillcoach.web_channel import WebDenied, digest

    if (
        set(body) != {"endpoint"}
        or not isinstance(body["endpoint"], str)
        or len(body["endpoint"]) > MAX_ENDPOINT
    ):
        raise WebDenied("Unexpected request fields. Refresh the page.")
    with runtime.repo.connection() as conn:
        conn.execute(
            "DELETE FROM web_push_subscriptions WHERE endpoint_hash=%s AND learner_id=%s",
            (digest(body["endpoint"]), session["learner_id"]),
        )
    return {"subscribed": False}
