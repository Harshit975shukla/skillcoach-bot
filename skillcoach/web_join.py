"""Web invitations: a person the owner invited proves their email address with a one-time code in
the same browser, and only then becomes a pending learner the owner can approve or reject in the
admin console. The invitation is claimed in that same transaction.

Addresses are compared after trimming and lowercasing, the existing web sign-in policy; plus tags
and dots are kept, so "a+b@x.com" and "ab@x.com" are different addresses. An address that already
has access, is waiting for approval or is the owner's is never reassigned. Approval, rejection and
revocation emails go only to the address that was verified.
"""

import hashlib
import hmac
import logging
import re
import secrets
import unicodedata
from datetime import timedelta

from psycopg.types.json import Jsonb

from skillcoach.clients import Budget, ExternalError
from skillcoach.config import normalize_email
from skillcoach.web_channel import (
    CODE_ATTEMPTS,
    CODE_SECONDS,
    EMAIL_ATTEMPTS,
    MAX_SENDS_PER_HOUR,
    TOKEN,
    WebCodeIncorrect,
    WebDenied,
    WebLimited,
    WebUnavailable,
    digest,
    keyed,
    masked,
)

log = logging.getLogger(__name__)
JOIN_COOKIE = "__Host-skillcoach-web-join"
INVITE = re.compile(r"[A-Za-z0-9_-]{32}")
NAME_LIMIT = 60
INVITE_INVALID = (
    "This invitation link is not valid, was already used or has expired. Ask your coach for a new one."
)


def invite_link(config, token: str) -> str:
    # The token is in the fragment, so it never reaches server logs or other sites as a referrer.
    return f"{config.web_app_url.rstrip('/')}/web#invite={token}"


def clean_name(raw) -> str | None:
    if not isinstance(raw, str):
        return None
    name = " ".join(raw.split())
    if not 1 <= len(name) <= NAME_LIMIT or any(unicodedata.category(c) in ("Cc", "Cf") for c in name):
        return None
    return name


def code_email(code: str) -> str:
    return (
        f"Your SkillCoach verification code is {code}\n\n"
        "Enter it on the page where you accepted your invitation. It expires in 10 minutes and works "
        "once, in that browser. Never share it.\n\n"
        "If you did not ask to join SkillCoach, ignore this email. Nothing happens without the code."
    )


def start_join(runtime, raw_invite, raw_name, raw_email):
    """Email a code to the address the joiner typed. Nothing is created and the invitation stays open
    until the code is confirmed. A new request for the same invitation or address replaces any
    earlier unconfirmed one. Limits are shared with web sign-in emails."""
    config, now = runtime.config, runtime.clock()
    if not isinstance(raw_invite, str) or not INVITE.fullmatch(raw_invite):
        raise WebDenied(INVITE_INVALID)
    name, email = clean_name(raw_name), normalize_email(raw_email)
    if name is None:
        raise WebDenied(f"Enter your name, up to {NAME_LIMIT} characters.")
    if email is None:
        raise WebDenied("Enter a valid email address.")
    email_hash = keyed(config, "email", email)
    identifier, verifier = secrets.token_urlsafe(18), secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(10**6):06d}"
    expires = now + timedelta(seconds=CODE_SECONDS)
    hour, day = now - timedelta(hours=1), now - timedelta(days=1)
    with runtime.repo.connection() as conn:
        # The same lock as web sign-in serializes all quota checks; no network call happens here.
        conn.execute("SELECT id FROM learners WHERE id='owner' FOR UPDATE")
        conn.execute("DELETE FROM web_joins WHERE requested_at<%s", (now - timedelta(days=2),))
        invite = conn.execute(
            "SELECT id FROM invitations WHERE token_hash=%s AND status='open' AND expires_at>%s",
            (hashlib.sha256(raw_invite.encode()).hexdigest(), now),
        ).fetchone()
        if not invite:
            raise WebDenied(INVITE_INVALID)
        usage = conn.execute(
            "SELECT count(*) FILTER (WHERE kind='join' AND ref=%s AND at>%s) AS invite_hourly, "
            "max(at) FILTER (WHERE kind='join' AND ref=%s) AS invite_latest, "
            "count(*) FILTER (WHERE email_hash=%s AND at>%s) AS hourly, "
            "count(*) FILTER (WHERE email_hash=%s) AS daily, "
            "max(at) FILTER (WHERE email_hash=%s) AS latest, "
            f"count(*) FILTER (WHERE at>%s AND reserved) AS reserved FROM ({EMAIL_ATTEMPTS}) r",
            (invite["id"], hour, invite["id"], email_hash, hour, email_hash, email_hash, hour, day, day),
        ).fetchone()
        if (usage["latest"] and usage["latest"] > now - timedelta(seconds=60)) or (
            usage["hourly"] >= 5 or usage["daily"] >= 10
        ):
            raise WebLimited(
                "Codes are limited to one a minute, five an hour and ten a day. Try again later."
            )
        if (usage["invite_latest"] and usage["invite_latest"] > now - timedelta(seconds=60)) or usage[
            "invite_hourly"
        ] >= 5:
            raise WebLimited("This invitation already asked for several codes. Wait a few minutes.")
        if usage["reserved"] >= MAX_SENDS_PER_HOUR:
            raise WebLimited("Too many emails are being sent right now. Try again in a few minutes.")
        conn.execute(
            "UPDATE web_joins SET status='rejected' WHERE status='pending' AND (invite_id=%s OR email_hash=%s)",
            (invite["id"], email_hash),
        )
        conn.execute(
            "INSERT INTO web_joins(id,invite_id,email,email_hash,display_name,verifier_hash,code_hash,"
            "requested_at,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                identifier,
                invite["id"],
                email,
                email_hash,
                name,
                digest(verifier),
                keyed(config, "join-code", f"{identifier}:{code}"),
                now,
                expires,
            ),
        )
    # One bounded send outside all DB locks. A failed send invalidates the code; it is never retried.
    try:
        runtime.email.send(email, "Your SkillCoach verification code", code_email(code), Budget(15))
    except ExternalError as exc:
        with runtime.repo.connection() as conn:
            conn.execute("UPDATE web_joins SET status='rejected' WHERE id=%s", (identifier,))
        log.warning("web_join_code_delivery_failed code=%s", exc.code)
        raise WebUnavailable(
            "The code could not be emailed. Check the address, then try again in a minute."
        ) from None
    with runtime.repo.connection() as conn:
        conn.execute("UPDATE web_joins SET notified=true WHERE id=%s", (identifier,))
    return {
        "pending": True,
        "expires_at": expires.isoformat(),
        "resend_at": (now + timedelta(seconds=60)).isoformat(),
    }, verifier


