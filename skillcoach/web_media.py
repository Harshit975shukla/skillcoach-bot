"""Lesson videos inside web messages.

A media worker renders a lesson's storyboard (or diagram) with the same local renderers as Telegram
mode, stores the result privately in PostgreSQL in bounded chunks and only then marks the message sent,
in the same transaction that records which media the message shows. The browser plays it from
/web/media/<id>. Every request checks the signed-in learner, the session, the access generation and
that learner's own sent message, serves at most one byte range, and spends a per-learner daily and an
overall monthly byte budget reserved before anything is read or returned.

Stored video is a derivative of the lesson data and can be rendered again; it is not learner state that
backups must restore byte for byte, and old videos are removed by retention. Nothing here is DRM: a
learner who can watch a video can also save it.
"""

import hashlib
import json
import logging
import math
import re
import tempfile
import threading
import time
from pathlib import Path
from uuid import uuid4

from psycopg.types.json import Jsonb

from skillcoach.clients import HTTP, Budget, ExternalError
from skillcoach.storage import LESSON_JOBS, MembershipChanged
from skillcoach.timeutil import IST

log = logging.getLogger(__name__)

VIDEO_BYTES = 3_670_016  # 3.5 MiB: a whole video fits one response under Vercel's 4.5 MB limit
IMAGE_BYTES = 524_288
CHUNK_BYTES = 524_288
STORE_BYTES = 120 * 1024 * 1024  # every stored or reserved media byte, posters included
DATABASE_GUARD = 350_000_000  # no new media once the database passes this (free plan: 500 MB)
DATABASE_SIZE_SECONDS = 300
RESERVE_SECONDS = 600
RETENTION_DAYS = 30
DAILY_BYTES = 64 * 1024 * 1024  # returned to one learner per IST day
MONTHLY_BYTES = 2 * 1024 * 1024 * 1024  # returned to everyone per IST calendar month
WAKE_SECONDS = 240
WAKE_PER_DAY = 48
WAKE_WORKFLOW = "recovery.yml"
WAKE_REF = "main"
DIAGRAM_RENDERER = "diagram-1"
STORE_LOCK = 7429042
USAGE_LOCK = 7429043
MEDIA_ID = re.compile(r"[0-9a-f]{32}")
RANGE = re.compile(r"bytes=(\d{0,15})-(\d{0,15})")
# Renderers missing on one worker are not the lesson's fault: an equipped worker retries.
INFRASTRUCTURE = frozenset(
    {
        "ffmpeg_missing",
        "readable_render_font_missing",
        "local_mermaid_renderer_missing",
        "offline_narrator_missing_use_voice_off_or_install_espeak_ng",
    }
)
NOT_FOUND = (404, {"Content-Type": "application/json"}, b'{"error":"Not found."}')
LIMITED = (
    429,
    {"Content-Type": "application/json"},
    b'{"error":"The video limit for today is reached. Open the lesson page for the walkthrough."}',
)
# This learner's own waiting lesson videos, or lesson preparation (/learn, a scheduled lesson, a plan
# lesson) that only a worker will now pick up: the only work a page may wake a worker for. Ordinary
# commands and replies never consume the shared wake budget.
WAITING = (
    "SELECT 1 FROM learners l WHERE l.id=%(learner)s AND l.status='active' AND l.generation=%(generation)s "
    "AND (EXISTS (SELECT 1 FROM outbox o WHERE o.learner_id=l.id AND o.access_generation=l.generation "
    "AND o.status IN ('pending','failed') AND o.attempts<5 AND o.available_at<=now() "
    "AND o.body->>'kind'='media') OR EXISTS (SELECT 1 FROM jobs j WHERE j.learner_id=l.id "
    "AND j.access_generation=l.generation AND j.status IN ('pending','failed') AND j.attempts<5 "
    "AND j.available_at<=now() AND " + LESSON_JOBS + "))"
)


