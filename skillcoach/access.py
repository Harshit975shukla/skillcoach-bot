"""Transactional admission and owner-only administration; no external calls."""

import hashlib
import re
import secrets
from uuid import uuid4

from psycopg.types.json import Jsonb

from skillcoach.clients import chunks

ADMIN_COMMANDS = {
    "invite": "[label] create a one-use invite, valid for 24 hours",
    "invites": "List open invitations",
    "revokeinvite": "<invite_id> cancel an unused invitation",
    "requests": "List invited learners waiting for your approval",
    "approve": "<learner_id> approve an invited learner",
    "reject": "<learner_id> reject a pending request",
    "revoke": "<learner_id> revoke access and cancel queued coaching",
    "members": "List learner access status (not private learning content)",
}
INVITE_TOKEN = re.compile(r"invite_([A-Za-z0-9_-]{32})\Z")


def _job(conn, key, member, payload, *, done=False):
    conn.execute(
        "INSERT INTO jobs(id,payload,learner_id,access_generation,status) VALUES (%s,%s,%s,%s,%s)",
        (key, Jsonb(payload), member["id"], member["generation"], "done" if done else "pending"),
    )


def _notice(conn, key, member, text, *, suffix="reply"):
    for index, part in enumerate(chunks(text)):
        conn.execute(
            "INSERT INTO outbox(id,job_id,body,learner_id,access_generation,access_notice) "
            "VALUES (%s,%s,%s,%s,%s,true) ON CONFLICT DO NOTHING",
            (
                f"{key}:access:{suffix}:{index}",
                key,
                Jsonb({"kind": "text", "text": part}),
                member["id"],
                member["generation"],
            ),
        )


def _audit(conn, update_id, action, subject):
    conn.execute(
        "INSERT INTO access_audit(update_id,action,subject_id) VALUES (%s,%s,%s)",
        (update_id, action, subject),
    )


def _invalidate(conn, member_id):
    conn.execute(
        "UPDATE jobs SET status='cancelled' WHERE learner_id=%s AND status IN ('pending','running','failed')",
        (member_id,),
    )
    conn.execute(
        "UPDATE outbox SET status='suppressed' WHERE learner_id=%s AND status IN ('pending','failed')",
        (member_id,),
    )
    conn.execute("UPDATE coach_state SET displayed_target=NULL WHERE learner_id=%s", (member_id,))