def verify_join(runtime, verifier, code):
    """Confirm the code from the requesting browser, then turn the request into a pending learner and
    claim the invitation in one transaction. Every refusal ends the request."""
    from skillcoach.access import _job, _notice, _pending_member

    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        raise WebCodeIncorrect("Enter the six-digit code from your email.")
    if not TOKEN.fullmatch(verifier or ""):
        raise WebDenied("Ask for a code in this browser first. Cookies must be enabled.")
    config, now = runtime.config, runtime.clock()
    failure = None
    with runtime.repo.connection() as conn:
        owner = conn.execute("SELECT * FROM learners WHERE id='owner' FOR UPDATE").fetchone()
        row = conn.execute(
            "SELECT * FROM web_joins WHERE verifier_hash=%s FOR UPDATE", (digest(verifier),)
        ).fetchone()
        if (
            not row
            or row["status"] != "pending"
            or row["expires_at"] <= now
            or row["attempts"] >= CODE_ATTEMPTS
        ):
            raise WebDenied("This code expired, was replaced or was already used. Ask for a new code.")
        expected = row["code_hash"] or keyed(config, "join-code", secrets.token_hex(16))
        if not (
            row["notified"]
            and hmac.compare_digest(expected, keyed(config, "join-code", f"{row['id']}:{code}"))
        ):
            remaining = CODE_ATTEMPTS - 1 - row["attempts"]
            conn.execute(
                "UPDATE web_joins SET attempts=attempts+1,status=%s WHERE id=%s",
                ("rejected" if remaining == 0 else "pending", row["id"]),
            )
            failure = (
                WebDenied("Too many incorrect codes. Ask for a new code.")
                if remaining == 0
                else WebCodeIncorrect(f"Incorrect code. {remaining} attempts remaining.")
            )
        else:
            email = row["email"]
            invite = conn.execute(
                "SELECT * FROM invitations WHERE id=%s FOR UPDATE", (row["invite_id"],)
            ).fetchone()
            member = conn.execute("SELECT * FROM learners WHERE email=%s FOR UPDATE", (email,)).fetchone()
            pending = conn.execute("SELECT count(*) AS n FROM learners WHERE status='pending'").fetchone()[
                "n"
            ]
            refusal = None
            if not invite or invite["status"] != "open" or invite["expires_at"] <= now:
                refusal = INVITE_INVALID
            elif config.owner_email and email == config.owner_email:
                refusal = "This address is your coach's own sign-in. Join with your own email address."
            elif member and member["status"] == "active":
                refusal = "This email already has SkillCoach access. Sign in with it instead."
            elif member and member["status"] == "pending":
                refusal = "This email is already waiting for your coach's approval."
            elif pending >= 100:
                refusal = "Too many requests are waiting for approval. Try again later."
            if refusal:
                conn.execute("UPDATE web_joins SET status='rejected' WHERE id=%s", (row["id"],))
                failure = WebDenied(refusal)
            else:
                # A rejected or revoked learner with this verified address keeps their history.
                member = _pending_member(conn, None, row["display_name"], member, guided=True)
                conn.execute("UPDATE learners SET email=%s WHERE id=%s", (email, member["id"]))
                conn.execute(
                    "UPDATE invitations SET status='claimed',claimed_by=%s WHERE id=%s",
                    (member["id"], invite["id"]),
                )
                conn.execute(
                    "UPDATE web_joins SET status='consumed',learner_id=%s WHERE id=%s",
                    (member["id"], row["id"]),
                )
                key = "web-join:" + row["id"]
                _job(
                    conn,
                    key,
                    member,
                    {"type": "access_claim", "invite_id": invite["id"], "channel": "web"},
                    done=True,
                )
                label = f" ({invite['label']})" if invite["label"] else ""
                summary = (
                    f"{row['display_name']} confirmed their email address {masked(email)} with invitation "
                    f"{invite['id']}{label} and asks to join SkillCoach. Learner ID: {member['id']}."
                )
                _notice(
                    conn,
                    key,
                    owner,
                    summary + "\nApprove or reject the request in the admin console.",
                    suffix="owner-request",
                )
                conn.execute(
                    "INSERT INTO outbox(id,job_id,body,learner_id,access_generation,access_notice) "
                    "VALUES (%s,%s,%s,'owner',%s,true) ON CONFLICT DO NOTHING",
                    (
                        f"{key}:owner-email",
                        key,
                        Jsonb(
                            {
                                "kind": "email",
                                "subject": "New SkillCoach access request",
                                "text": f"{summary}\n\nNothing happens until you approve it. Review it in the "
                                f"admin console: {config.web_app_url.rstrip('/')}/admin",
                            }
                        ),
                        owner["generation"],
                    ),
                )
    # A wrong code or a refusal commits its effect before the error is returned.
    if failure:
        raise failure
    return {"requested": True}