class MediaUnavailable(Exception):
    """This message's video will not exist: it goes out with an honest note instead."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# Identity and rendering -------------------------------------------------------------------------


def identity(body: dict, learner_id: str) -> tuple[str, str | None]:
    """The asset key and the learner the media belongs to (None for shared reviewed/library media)."""
    mode = body.get("mode")
    if mode not in ("video", "static") or not ("storyboard" in body or "code" in body):
        raise MediaUnavailable("not_made")
    if "storyboard" in body:
        from pydantic import ValidationError

        from skillcoach.storyboard import Storyboard, asset_key

        try:
            story = Storyboard.model_validate(body["storyboard"])
        except ValidationError:
            raise MediaUnavailable("not_made") from None
        shared = bool(body.get("shared_reviewed") or body.get("shared_library"))
        key = asset_key(
            story,
            learner_id,
            voice=bool(body.get("voice")) and mode == "video",
            shared_reviewed=body.get("shared_reviewed", False),
            shared_library=body.get("shared_library", False),
        )
        return f"{key}:{mode}", None if shared else learner_id
    data = {
        "diagram": body["code"],
        "caption": body["caption"][:150],
        "mode": mode,
        "scope": learner_id,
        "renderer": DIAGRAM_RENDERER,
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest() + ":" + mode, learner_id


def _part(role: str, path: Path) -> dict:
    from PIL import Image

    data = path.read_bytes()
    if role == "video":
        return {"role": role, "mime": "video/mp4", "data": data, "details": {}}
    with Image.open(path) as image:
        width, height = image.size
    return {"role": role, "mime": "image/png", "data": data, "details": {"width": width, "height": height}}


def render(body: dict, folder: Path, budget: Budget) -> list[dict]:
    """Render with the shared local renderers. Video plus poster, or one still image."""
    if "storyboard" in body:
        from skillcoach.story_renderer import render_storyboard
        from skillcoach.storyboard import Storyboard

        path, meta = render_storyboard(
            Storyboard.model_validate(body["storyboard"]),
            folder,
            budget,
            voice=body.get("voice", False),
            static=body["mode"] == "static",
            reviewed=body.get("shared_reviewed", False),
        )
        if meta["kind"] != "video":
            return [_part("image", path)]
        video = _part("video", path)
        video["details"] = {
            "duration": round(meta["duration"], 1),
            "width": meta["width"],
            "height": meta["height"],
            "voice": bool(meta["voice"]),
        }
        return [video, _part("poster", folder / "storyboard.png")]
    from skillcoach.media import animate, render_png

    image = render_png(body["code"], folder)
    video = animate(image, folder, body["caption"]) if body["mode"] == "video" else None
    if video is None:
        return [_part("image", image)]
    part = _part("video", video)
    poster = _part("poster", image)
    part["details"] = {"duration": 25.0, "width": 1280, "height": 720, "voice": False}
    return [part, poster]


def bounded(files: list[dict]) -> list[dict]:
    """Apply the size caps: an oversized video or still means no media; an oversized poster is dropped."""
    kept = []
    for item in files:
        limit = VIDEO_BYTES if item["role"] == "video" else IMAGE_BYTES
        if len(item["data"]) <= limit:
            kept.append(item)
        elif item["role"] != "poster":
            raise MediaUnavailable("too_large")
    return kept


# Private storage --------------------------------------------------------------------------------


def ready(repo, key: str) -> dict | None:
    """The complete stored set for this asset key, by role, or None."""
    with repo.connection() as conn:
        return _ready(conn, key)


def _ready(conn, key):
    rows = conn.execute(
        "SELECT id, role, state, details FROM web_media WHERE asset_key=%s", (key,)
    ).fetchall()
    if not rows or any(row["state"] != "ready" for row in rows):
        return None
    found = {row["role"]: {"id": row["id"], "details": row["details"]} for row in rows}
    return found if "video" in found or "image" in found else None


_size = {"at": float("-inf"), "bytes": 0}
_size_lock = threading.Lock()


def database_size(repo) -> int:
    """The physical watermark (deleted media become reusable space only after vacuum, so the database
    size is checked as well as the stored bytes). pg_database_size reads every file's size, so a
    process measures it at most every DATABASE_SIZE_SECONDS; the store cap bounds growth meanwhile."""
    with _size_lock:
        if time.monotonic() - _size["at"] > DATABASE_SIZE_SECONDS:
            with repo.connection() as conn:
                # A timeout set by a statement applies from the next statement on.
                conn.execute("SELECT set_config('statement_timeout','15s',true)")
                _size["bytes"] = conn.execute("SELECT pg_database_size(current_database()) AS n").fetchone()["n"]
            _size["at"] = time.monotonic()
        return _size["bytes"]


def _prune(conn, need: int):
    """Inside the store lock: drop abandoned reservations, then media unseen for the retention period,
    then (only if still over the cap) the least recently shown. Never media stored in the last day."""
    conn.execute(
        "DELETE FROM web_media WHERE asset_key IN (SELECT asset_key FROM web_media "
        "WHERE state='reserved' AND reserved_until<=now())"
    )
    conn.execute(
        "DELETE FROM web_media WHERE asset_key IN (SELECT asset_key FROM web_media GROUP BY asset_key "
        "HAVING bool_and(state='ready') AND max(last_used_at) < now() - make_interval(days => %s) "
        "AND max(created_at) < now() - interval '1 day')",
        (RETENTION_DAYS,),
    )
    used = conn.execute("SELECT coalesce(sum(bytes),0) AS n FROM web_media").fetchone()["n"]
    if used + need <= STORE_BYTES:
        return
    groups = conn.execute(
        "SELECT asset_key, sum(bytes) AS size FROM web_media GROUP BY asset_key "
        "HAVING bool_and(state='ready') AND max(created_at) < now() - interval '1 day' "
        "ORDER BY max(last_used_at), asset_key LIMIT 500"
    ).fetchall()
    victims, freed = [], 0
    for group in groups:
        if used - freed + need <= STORE_BYTES:
            break
        victims.append(group["asset_key"])
        freed += group["size"]
    if victims:
        conn.execute("DELETE FROM web_media WHERE asset_key = ANY(%s)", (victims,))


def store(repo, key: str, learner_id: str | None, files: list[dict]) -> dict:
    """Reserve capacity for the whole set, write its chunks, then verify and publish it atomically.

    The reservation (under one advisory lock, a short transaction) counts every stored byte and every
    unfinished reservation against the cap and refuses new media past the database watermark. Chunks
    are written in their own short transactions; nothing is locked while rendering or uploading."""
    lease = uuid4().hex
    plan = [
        {
            **item,
            "id": uuid4().hex,
            "sha256": hashlib.sha256(item["data"]).hexdigest(),
            "chunks": math.ceil(len(item["data"]) / CHUNK_BYTES),
        }
        for item in files
    ]
    need = sum(len(item["data"]) for item in plan)
    size = database_size(repo)
    with repo.connection() as conn:
        # Writers take turns under the store lock; each turn is a few short statements.
        conn.execute(
            "SELECT set_config('lock_timeout','15s',true), set_config('statement_timeout','20s',true)"
        )
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (STORE_LOCK,))
        existing = _ready(conn, key)
        if existing:
            return existing
        if size > DATABASE_GUARD:
            raise MediaUnavailable("storage_full")
        rows = conn.execute(
            "SELECT state, reserved_until>now() AS active FROM web_media WHERE asset_key=%s", (key,)
        ).fetchall()
        if any(row["state"] == "reserved" and row["active"] for row in rows):
            raise ExternalError("media_busy")
        # An expired reservation or an incomplete set for this key: its writer is gone.
        conn.execute("DELETE FROM web_media WHERE asset_key=%s", (key,))
        _prune(conn, need)
        used = conn.execute("SELECT coalesce(sum(bytes),0) AS n FROM web_media").fetchone()["n"]
        if used + need > STORE_BYTES:
            raise MediaUnavailable("storage_full")
        for item in plan:
            conn.execute(
                "INSERT INTO web_media(id,asset_key,role,learner_id,mime,bytes,chunks,sha256,lease,"
                "reserved_until,details) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                "now()+make_interval(secs => %s),%s)",
                (
                    item["id"],
                    key,
                    item["role"],
                    learner_id,
                    item["mime"],
                    len(item["data"]),
                    item["chunks"],
                    item["sha256"],
                    lease,
                    RESERVE_SECONDS,
                    Jsonb(item["details"]),
                ),
            )
    try:
        for item in plan:
            for seq in range(item["chunks"]):
                _write_chunk(repo, item["id"], lease, seq, item["data"][seq * CHUNK_BYTES : (seq + 1) * CHUNK_BYTES])
        return _finalize(repo, plan, lease)
    except BaseException:
        _abandon(repo, plan, lease)
        raise


def _write_chunk(repo, media_id: str, lease: str, seq: int, data: bytes):
    with repo.connection() as conn:
        row = conn.execute(
            "UPDATE web_media SET reserved_until=now()+make_interval(secs => %s) WHERE id=%s "
            "AND state='reserved' AND lease=%s AND reserved_until>now() RETURNING chunks",
            (RESERVE_SECONDS, media_id, lease),
        ).fetchone()
        if not row or seq >= row["chunks"] or not 0 < len(data) <= CHUNK_BYTES:
            raise ExternalError("media_reservation_lost")
        conn.execute(
            "INSERT INTO web_media_chunks(media_id,seq,data) VALUES (%s,%s,%s) "
            "ON CONFLICT (media_id,seq) DO UPDATE SET data=EXCLUDED.data",
            (media_id, seq, data),
        )


def _finalize(repo, plan: list[dict], lease: str) -> dict:
    ids = [item["id"] for item in plan]
    with repo.connection() as conn:
        held = conn.execute(
            "SELECT id FROM web_media WHERE id = ANY(%s) AND state='reserved' AND lease=%s "
            "AND reserved_until>now() FOR UPDATE",
            (ids, lease),
        ).fetchall()
        if len(held) != len(ids):
            raise ExternalError("media_reservation_lost")
        stored = {
            row["media_id"]: row
            for row in conn.execute(
                "SELECT media_id, count(*) AS n, max(seq) AS last, sum(octet_length(data)) AS size, "
                "encode(sha256(string_agg(data, ''::bytea ORDER BY seq)), 'hex') AS digest "
                "FROM web_media_chunks WHERE media_id = ANY(%s) GROUP BY media_id",
                (ids,),
            )
        }
        for item in plan:
            found = stored.get(item["id"])
            if (
                not found
                or found["n"] != item["chunks"]
                or found["last"] != item["chunks"] - 1
                or found["size"] != len(item["data"])
                or found["digest"] != item["sha256"]
            ):
                raise ExternalError("media_integrity_failed")
        conn.execute(
            "UPDATE web_media SET state='ready', lease=NULL, reserved_until=NULL, last_used_at=now() "
            "WHERE id = ANY(%s)",
            (ids,),
        )
    return {item["role"]: {"id": item["id"], "details": item["details"]} for item in plan}


def _abandon(repo, plan: list[dict], lease: str):
    """Best effort: release this writer's own unfinished reservation (expiry also reclaims it)."""
    try:
        with repo.connection() as conn:
            conn.execute(
                "DELETE FROM web_media WHERE id = ANY(%s) AND lease=%s AND state='reserved'",
                ([item["id"] for item in plan], lease),
            )
    except Exception:
        log.warning("web_media_reservation_left reason=cleanup_failed")


