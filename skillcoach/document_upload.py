"""Signed learner-only upload preview and confirmation; no public file storage."""

import hashlib
import hmac
import json
import subprocess
import sys
from datetime import timedelta
from uuid import UUID

from psycopg.types.json import Jsonb

from skillcoach.documents import (
    MAX_FILE,
    MAX_FILE_LABEL,
    DocumentError,
    profile_hash,
    require_profile,
    text_value,
)
from skillcoach.models import State


def extract(raw, filename, kind):
    if not 0 < len(raw) <= MAX_FILE:
        raise DocumentError(f"Upload a PDF or UTF-8 TXT file no larger than {MAX_FILE_LABEL}.")
    if filename.lower().endswith(".txt"):
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeError:
            raise DocumentError("TXT files must use UTF-8 encoding.") from None
        if raw.startswith(b"%PDF-"):
            raise DocumentError("A PDF must use the .pdf file type.")
    elif filename.lower().endswith(".pdf"):
        if not raw.startswith(b"%PDF-"):
            raise DocumentError("The uploaded file is not a PDF.")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "skillcoach.document_extract"],
                input=raw,
                capture_output=True,
                timeout=8,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise DocumentError(
                "PDF processing exceeded its limit. Upload a simpler PDF or UTF-8 TXT."
            ) from None
        if result.returncode or len(result.stdout) > 100000:
            raise DocumentError("PDF processing exceeded its limits or failed. Use UTF-8 TXT.")
        try:
            body = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            raise DocumentError("PDF could not be read. Use UTF-8 TXT.") from None
        errors = {
            "encrypted_pdf": "Encrypted PDFs are not supported. Upload an unencrypted text PDF.",
            "pdf_page_limit": "PDFs may contain at most 15 pages.",
            "document_text_limit": "Document text may contain at most 16000 characters.",
            "pdf_has_no_text": "This PDF has no selectable text. Paste text or upload TXT; no OCR is performed.",
        }
        if body.get("error") or not isinstance(body.get("text"), str):
            raise DocumentError(errors.get(body.get("error"), "This PDF could not be read. Use UTF-8 TXT."))
        text = body["text"]
    else:
        raise DocumentError(
            "Supported uploads: text-based PDF and UTF-8 TXT. DOCX and images are not supported."
        )
    return text_value(text, kind)


def confirmation(config, row):
    value = json.dumps(
        {
            key: str(row[key])
            for key in (
                "id",
                "learner_id",
                "access_generation",
                "auth_hash",
                "kind",
                "content_hash",
                "profile_hash",
                "plan_id",
                "expires_at",
            )
        },
        sort_keys=True,
    )
    return hmac.new(config.webhook_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def member_state(conn, learner_id, generation):
    member = conn.execute("SELECT * FROM learners WHERE id=%s FOR UPDATE", (learner_id,)).fetchone()
    if not member or member["status"] != "active" or member["generation"] != generation:
        raise DocumentError("Access changed. Reopen your personal dashboard.")
    row = conn.execute("SELECT body FROM coach_state WHERE learner_id=%s", (learner_id,)).fetchone()
    state = State.model_validate(row["body"])
    require_profile(state)
    return state


def preview(runtime, identity, identifier, kind, raw, filename):
    try:
        identifier = str(UUID(identifier))
    except (ValueError, TypeError, AttributeError):
        raise DocumentError("A valid upload request identifier is required.") from None
    if kind not in ("resume", "jd") or not 0 < len(raw) <= MAX_FILE:
        raise DocumentError(f"Choose resume or job description and a PDF/TXT file up to {MAX_FILE_LABEL}.")
    # Include format, not filename, in the idempotency binding.
    suffix = filename.rsplit(".", 1)[-1].lower()
    fingerprint = hashlib.sha256(kind.encode() + b":" + suffix.encode() + b":" + raw).hexdigest()
    learner, generation, auth_hash = identity
    with runtime.repo.connection() as conn:
        state = member_state(conn, learner, generation)
        conn.execute(
            "UPDATE learner_document_requests SET text='',status='cancelled' "
            "WHERE expires_at<now() AND status IN ('processing','ready','failed')"
        )
        conn.execute(
            "DELETE FROM learner_document_requests WHERE expires_at<now()-interval '1 day' "
            "AND status<>'queued'"
        )
        row = conn.execute(
            "SELECT * FROM learner_document_requests WHERE learner_id=%s AND id=%s", (learner, identifier)
        ).fetchone()
        if row:
            if row["expires_at"] <= runtime.clock():
                raise DocumentError("This preview expired. Choose the file again to create a new request.")
            if (
                row["content_hash"] != fingerprint
                or row["auth_hash"] != auth_hash
                or row["access_generation"] != generation
            ):
                raise DocumentError("That upload identifier belongs to a different document or session.")
            if row["status"] not in ("ready", "queued"):
                raise DocumentError(
                    "This upload is processing or failed. Wait briefly, then choose the file again."
                )
            return preview_result(runtime, row)
        count = conn.execute(
            "SELECT count(*) AS n FROM learner_document_requests WHERE learner_id=%s "
            "AND created_at>now()-interval '1 hour'",
            (learner,),
        ).fetchone()["n"]
        if count >= 10:
            raise DocumentError("Upload limit reached. Try again in an hour.")
        row = conn.execute(
            "INSERT INTO learner_document_requests(id,learner_id,access_generation,auth_hash,kind,content_hash,"
            "profile_hash,plan_id,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (
                identifier,
                learner,
                generation,
                auth_hash,
                kind,
                fingerprint,
                profile_hash(state),
                state.journey.active_id if state.journey else None,
                runtime.clock() + timedelta(minutes=5),
            ),
        ).fetchone()
    try:
        text = extract(raw, filename, kind)  # No database transaction remains open while parsing.
    except DocumentError:
        with runtime.repo.connection() as conn:
            conn.execute(
                "UPDATE learner_document_requests SET status='failed' WHERE learner_id=%s AND id=%s",
                (learner, identifier),
            )
        raise
    with runtime.repo.connection() as conn:
        state = member_state(conn, learner, generation)
        if profile_hash(state) != row["profile_hash"] or runtime.clock() >= row["expires_at"]:
            raise DocumentError("Profile changed or preview expired during parsing. Upload again.")
        row = conn.execute(
            "UPDATE learner_document_requests SET status='ready',text=%s "
            "WHERE learner_id=%s AND id=%s AND status='processing' RETURNING *",
            (text, learner, identifier),
        ).fetchone()
    return preview_result(runtime, row)