def deliver_now(runtime, steps=3):
    """In web mode, send a few queued messages and emails right away (decision and request emails);
    anything left waits for the worker. The caller's action is already committed, so a failure here
    is logged, never reported as a failed action."""
    from skillcoach.runtime import STORAGE_ERRORS

    if not runtime.config.web_mode:
        return
    budget = Budget(20)
    try:
        for _ in range(steps):
            if budget.remaining() < 8 or not runtime.deliver_one(budget, media=False):
                break
    except (ExternalError, *STORAGE_ERRORS):
        log.warning("web_inline_delivery_deferred")


ACCESS_EMAILS = {
    "active": (
        "Your SkillCoach access is approved",
        "Welcome to SkillCoach! Your coach approved your access.\n\nSign in at {url}/web with this email "
        "address; you will receive a six-digit code. Then tap “Set up my learning” to build your plan.",
    ),
    "rejected": (
        "Your SkillCoach access request",
        "Your request to join SkillCoach was not approved, so no coaching access was granted. If you think "
        "this is a mistake, contact the person who invited you.",
    ),
    "revoked": (
        "Your SkillCoach access has ended",
        "Your SkillCoach access was revoked and queued coaching was cancelled. Returning needs a new "
        "invitation and your coach's approval.",
    ),
}


def access_email(conn, key, member, status, config):
    """Queue one decision email to the learner's verified address. The row is keyed to the admin
    request, and it is only delivered while that address is still the learner's."""
    if not config.web_mode or not member.get("email") or status not in ACCESS_EMAILS:
        return
    subject, text = ACCESS_EMAILS[status]
    conn.execute(
        "INSERT INTO outbox(id,job_id,body,learner_id,access_generation,access_notice) "
        "VALUES (%s,%s,%s,%s,%s,true) ON CONFLICT DO NOTHING",
        (
            f"{key}:access-email",
            key,
            Jsonb(
                {
                    "kind": "email",
                    "subject": subject,
                    "text": text.format(url=config.web_app_url.rstrip("/"))
                    + "\n\nReplies to this address are not read.",
                    "to_hash": keyed(config, "email", member["email"]),
                }
            ),
            member["id"],
            member["generation"],
        ),
    )