# Delivery ---------------------------------------------------------------------------------------


def note_for(body: dict, found: dict) -> dict:
    """What the message shows: the stored media, the caption and its honesty labels."""
    from skillcoach.media import diagram_caption, storyboard_caption

    kind = "video" if "video" in found else "image"
    if "storyboard" in body:
        caption = body["caption"][:500]
        full = storyboard_caption(body, still=kind == "image")
    else:
        caption = body["caption"]
        full = diagram_caption(body, animated=kind == "video")
    labels = [line for line in full[len(caption) :].split("\n") if line.strip()]
    note = {"status": "ready", "type": kind, kind: found[kind]["id"], "text": caption, "labels": labels}
    if "poster" in found:
        note["poster"] = found["poster"]["id"]
    facts = found[kind]["details"]
    note.update({k: facts[k] for k in ("duration", "width", "height", "voice") if k in facts})
    return note


def attach(runtime, scoped, outbox_id: str, token: str, found: dict, note: dict, *, voiced=False) -> str:
    """Publish the message with its media (or its honest note) in one short fenced transaction.

    Locks follow the order of domain work (learner, then coaching state, then the message), so this
    waits for a concurrent pause, revocation or plan change instead of deadlocking with it. Under those
    locks it applies the same rules as the start of delivery, against the state as it is now: the
    learner's access, a pause, a passed scheduled day, a replaced plan or topic, and narration that was
    turned off while rendering. Returns "sent" or "suppressed"; a message that is no longer pending
    (suppressed meanwhile) is never brought back."""
    from skillcoach.models import State
    from skillcoach.runtime import DeliveryDeferred, stale_delivery

    ids = {role: item["id"] for role, item in found.items()}
    today = runtime.clock().astimezone(IST).date().isoformat()
    with scoped.connection() as conn:
        scoped._fence(conn, "delivery", token)
        member = conn.execute(
            "SELECT status, generation FROM learners WHERE id=%s FOR UPDATE", (scoped.learner_id,)
        ).fetchone()
        state = conn.execute(
            "SELECT body FROM coach_state WHERE learner_id=%s FOR UPDATE", (scoped.learner_id,)
        ).fetchone()
        item = conn.execute(
            "SELECT status, access_generation, body FROM outbox WHERE id=%s AND learner_id=%s FOR UPDATE",
            (outbox_id, scoped.learner_id),
        ).fetchone()
        if not item or item["status"] not in ("pending", "failed"):
            return "suppressed"
        if not member or not state or member["status"] != "active" or member["generation"] != item["access_generation"]:
            scoped._finish_delivery(conn, outbox_id, "suppressed")
            return "suppressed"
        current = State.model_validate(state["body"])
        if stale_delivery(current, item["body"], today):
            scoped._finish_delivery(conn, outbox_id, "suppressed")
            return "suppressed"
        if voiced and not (current.voice and runtime.config.narration_enabled):
            raise DeliveryDeferred()
        if ids:
            kept = conn.execute(
                "SELECT id FROM web_media WHERE id = ANY(%s) AND state='ready' FOR SHARE",
                (list(ids.values()),),
            ).fetchall()
            if len(kept) != len(ids):
                raise ExternalError("media_missing")
            for role, media_id in ids.items():
                conn.execute(
                    "INSERT INTO web_media_refs(outbox_id,role,media_id) VALUES (%s,%s,%s) "
                    "ON CONFLICT (outbox_id,role) DO UPDATE SET media_id=EXCLUDED.media_id",
                    (outbox_id, role, media_id),
                )
            conn.execute(
                "UPDATE web_media SET last_used_at=now() WHERE id = ANY(%s)", (list(ids.values()),)
            )
        conn.execute(
            "UPDATE outbox SET body = body || %s WHERE id=%s AND learner_id=%s",
            (Jsonb({"web_media": note}), outbox_id, scoped.learner_id),
        )
        scoped._finish_delivery(conn, outbox_id, "sent")
        # Both mode: the message (or its honest note) may also go to Telegram.
        from skillcoach.telegram_copies import create_copy

        create_copy(conn, runtime.config, scoped.learner_id, outbox_id)
    return "sent"