def _admin(conn, update_id, key, owner, command, argument, config):
    _job(conn, key, owner, {"type": "access_admin", "command": command}, done=True)
    if command == "invite":
        if not config.bot_username:
            _notice(conn, key, owner, "Invites are unavailable until TELEGRAM_BOT_USERNAME is configured.")
            return
        open_count = conn.execute(
            "SELECT count(*) AS n FROM invitations WHERE status='open' AND expires_at>now()"
        ).fetchone()["n"]
        if open_count >= 50:
            _notice(conn, key, owner, "There are already 50 open invitations. Revoke an unused invite first.")
            return
        ident, token = "i_" + uuid4().hex[:12], secrets.token_urlsafe(24)
        digest = hashlib.sha256(token.encode()).hexdigest()
        conn.execute(
            "INSERT INTO invitations(id,token_hash,label,status,expires_at) "
            "VALUES (%s,%s,%s,'open',now()+interval '24 hours')",
            (ident, digest, argument[:100]),
        )
        _audit(conn, update_id, "invite", ident)
        _notice(
            conn,
            key,
            owner,
            f"Invitation {ident} (one use, expires in 24 hours).\n"
            f"https://t.me/{config.bot_username}?start=invite_{token}\n\n"
            "Share privately with one person. Redeeming it only requests access; you must /approve them. "
            f"Cancel an unused link with /revokeinvite {ident}.",
        )
    elif command == "invites":
        rows = conn.execute(
            "SELECT id,label,expires_at FROM invitations "
            "WHERE status='open' AND expires_at>now() ORDER BY created_at LIMIT 50"
        ).fetchall()
        _notice(
            conn,
            key,
            owner,
            "\n".join(
                f"{r['id']}: {r['label'] or 'No label'}; expires {r['expires_at'].isoformat()}" for r in rows
            )
            or "No open invitations.",
        )
    elif command == "revokeinvite":
        row = conn.execute(
            "UPDATE invitations SET status='cancelled' WHERE id=%s AND status='open' RETURNING id",
            (argument,),
        ).fetchone()
        if row:
            _audit(conn, update_id, "revoke_invite", argument)
        _notice(conn, key, owner, "Unused invitation cancelled." if row else "No matching open invitation.")
    elif command in ("members", "requests"):
        rows = conn.execute(
            "SELECT id,display_name,status FROM learners WHERE id<>'owner' AND (%s OR status='pending') "
            "ORDER BY updated_at DESC LIMIT 100",
            (command == "members",),
        ).fetchall()
        _notice(
            conn,
            key,
            owner,
            "\n".join(f"{r['id']}: {r['display_name'] or 'Learner'} [{r['status']}]" for r in rows)
            or "No matching learners.",
        )
    else:
        if argument == "owner":
            _notice(conn, key, owner, "The owner cannot be rejected or revoked.")
            return
        member = conn.execute("SELECT * FROM learners WHERE id=%s FOR UPDATE", (argument,)).fetchone()
        if member is None or member["id"] == "owner":
            _notice(conn, key, owner, "Use a learner ID from /requests or /members.")
            return
        if command in ("approve", "reject") and member["status"] != "pending":
            _notice(
                conn, key, owner, "That learner has no pending invite request. A fresh invite is required."
            )
            return
        if command == "revoke" and member["status"] not in ("active", "pending"):
            _notice(conn, key, owner, "That learner does not currently have active or pending access.")
            return
        if command == "approve":
            count = conn.execute("SELECT count(*) AS n FROM learners WHERE status='active'").fetchone()["n"]
            if count >= config.max_learners:
                _notice(
                    conn,
                    key,
                    owner,
                    f"Active learner limit ({config.max_learners}, including you) reached. "
                    "Review free-tier capacity before increasing MAX_LEARNERS.",
                )
                return
        status = {"approve": "active", "reject": "rejected", "revoke": "revoked"}[command]
        _invalidate(conn, member["id"])
        member = conn.execute(
            "UPDATE learners SET status=%s,generation=generation+1,updated_at=now() WHERE id=%s RETURNING *",
            (status, member["id"]),
        ).fetchone()
        _audit(conn, update_id, command, member["id"])
        _notice(
            conn,
            key,
            owner,
            f"{member['id']}: access {status}. "
            "Only access status was changed; their private history is preserved.",
        )
        message = {
            "active": "Your invitation has been approved. Use /setup to start, or /profile to view your own profile. "
            "Your private learning data is not published to the owner's dashboard.",
            "rejected": "Your access request was rejected. No coaching access has been granted.",
            "revoked": "Your bot access was revoked. Queued coaching has been cancelled. "
            "A new invitation and approval are required to return.",
        }[status]
        _notice(conn, key, member, message, suffix="learner-status")


def _claim(conn, update_id, key, actor, display_name, owner, token, current):
    digest = hashlib.sha256(token.encode()).hexdigest()
    invite = conn.execute(
        "SELECT * FROM invitations WHERE token_hash=%s AND status='open' AND expires_at>now() FOR UPDATE",
        (digest,),
    ).fetchone()
    if not invite:
        return "invalid_invite"
    if current and current["status"] in ("active", "pending"):
        _job(conn, key, current, {"type": "access_claim"}, done=True)
        _notice(
            conn,
            key,
            current,
            "You already have access."
            if current["status"] == "active"
            else "Your request is already waiting for the owner's approval.",
        )
        return current["status"]
    pending = conn.execute("SELECT count(*) AS n FROM learners WHERE status='pending'").fetchone()["n"]
    if pending >= 100:
        return "pending_capacity_reached"
    ident = current["id"] if current else "u_" + uuid4().hex[:12]
    if current:
        _invalidate(conn, ident)
        member = conn.execute(
            "UPDATE learners SET status='pending',display_name=%s,generation=generation+1,updated_at=now() "
            "WHERE id=%s RETURNING *",
            (display_name, ident),
        ).fetchone()
    else:
        member = conn.execute(
            "INSERT INTO learners(id,telegram_id,display_name,status) VALUES (%s,%s,%s,'pending') RETURNING *",
            (ident, actor, display_name),
        ).fetchone()
    conn.execute(
        "INSERT INTO coach_state(learner_id,body) VALUES (%s,'{}') ON CONFLICT(learner_id) DO NOTHING",
        (ident,),
    )
    conn.execute("UPDATE invitations SET status='claimed',claimed_by=%s WHERE id=%s", (ident, invite["id"]))
    conn.execute("UPDATE telegram_receipts SET learner_id=%s WHERE update_id=%s", (ident, update_id))
    _job(conn, key, member, {"type": "access_claim", "invite_id": invite["id"]}, done=True)
    _notice(
        conn,
        key,
        member,
        "Invitation received. Access is pending the owner's approval. "
        "Do not send your resume or private answers until you are approved.",
    )
    _notice(
        conn,
        key,
        owner,
        f"Invited learner requests access:\n{display_name or 'Learner'}\nID: {ident}\n"
        f"/approve {ident}\n/reject {ident}",
        suffix="owner-request",
    )
    _audit(conn, update_id, "claim_invite", ident)
    return "pending"