def preview_result(runtime, row):
    return {
        "request_id": row["id"],
        "confirmation": confirmation(runtime.config, row),
        "characters": len(row["text"]),
        "kind": row["kind"],
        "expires_at": row["expires_at"].isoformat(),
        "can_revise": row["plan_id"] is not None,
        "status": row["status"],
    }


def confirm(runtime, identity, identifier, token, choice):
    if choice not in ("keep", "revise", "cancel") or not isinstance(token, str):
        raise DocumentError("Choose Keep current plan, Revise future sessions or Cancel.")
    learner, generation, auth_hash = identity
    with runtime.repo.connection() as conn:
        state = member_state(conn, learner, generation)
        row = conn.execute(
            "SELECT * FROM learner_document_requests WHERE learner_id=%s AND id=%s FOR UPDATE",
            (learner, identifier),
        ).fetchone()
        if (
            not row
            or row["auth_hash"] != auth_hash
            or row["access_generation"] != generation
            or not hmac.compare_digest(token, confirmation(runtime.config, row))
        ):
            raise DocumentError("The document preview does not belong to this session.")
        if row["status"] == "queued":
            if row["choice"] != choice:
                raise DocumentError("This upload was already confirmed with a different choice.")
            return {"queued": True, "duplicate": True}
        if row["status"] != "ready" or runtime.clock() >= row["expires_at"]:
            raise DocumentError("This preview expired or was cancelled. Upload again.")
        if choice == "cancel":
            conn.execute(
                "UPDATE learner_document_requests SET status='cancelled',text='' "
                "WHERE learner_id=%s AND id=%s",
                (learner, identifier),
            )
            return {"cancelled": True}
        if profile_hash(state) != row["profile_hash"]:
            raise DocumentError("Your profile changed. Upload again to review the current version.")
        if choice == "revise" and (
            not state.journey
            or state.journey.active_id != row["plan_id"]
            or not row["plan_id"]
            or state.journey.proposed_id
            or state.journey.stage != "active"
        ):
            raise DocumentError(
                "The plan changed or has a revision in progress. Save with Keep current plan."
            )
        key = f"document:{learner}:{identifier}"
        conn.execute(
            "INSERT INTO jobs(id,payload,learner_id,access_generation) VALUES (%s,%s,%s,%s)",
            (
                key,
                Jsonb(
                    {
                        "type": "document",
                        "kind": row["kind"],
                        "text": row["text"],
                        "choice": choice,
                        "profile_hash": row["profile_hash"],
                        "plan_id": row["plan_id"],
                    }
                ),
                learner,
                generation,
            ),
        )
        conn.execute(
            "UPDATE learner_document_requests SET status='queued',choice=%s,text='' "
            "WHERE learner_id=%s AND id=%s",
            (choice, learner, identifier),
        )
    return {"queued": True, "duplicate": False}