def record_failure(scoped, outbox_id: str, token: str, code: str):
    """A current render or storage failure: retried automatically, never mistaken for Telegram-era
    history (the WEB_FAILURE marker is written with the failure), and shown to the learner as a video
    being prepared rather than as a /retry instruction."""
    from skillcoach.storage import WEB_FAILURE

    with scoped.connection() as conn:
        scoped._fence(conn, "delivery", token)
        conn.execute(
            "UPDATE outbox SET body = body || jsonb_build_object(%s::text, %s::text) "
            "WHERE id=%s AND learner_id=%s AND status IN ('pending','failed')",
            (WEB_FAILURE, code, outbox_id, scoped.learner_id),
        )
        scoped._finish_delivery(conn, outbox_id, "failed", code, notice=False)


def deliver(runtime, scoped, item: dict, body: dict, token: str, budget: Budget) -> bool:
    """One media message in web mode, on a worker with the renderers installed. Nothing is locked
    while rendering or uploading; the message is published only by attach()."""
    from skillcoach.runtime import DeliveryDeferred

    final = item.get("attempts", 0) >= 4
    try:
        try:
            scoped.ensure_delivery_authorized(item["id"], token)
            key, owner = identity(body, scoped.learner_id)
            found = ready(scoped, key)
            if not found:
                with tempfile.TemporaryDirectory(prefix="skillcoach-web-media-") as tmp:
                    try:
                        files = bounded(render(body, Path(tmp), budget))
                    except OSError:
                        # A local file problem while rendering: retried like any passing fault.
                        raise ExternalError("render_io_failed") from None
                found = store(scoped, key, owner, files)
            note = note_for(body, found)
            attach(runtime, scoped, item["id"], token, found, note, voiced=bool(note.get("voice")))
            return True
        except ExternalError as exc:
            permanent = not exc.retryable and exc.code not in INFRASTRUCTURE
            if not (permanent or final):
                log.warning("delivery_failed kind=media code=%s", exc.code)
                record_failure(scoped, item["id"], token, exc.code)
                return True
            log.warning("web_media_unavailable reason=not_made code=%s", exc.code)
            raise MediaUnavailable("not_made") from None
    except MediaUnavailable as exc:
        if exc.reason != "not_made":
            log.warning("web_media_unavailable reason=%s", exc.reason)
        attach(runtime, scoped, item["id"], token, {}, {"status": "unavailable", "reason": exc.reason})
        return True
    except DeliveryDeferred:
        return False
    except MembershipChanged:
        scoped.delivery_result(item["id"], token, "suppressed")
        return True