def accept_update(repo, update_id: int, payload: dict, config) -> str:
    actor = payload["actor_id"]
    if type(actor) is not int or actor <= 0 or config.owner_id <= 0:
        return "denied"
    key = f"telegram:{update_id}"
    text = payload.get("text", "").strip()
    parts = text.split(None, 1)
    command = parts[0].split("@")[0].lstrip("/").lower() if parts and text.startswith("/") else ""
    argument = parts[1].strip() if len(parts) == 2 else ""
    with repo.connection() as conn:
        # Admission operations serialize briefly; this is never held over AI/Telegram/network calls.
        owner = conn.execute("SELECT * FROM learners WHERE id='owner' FOR UPDATE").fetchone()
        member = (
            owner
            if actor == config.owner_id
            else conn.execute(
                "SELECT * FROM learners WHERE telegram_id=%s FOR UPDATE",
                (actor,),
            ).fetchone()
        )
        receipt = conn.execute(
            "INSERT INTO telegram_receipts(update_id,learner_id,disposition) VALUES (%s,%s,'received') "
            "ON CONFLICT DO NOTHING RETURNING update_id",
            (update_id, member["id"] if member else None),
        ).fetchone()
        if not receipt or conn.execute("SELECT 1 FROM jobs WHERE id=%s", (key,)).fetchone():
            return "duplicate"
        outcome = "invite_required"
        if command in ADMIN_COMMANDS:
            if actor != config.owner_id:
                if member:
                    _job(conn, key, member, {"type": "access_denied"}, done=True)
                    _notice(conn, key, member, "Only the bot owner can manage invitations or access.")
                outcome = "denied"
            else:
                _admin(conn, update_id, key, owner, command, argument, config)
                outcome = "admin_handled"
        elif command in ("start", "join") and INVITE_TOKEN.fullmatch(argument):
            if actor == config.owner_id:
                _job(conn, key, owner, {"type": "access_claim"}, done=True)
                _notice(conn, key, owner, "You are the administrator. Share the invitation with a learner.")
                outcome = "admin_handled"
            else:
                name = re.sub(r"[\r\n\t]+", " ", payload.get("display_name", ""))[:100]
                outcome = _claim(
                    conn,
                    update_id,
                    key,
                    actor,
                    name,
                    owner,
                    INVITE_TOKEN.fullmatch(argument).group(1),
                    member,
                )
        elif member and member["status"] == "active":
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
                outcome = "rate_limited"
            else:
                target = conn.execute(
                    "SELECT displayed_target FROM coach_state WHERE learner_id=%s", (member["id"],)
                ).fetchone()["displayed_target"]
                data = {k: v for k, v in payload.items() if k not in ("actor_id", "display_name")}
                data["target"] = target
                _job(conn, key, member, data)
                outcome = "queued"
        elif member:
            recent = conn.execute(
                "SELECT count(*) AS n FROM jobs WHERE learner_id=%s AND created_at>now()-interval '1 minute'",
                (member["id"],),
            ).fetchone()["n"]
            if recent < 2:
                _job(conn, key, member, {"type": "access_status"}, done=True)
                _notice(
                    conn,
                    key,
                    member,
                    "Access is pending approval."
                    if member["status"] == "pending"
                    else "You do not have coaching access. A new invitation and approval are required.",
                )
            outcome = member["status"]
        conn.execute("UPDATE telegram_receipts SET disposition=%s WHERE update_id=%s", (outcome, update_id))
        return outcome
