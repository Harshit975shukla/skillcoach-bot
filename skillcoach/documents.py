"""Private document updates with explicit confirmation; never reset learning history."""

import hashlib
import json
from datetime import timedelta

MAX_TEXT = 16000
MAX_FILE = 256 * 1024


class DocumentError(ValueError):
    pass


def text_value(text, kind):
    if kind not in ("resume", "jd") or not isinstance(text, str):
        raise DocumentError("Choose resume or job description.")
    text = text.strip()
    minimum = 80 if kind == "resume" else 50
    if not minimum <= len(text) <= MAX_TEXT:
        raise DocumentError(f"Use {minimum}-{MAX_TEXT} characters of readable text.")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in text) or "\ufffd" in text:
        raise DocumentError(
            "The document contains unsupported encoding or control characters. Use UTF-8 text."
        )
    return text


def profile_hash(state):
    value = state.profile.model_dump(mode="json") if state.profile else None
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def require_profile(state):
    if state.profile is None:
        raise DocumentError("Finish profile setup first. Documents remain optional during /onboard.")
    if state.focus:
        raise DocumentError("Finish or /cancel the current interactive flow before updating documents.")


def apply_document(service, *, kind, text, expected_hash, choice, expected_plan=None):
    from skillcoach.journey import approved_plan

    state = service.state
    if choice not in ("keep", "revise"):
        raise DocumentError("Choose Keep current plan or Revise future sessions.")
    if not state.profile or profile_hash(state) != expected_hash:
        raise DocumentError("Your profile changed since this preview. Upload or paste the document again.")
    text = text_value(text, kind)
    plan = approved_plan(state)
    if choice == "revise":
        if (
            not plan
            or plan.id != expected_plan
            or state.journey.proposed_id
            or state.journey.stage != "active"
        ):
            raise DocumentError(
                "Your plan changed or has an unfinished revision. Save with Keep current plan, then use /plan."
            )
    setattr(state.profile, "resume_text" if kind == "resume" else "jd_text", text)
    if state.profile.readiness_basis == "resume-jd":
        # A changed source document invalidates document alignment, not tested diagnostic evidence.
        state.profile.readiness, state.profile.readiness_basis = None, "unavailable"
    state.resume_feedback = None
    if state.journey:
        setattr(state.journey, "resume_text" if kind == "resume" else "jd_text", text)
    state.document_draft = None
    if state.focus == "document":
        state.focus = None
    service.say(
        "Document saved privately. No lessons, tasks, answers or grades were reset. "
        "Use /resume for feedback on the saved resume."
    )
    if choice == "revise":
        state.journey.stage = "planning"
        state.journey.revision_request = (
            "Revise only future sessions using the updated private documents. Preserve prepared work."
        )
        service.control = {"type": "journey", "journey_id": state.journey.id, "action": "propose"}
        service.say(
            "A revised proposal is queued. Your current plan keeps running until you approve a replacement."
        )


class Documents:
    def __init__(self, service):
        self.s = service

    def begin(self, kind):
        from skillcoach.models import DocumentDraft
        from skillcoach.service import stable_id

        try:
            require_profile(self.s.state)
        except DocumentError as exc:
            self.s.say(str(exc))
            return
        self.s.state.document_draft = DocumentDraft(
            id=stable_id(self.s.job["id"]),
            kind=kind,
            base_profile_hash=profile_hash(self.s.state),
            expires_at=self.s.now + timedelta(minutes=30),
        )
        self.s.state.focus = "document"
        self.s.say(
            "Paste the new resume text (80-16000 characters)."
            if kind == "resume"
            else "Paste the new job description (50-16000 characters).",
            target=self.s.state.target(),
        )
        self.s.say(
            "To upload a text-based PDF/UTF-8 TXT instead, /cancel this paste step first, then open /dashboard. Documents stay private; "
            "nothing changes until you confirm. /cancel keeps your profile and learning."
        )

    def input(self, text):
        draft = self.s.state.document_draft
        try:
            draft.text = text_value(text, draft.kind)
        except DocumentError as exc:
            self.s.say(str(exc), target=self.s.state.target())
            return
        from skillcoach.journey import approved_plan

        plan = approved_plan(self.s.state)
        choices = [[{"text": "Save; keep current plan", "callback_data": f"doc:{draft.id}:keep"}]]
        if plan:
            choices.append(
                [{"text": "Save; propose future changes", "callback_data": f"doc:{draft.id}:revise"}]
            )
        choices.append([{"text": "Cancel update", "callback_data": f"doc:{draft.id}:cancel"}])
        self.s.say(
            f"Ready to save {len(draft.text)} characters. Your previous document is unchanged. "
            "Keep the plan, or request a proposal for future sessions; history is never reset.",
            buttons=choices,
        )
        # A fresh target invalidates text sent in reply to the original paste request.
        self.s.state.focus = None
        self.s.state.legacy_archive["document_preview_plan"] = plan.id if plan else None

    def confirm(self, ident, action):
        draft = self.s.state.document_draft
        if not draft or draft.id != ident or draft.expires_at <= self.s.now:
            self.s.say("This document preview expired or was replaced. Use /updateresume or /updatejd.")
            return
        if action == "cancel":
            self.s.state.document_draft = None
            self.s.say("Document update cancelled. Your existing document and plan are unchanged.")
            return
        if self.s.state.focus:
            self.s.say("Finish or /cancel your current question before confirming the document.")
            return
        try:
            apply_document(
                self.s,
                kind=draft.kind,
                text=draft.text,
                expected_hash=draft.base_profile_hash,
                choice=action,
                expected_plan=self.s.state.legacy_archive.get("document_preview_plan"),
            )
        except DocumentError as exc:
            self.s.say(str(exc))

    def job(self):
        payload = self.s.payload
        require_profile(self.s.state)
        apply_document(
            self.s,
            kind=payload["kind"],
            text=payload["text"],
            expected_hash=payload["profile_hash"],
            choice=payload["choice"],
            expected_plan=payload["plan_id"],
        )