# Serving ----------------------------------------------------------------------------------------


def parse_range(header: str | None, size: int):
    """One byte range as (start, end) inclusive; None to serve the whole file (no, invalid or
    multiple ranges, which HTTP lets a server ignore); "unsatisfiable" for a range past the end."""
    if not header:
        return None
    match = RANGE.fullmatch(header.replace(" ", ""))
    if not match or not (match[1] or match[2]):
        return None
    if not match[1]:
        suffix = int(match[2])
        return (max(0, size - suffix), size - 1) if suffix else "unsatisfiable"
    start = int(match[1])
    if match[2] and int(match[2]) < start:
        return None
    if start >= size:
        return "unsatisfiable"
    return start, min(int(match[2]) if match[2] else size - 1, size - 1)


AUTHORIZED = (
    "SELECT m.id, m.mime, m.bytes, m.sha256 FROM web_media m WHERE m.id=%(media)s AND m.state='ready' "
    "AND EXISTS (SELECT 1 FROM web_media_refs r JOIN outbox o ON o.id=r.outbox_id "
    "JOIN learners l ON l.id=o.learner_id JOIN web_sessions s ON s.learner_id=l.id "
    "WHERE r.media_id=m.id AND o.learner_id=%(learner)s AND o.access_generation=%(generation)s "
    "AND o.status='sent' AND l.status='active' AND l.generation=o.access_generation "
    "AND s.token_hash=%(session)s AND s.access_generation=l.generation AND s.expires_at>%(now)s)"
)


def _spend(conn, learner_id: str, day, amount: int) -> bool:
    """Reserve bytes about to be returned. Never refunded: a response that may have reached the
    browser counts even if it fails afterwards."""
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (USAGE_LOCK,))
    totals = conn.execute(
        "SELECT coalesce(sum(bytes),0) AS month, "
        "coalesce(sum(bytes) FILTER (WHERE learner_id=%s AND day=%s),0) AS today "
        "FROM web_media_usage WHERE day >= %s",
        (learner_id, day, day.replace(day=1)),
    ).fetchone()
    if totals["month"] + amount > MONTHLY_BYTES or totals["today"] + amount > DAILY_BYTES:
        return False
    conn.execute(
        "INSERT INTO web_media_usage(learner_id,day,bytes) VALUES (%s,%s,%s) ON CONFLICT (learner_id,day) "
        "DO UPDATE SET bytes=web_media_usage.bytes+EXCLUDED.bytes",
        (learner_id, day, amount),
    )
    return True


def read_all(repo, media_id: str):
    """(mime, bytes) of a stored media file, or None once it is no longer kept. The caller has already
    checked that it belongs to the learner's own sent message."""
    if not MEDIA_ID.fullmatch(media_id or ""):
        return None
    with repo.connection(readonly=True) as conn:
        row = conn.execute(
            "SELECT mime, bytes FROM web_media WHERE id=%s AND state='ready'", (media_id,)
        ).fetchone()
        if not row:
            return None
        return row["mime"], _read(conn, media_id, 0, row["bytes"] - 1)


def _read(conn, media_id: str, start: int, end: int) -> bytes:
    first, last = start // CHUNK_BYTES, end // CHUNK_BYTES
    rows = conn.execute(
        "SELECT seq, data FROM web_media_chunks WHERE media_id=%s AND seq BETWEEN %s AND %s ORDER BY seq",
        (media_id, first, last),
    ).fetchall()
    if [row["seq"] for row in rows] != list(range(first, last + 1)):
        raise ExternalError("media_incomplete")
    data = b"".join(bytes(row["data"]) for row in rows)
    offset = start - first * CHUNK_BYTES
    return data[offset : offset + end - start + 1]


def serve(runtime, session: dict, session_hash: str, media_id: str, method: str, range_header, if_range):
    """(status, headers, body) for GET or HEAD /web/media/<id>, re-authorized on every request.

    The bytes about to be returned are reserved and committed first (a short transaction under the
    usage lock); the chunks are then read in a separate read-only transaction that checks access again.
    """
    if not MEDIA_ID.fullmatch(media_id or ""):
        return NOT_FOUND
    now = runtime.clock()
    lookup = {
        "media": media_id,
        "learner": session["learner_id"],
        "generation": session["access_generation"],
        "session": session_hash,
        "now": now,
    }
    with runtime.repo.connection() as conn:
        row = conn.execute(AUTHORIZED, lookup).fetchone()
        if not row:
            return NOT_FOUND
        size, tag = row["bytes"], f'"{row["sha256"][:40]}"'
        headers = {
            "Content-Type": row["mime"],
            "Accept-Ranges": "bytes",
            "ETag": tag,
            "Content-Disposition": "inline",
            "Cross-Origin-Resource-Policy": "same-origin",
        }
        span = parse_range(range_header, size) if if_range in (None, tag) else None
        if span == "unsatisfiable":
            return 416, {**headers, "Content-Range": f"bytes */{size}", "Content-Length": "0"}, b""
        start, end = span or (0, size - 1)
        headers["Content-Length"] = str(end - start + 1)
        if span:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        status = 206 if span else 200
        if method == "HEAD":
            return status, headers, b""
        if not _spend(conn, session["learner_id"], now.astimezone(IST).date(), end - start + 1):
            return LIMITED
    with runtime.repo.connection(readonly=True) as conn:
        if not conn.execute(AUTHORIZED, lookup).fetchone():
            return NOT_FOUND
        return status, headers, _read(conn, media_id, start, end)


# Waking a rendering worker ------------------------------------------------------------------------


def waiting(conn, learner_id: str, generation: int) -> str | None:
    """"queued" or "delayed" while this learner's own lesson video is still to come, else None."""
    row = conn.execute(
        "SELECT count(*) AS n, bool_or(o.attempts>0 OR o.available_at > now() "
        "OR o.available_at < now() - interval '10 minutes') AS late FROM outbox o "
        "JOIN learners l ON l.id=o.learner_id WHERE o.learner_id=%s AND o.access_generation=%s "
        "AND l.status='active' AND l.generation=o.access_generation AND o.status IN ('pending','failed') "
        "AND o.attempts<5 AND o.body->>'kind'='media'",
        (learner_id, generation),
    ).fetchone()
    if not row["n"]:
        return None
    return "delayed" if row["late"] else "queued"


def wake(runtime, session: dict, *, http=None, settings=None) -> str:
    """Ask GitHub to start the fixed recovery workflow on main, at most once per WAKE_SECONDS and
    WAKE_PER_DAY times a day overall, only for this signed-in learner's own due work, and never while a
    worker holds a lease. The claim is committed before the request and never undone, so concurrent or
    uncertain requests cannot dispatch twice. Learner deliveries are never touched here."""
    from skillcoach.scheduler import REPOSITORY, TriggerSettings

    settings = settings or TriggerSettings.from_env()
    if not settings.token or not REPOSITORY.fullmatch(settings.repo):
        return "unconfigured"
    today = runtime.clock().astimezone(IST).date()
    with runtime.repo.connection() as conn:
        claimed = conn.execute(
            "UPDATE web_media_wake SET requested_at=now(), day=%(today)s, "
            "count=CASE WHEN day=%(today)s THEN count+1 ELSE 1 END "
            "WHERE id=1 AND requested_at < now() - make_interval(secs => %(spacing)s) "
            "AND (day IS DISTINCT FROM %(today)s OR count < %(daily)s) "
            "AND NOT EXISTS (SELECT 1 FROM worker_leases WHERE name IN ('delivery','domain') "
            "AND expires_at > now()) AND EXISTS (" + WAITING + ") RETURNING id",
            {
                "today": today,
                "spacing": WAKE_SECONDS,
                "daily": WAKE_PER_DAY,
                "learner": session["learner_id"],
                "generation": session["access_generation"],
            },
        ).fetchone()
    if not claimed:
        return "skipped"
    try:
        (http or HTTP()).call(
            "POST",
            f"https://api.github.com/repos/{settings.repo}/actions/workflows/{WAKE_WORKFLOW}/dispatches",
            budget=Budget(4),
            attempts=1,
            allow=(204,),
            read_timeout=3,
            headers={
                "Authorization": f"Bearer {settings.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"ref": WAKE_REF},
        )
    except ExternalError as exc:
        log.warning("media_wake_failed code=%s", exc.code)
        return "failed"
    log.info("media_wake_dispatched")
    return "dispatched"
