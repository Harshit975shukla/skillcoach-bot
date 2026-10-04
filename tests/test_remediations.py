import io
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb
from test_dashboard import signed
from test_flows import PROFILE, READINESS, RESUME, command
from test_journey import callback, core_guide, proposal, shared_journey

from skillcoach.documents import MAX_FILE, MAX_FILE_LABEL, DocumentError
from skillcoach.models import Profile, Readiness, Task
from skillcoach.timeutil import IST
from skillcoach.web import create_app


def active(h):
    h.repo.state.journey = shared_journey(h.clock.now)
    h.repo.state.profile = Profile(**PROFILE, readiness=Readiness(**READINESS), readiness_basis="diagnostic")


def test_revision_does_not_replace_reassessment_or_newer_documents(harness):
    h = harness
    active(h)
    h.repo.state.profile.readiness = Readiness(**{**READINESS, "readiness_score": 92})
    h.repo.state.profile.resume_text = "LATEST-RESUME"
    h.repo.state.profile.jd_text = "LATEST-JD"
    h.repo.state.profile.skills = ["Newer verified skill"]
    expected = h.repo.state.profile.model_copy(deep=True)
    callback(h, "plan:plan-test:edit")
    h.ai.responses.append(proposal())
    command(h, "Change future sessions.")
    callback(h, f"plan:{h.repo.state.journey.proposed_id}:approve")
    assert h.repo.state.profile == expected
    prompt = h.ai.calls[-1][0]
    assert "LATEST-RESUME" in prompt and '"readiness_score": 92' in prompt


@pytest.mark.parametrize("minutes,count", [(15, 1), (30, 2), (45, 3), (60, 4)])
def test_approved_pacing_sets_real_core_work_and_keeps_full_reference(harness, minutes, count):
    h = harness
    h.clock.now = datetime(2026, 9, 28, 8, tzinfo=IST)
    active(h)
    plan = h.repo.state.journey.plans["plan-test"]
    plan.minutes = minutes
    plan.sessions[0].objective = "APPROVED-OBJECTIVE"
    plan.sessions[0].practice = "APPROVED-PRACTICE"
    h.repo.enqueue(
        "day1",
        {
            "type": "journey",
            "journey_id": h.repo.state.journey.id,
            "action": "lesson",
            "plan_id": plan.id,
            "date": h.clock.now.date().isoformat(),
        },
    )
    h.runtime.recover(media=False)
    tasks = list(h.repo.state.tasks.values())
    assert len(tasks) == count
    reading = {15: 5, 30: 10, 45: 15, 60: 20}[minutes]
    assert sum(t.estimated_minutes for t in tasks) + reading == minutes
    assert all("APPROVED-OBJECTIVE" in t.detail and "APPROVED-PRACTICE" in t.detail for t in tasks)
    assert all(t.actual_minutes == 0 for t in tasks)
    bodies = [o["body"] for o in h.repo.outbox.values()]
    assert len([b for b in bodies if b["kind"] == "media"]) == 1
    assert sum(b["kind"] == "text" and "APPROVED-OBJECTIVE" in b["text"] for b in bodies) >= 1
    assert not h.ai.calls


def test_invalid_dynamic_pacing_is_rejected(harness):
    from types import SimpleNamespace

    from lesson_content import LESSONS
    from skillcoach.clients import Budget
    from skillcoach.models import Lesson
    from skillcoach.pacing import build_session

    h = harness
    h.clock.now = datetime(2026, 9, 28, 8, tzinfo=IST)
    active(h)
    invalid = core_guide()
    invalid["tasks"][0]["minutes"] = 90
    h.ai.responses.append(invalid)
    service = SimpleNamespace(
        structured=lambda key, prompt, model, validate: h.ai.structured(prompt, model, Budget(), validate)
    )
    plan = h.repo.state.journey.plans["plan-test"]
    with pytest.raises(ValueError, match="Core exercise count and estimated minutes"):
        build_session(service, Lesson.model_validate(LESSONS["ec2"]), plan.sessions[0], plan, "EC2")
    assert not h.repo.state.tasks and not h.repo.state.lessons


def test_document_commands_preview_cancel_keep_and_revise_without_reset(harness):
    h = harness
    active(h)
    plan = h.repo.state.journey.plans["plan-test"].model_copy(deep=True)
    rating = h.repo.state.profile.readiness.model_copy(deep=True)
    command(h, "/updateresume")
    command(h, RESUME)
    draft = h.repo.state.document_draft
    assert h.repo.state.profile.resume_text == ""
    callback(h, f"doc:{draft.id}:keep")
    assert h.repo.state.profile.resume_text == RESUME.strip()
    assert h.repo.state.journey.plans["plan-test"] == plan
    assert h.repo.state.profile.readiness == rating
    callback(h, f"doc:{draft.id}:keep")
    assert h.repo.state.profile.readiness == rating
    command(h, "/updatejd")
    command(h, "A new job description for cloud infrastructure practice. " * 3)
    draft = h.repo.state.document_draft
    callback(h, f"doc:{draft.id}:cancel")
    assert not h.repo.state.profile.jd_text
    command(h, "/updateresume")
    command(h, RESUME + "new")
    draft = h.repo.state.document_draft
    h.ai.responses.append(proposal())
    callback(h, f"doc:{draft.id}:revise")
    assert h.repo.state.journey.active_id == plan.id
    assert h.repo.state.journey.proposed_id
    assert h.repo.state.profile.readiness == rating


def test_stale_document_confirmation_preserves_newer_profile(harness):
    h = harness
    active(h)
    command(h, "/updateresume")
    command(h, RESUME)
    ident = h.repo.state.document_draft.id
    h.repo.state.profile.resume_text = "newer document"
    callback(h, f"doc:{ident}:keep")
    assert h.repo.state.profile.resume_text == "newer document"
    assert "changed" in h.telegram.messages[-1][0]


def test_scheduled_assessment_cannot_replace_document_input_focus(harness):
    h = harness
    active(h)
    plan = h.repo.state.journey.plans["plan-test"]
    plan.sessions[0].lesson_key = "delivered"
    h.repo.state.lessons["delivered"] = {
        "topic": "Cloud",
        "date": h.clock.now.date().isoformat(),
        "delivered_at": h.clock.now.isoformat(),
    }
    command(h, "/updateresume")
    draft = h.repo.state.document_draft.model_copy(deep=True)
    h.repo.enqueue("weekly", {"type": "schedule", "kind": "weekly", "date": h.clock.now.date().isoformat()})
    h.runtime.recover(media=False)
    assert h.repo.jobs["weekly"]["status"] == "failed"
    assert h.repo.state.focus == "document" and h.repo.state.document_draft == draft
    assert not h.ai.calls and not h.repo.state.assessments


@pytest.mark.postgres
def test_expired_lesson_recovery_reopens_only_unsent_parts_with_same_tasks(pg_repo, config):
    from test_multiuser import Bot

    bot = Bot(pg_repo, config)
    a, b = bot.join(101), bot.join(102)
    now = datetime(2026, 10, 3, 8, tzinfo=IST)
    bot.runtime.clock = lambda: now
    old = now.date() - timedelta(days=1)
    journey = shared_journey(now)
    for i, d in enumerate(journey.plans["plan-test"].sessions):
        d.lesson_key, d.date = f"lesson:{i}", old

    def seed(state):
        state.journey = journey
        state.profile = Profile(**PROFILE)
        state.tasks["prepared"] = Task(
            id="prepared",
            origin="lesson:4:0",
            title="Prepared task",
            detail="Original required work",
            skill="Cloud",
            assigned_date=old,
            estimated_minutes=15,
        )
        state.tasks["completed"] = Task(
            id="completed",
            origin="lesson:3:0",
            title="Completed task",
            detail="Already completed work",
            skill="Cloud",
            assigned_date=old,
            status="done",
            completed_at=now - timedelta(hours=1),
            actual_minutes=12,
        )
        for i in range(5):
            state.lessons[f"lesson:{i}"] = {
                "date": old.isoformat(),
                "topic": "Cloud",
                "delivered_at": now.isoformat() if i < 4 else None,
            }

    bot.save(a, seed)
    key = f"learner:{a.learner_id}:lesson"
    a.enqueue("lesson", {"type": "schedule", "kind": "lesson", "date": old.isoformat()})
    token = pg_repo.acquire("domain", 60)
    try:
        revision, state = a.read()
        body = {
            "kind": "text",
            "text": "Synthetic content",
            "scheduled": True,
            "scheduled_date": old.isoformat(),
            "journey_plan_id": "plan-test",
            "journey_lesson_key": "lesson:4",
        }
        a.finish(key, token, revision, state, [body, {**body, "lesson_key": "lesson:4"}], [])
    finally:
        pg_repo.release("domain", token)
    with pg_repo.connection() as conn:
        conn.execute(
            "INSERT INTO answer_keys(learner_id,session_id,question_id,job_id) VALUES (%s,'prior','q1',%s)",
            (a.learner_id, key),
        )
        conn.execute(
            "UPDATE outbox SET status='sent',delivered_at=now(),attempts=1 WHERE id=%s", (key + ":0",)
        )
    bot.runtime.recover(media=False)  # The final old-date item is suppressed.
    before_b = b.read()
    protected = a.read()[1].model_copy(deep=True)
    with a.connection() as conn:
        answers_before = conn.execute(
            "SELECT * FROM answer_keys WHERE learner_id=%s", (a.learner_id,)
        ).fetchall()
        tasks_before = conn.execute(
            "SELECT * FROM task_keys WHERE learner_id=%s ORDER BY id", (a.learner_id,)
        ).fetchall()
    bot.input(101, "/pause")
    bot.input(101, "/recoverlesson")
    with pg_repo.connection() as conn:
        assert (
            conn.execute("SELECT status FROM outbox WHERE id=%s", (key + ":1",)).fetchone()["status"]
            == "suppressed"
        )
    bot.input(101, "/unpause")
    bot.input(101, "/recoverlesson", drain=False)
    bot.input(101, "/recoverlesson", drain=False)
    bot.runtime.recover(media=False)
    with pg_repo.connection() as conn:
        first = conn.execute("SELECT status,attempts FROM outbox WHERE id=%s", (key + ":0",)).fetchone()
        last = conn.execute("SELECT status,attempts FROM outbox WHERE id=%s", (key + ":1",)).fetchone()
        assert first == last == {"status": "sent", "attempts": 1}
    assert a.read()[1].lessons["lesson:4"]["delivered_at"]
    assert a.read()[1].tasks == protected.tasks
    assert a.read()[1].profile == protected.profile
    with a.connection() as conn:
        assert (
            conn.execute("SELECT * FROM answer_keys WHERE learner_id=%s", (a.learner_id,)).fetchall()
            == answers_before
        )
        assert (
            conn.execute(
                "SELECT * FROM task_keys WHERE learner_id=%s ORDER BY id", (a.learner_id,)
            ).fetchall()
            == tasks_before
        )
    assert b.read() == before_b
    bot.input(101, callback="plan:plan-test:edit")
    bot.runtime.ai.responses.append(proposal())
    bot.input(101, "Next week please")
    new = a.read()[1].journey.proposed_id
    # Seed a profile/diagnostic if needed for first synthetic plan; new approval must no longer block.
    bot.input(101, callback=f"plan:{new}:approve")
    assert a.read()[1].journey.active_id == new


def pdf_bytes(
    text="Synthetic resume describes Python and cloud engineering practice. " * 2, *, encrypted=False
):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=500, height=500)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 20 450 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("test-only")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def padded_pdf(size):
    """A text resume PDF carrying an incompressible photo-sized image, about `size` bytes long."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes())))
    width = 1000
    height = max(1, (size - 4000) // (width * 3))
    image = DecodedStreamObject()
    image.set_data(os.urandom(width * height * 3))
    image.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(width),
            NameObject("/Height"): NumberObject(height),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    writer.pages[0]["/Resources"][NameObject("/XObject")] = DictionaryObject(
        {NameObject("/Im0"): writer._add_object(image)}
    )
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_upload_limit_is_4_mb_everywhere_and_under_the_platform_cap():
    """Uploads pass through one Vercel Function request (body capped at 4.5 MB): the file limit, the
    request limit and the dashboard's own check and wording all agree on 4 MB."""
    from skillcoach.document_extract import extract_pdf

    assert MAX_FILE == 4 * 1024 * 1024 and MAX_FILE_LABEL == "4 MB"
    assert MAX_FILE + 64 * 1024 < 4_500_000
    static = Path(__file__).resolve().parents[1] / "skillcoach" / "static"
    script = (static / "dashboard.js").read_text(encoding="utf-8")
    assert "file.size > 4 * 1024 * 1024" in script and "PDF or TXT file up to 4 MB." in script
    assert "Maximum 4 MB, 15 PDF pages" in (static / "dashboard.html").read_text(encoding="utf-8")
    # A photo-heavy resume close to the limit still parses quickly, far inside the 8-second guard.
    raw = padded_pdf(MAX_FILE - 50_000)
    assert 256 * 1024 < len(raw) <= MAX_FILE
    started = time.perf_counter()
    assert "Synthetic resume" in extract_pdf(raw)["text"]
    assert time.perf_counter() - started < 2
    assert extract_pdf(b"%PDF-" + b"0" * MAX_FILE)["error"] == "invalid_pdf"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows child startup exceeds the production 8s guard; real subprocess tested on Linux CI",
)
def test_pdf_text_extraction_is_local_bounded_and_rejects_invalid_files():
    from skillcoach.document_upload import extract

    assert "Synthetic resume" in extract(pdf_bytes(), "resume.pdf", "resume")
    assert "Synthetic resume" in extract(padded_pdf(MAX_FILE - 50_000), "resume.pdf", "resume")
    assert extract(RESUME.encode(), "resume.txt", "resume") == RESUME.strip()
    for raw, name in [
        (pdf_bytes(encrypted=True), "resume.pdf"),
        (b"%PDF-broken", "resume.pdf"),
        (b"not PDF", "fake.pdf"),
        (b"\xff" * 100, "resume.txt"),
        (b"x" * (MAX_FILE + 1), "resume.txt"),
        (b"PKzip", "resume.docx"),
        (pdf_bytes(text=""), "scan.pdf"),
    ]:
        with pytest.raises(DocumentError):
            extract(raw, name, "resume")


def test_pdf_parser_core_and_timeout_are_explicit(monkeypatch):
    import subprocess

    from skillcoach.document_extract import extract_pdf
    from skillcoach.document_upload import extract

    assert "Synthetic resume" in extract_pdf(pdf_bytes())["text"]
    assert extract_pdf(pdf_bytes(encrypted=True))["error"] == "encrypted_pdf"
    assert extract_pdf(pdf_bytes(text=""))["error"] == "pdf_has_no_text"
    assert extract(RESUME.encode(), "test.txt", "resume") == RESUME.strip()

    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 8
        raise subprocess.TimeoutExpired("parser", 8)

    monkeypatch.setattr("skillcoach.document_upload.subprocess.run", timeout)
    with pytest.raises(DocumentError, match="exceeded"):
        extract(pdf_bytes(), "test.pdf", "resume")


@pytest.fixture
def upload_api(pg_repo, config):
    from test_multiuser import Bot

    bot = Bot(pg_repo, config)
    scoped = bot.join(101)
    bot.save(
        scoped,
        lambda state: (
            setattr(state, "profile", Profile(**PROFILE)),
            setattr(state, "journey", shared_journey(datetime.now(IST))),
        ),
    )
    bot.runtime.clock = lambda: datetime.now(timezone.utc) + timedelta(seconds=2)
    client = create_app(bot.runtime).test_client()
    raw = signed(101, config.telegram_token, int(bot.runtime.clock().timestamp()))
    origin = "https://localhost"
    response = client.post("/app/data", base_url=origin, json={"init_data": raw})
    assert response.status_code == 200
    headers = {"Origin": origin, "X-Telegram-Init-Data": raw, "X-CSRF-Token": response.json["document_csrf"]}
    return bot, scoped, client, headers


def upload(client, headers, raw=None, ident=None, name="resume.txt"):
    return client.post(
        "/app/documents/preview",
        base_url="https://localhost",
        headers=headers,
        data={
            "request_id": ident or str(uuid4()),
            "kind": "resume",
            "file": (io.BytesIO(raw or RESUME.encode()), name),
        },
    )


def confirm_upload(client, headers, preview, choice="keep"):
    return client.post(
        "/app/documents/confirm",
        base_url="https://localhost",
        headers=headers,
        json={"request_id": preview["request_id"], "confirmation": preview["confirmation"], "choice": choice},
    )


@pytest.mark.postgres
def test_upload_confirmation_replay_private_storage_and_other_learner_isolation(upload_api):
    bot, scoped, client, headers = upload_api
    before_owner = bot.repo.read()
    before = scoped.read()[1]
    ident = str(uuid4())
    first = upload(client, headers, ident=ident)
    assert first.status_code == 200
    assert first.json["characters"] == len(RESUME.strip())
    assert "resume.txt" not in first.text and RESUME not in first.text
    assert scoped.read()[1] == before
    assert upload(client, headers, ident=ident).json == first.json
    assert upload(client, headers, raw=(RESUME + "different").encode(), ident=ident).status_code == 409
    assert confirm_upload(client, headers, first.json).json["queued"]
    assert scoped.read()[1].profile.resume_text == RESUME.strip()  # No cron required when fair turn is ready.
    assert confirm_upload(client, headers, first.json).json["duplicate"]
    bot.runtime.recover(media=False)
    result = scoped.read()[1]
    assert result.profile.resume_text == RESUME.strip()
    assert result.journey.plans == before.journey.plans
    assert bot.repo.read() == before_owner
    with bot.repo.connection() as conn:
        rows = conn.execute(
            "SELECT payload FROM jobs WHERE learner_id=%s AND payload->>'type'='document'",
            (scoped.learner_id,),
        ).fetchall()
        assert len(rows) == 1 and rows[0]["payload"]["choice"] == "keep"
        assert (
            conn.execute(
                "SELECT text FROM learner_document_requests WHERE learner_id=%s AND id=%s",
                (scoped.learner_id, ident),
            ).fetchone()["text"]
            == ""
        )


@pytest.mark.postgres
def test_upload_auth_origin_csrf_revoke_and_stale_profile(upload_api, monkeypatch):
    bot, scoped, client, headers = upload_api
    from skillcoach import document_upload

    real = document_upload.extract
    parsed = []
    monkeypatch.setattr(document_upload, "extract", lambda *args: (parsed.append(True), real(*args))[1])
    for bad in (
        {},
        {**headers, "Origin": "https://attacker.invalid"},
        {**headers, "X-CSRF-Token": "bad"},
        {**headers, "X-Telegram-Init-Data": "forged"},
    ):
        assert upload(client, bad).status_code == 403
    assert not parsed
    value = upload(client, headers).json
    bot.save(scoped, lambda state: setattr(state.profile, "resume_text", "newer"))
    assert confirm_upload(client, headers, value).status_code == 409
    value = upload(client, headers).json
    bot.input(bot.config.owner_id, "/revoke " + scoped.learner_id)
    assert confirm_upload(client, headers, value).status_code == 403
    assert scoped.read()[1].profile.resume_text == "newer"


@pytest.mark.postgres
def test_upload_cancel_expiry_conflict_during_parsing_and_limits(upload_api, monkeypatch):
    from skillcoach import document_upload

    bot, scoped, client, headers = upload_api
    value = upload(client, headers).json
    assert confirm_upload(client, headers, value, "cancel").json["cancelled"]
    assert confirm_upload(client, headers, value).status_code == 409
    value = upload(client, headers).json
    with bot.repo.connection() as conn:
        conn.execute(
            "UPDATE learner_document_requests SET expires_at=now()-interval '1 second' WHERE id=%s",
            (value["request_id"],),
        )
    assert confirm_upload(client, headers, value).status_code == 409
    original = document_upload.extract

    def parse(*args):
        assert bot.repo._session_connection.get().info.transaction_status.name == "IDLE"
        bot.save(scoped, lambda state: setattr(state.profile, "target_role", "newer target"))
        return original(*args)

    monkeypatch.setattr(document_upload, "extract", parse)
    assert upload(client, headers).status_code == 409
    assert scoped.read()[1].profile.target_role == "newer target"
    assert not scoped.read()[1].profile.resume_text
    assert client.get("/app/documents/confirm", base_url="https://localhost").status_code == 405
    # One byte over the file limit: refused with the limit named. Past the request limit: 413.
    too_big = upload(client, headers, raw=b"x" * (MAX_FILE + 1))
    assert too_big.status_code == 409 and MAX_FILE_LABEL in too_big.json["error"]
    oversized = upload(client, headers, raw=b"x" * (MAX_FILE + 65 * 1024))
    assert oversized.status_code == 413 and MAX_FILE_LABEL in oversized.json["error"]


@pytest.mark.postgres
def test_document_confirm_concurrency_creates_one_job(upload_api):
    from concurrent.futures import ThreadPoolExecutor

    from skillcoach.document_upload import confirm

    bot, scoped, client, headers = upload_api
    value = upload(client, headers).json
    with bot.repo.connection() as conn:
        row = conn.execute(
            "SELECT access_generation,auth_hash FROM learner_document_requests WHERE id=%s",
            (value["request_id"],),
        ).fetchone()
    identity = (scoped.learner_id, row["access_generation"], row["auth_hash"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: confirm(bot.runtime, identity, value["request_id"], value["confirmation"], "keep"),
                range(2),
            )
        )
    assert sum(r["duplicate"] for r in results) == 1
    with bot.repo.connection() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM jobs WHERE payload->>'type'='document'").fetchone()["n"]
            == 1
        )


@pytest.mark.postgres
def test_authenticated_pdf_multipart_preview_cancel_and_invalid_files(upload_api):
    from pypdf import PdfWriter

    bot, scoped, client, headers = upload_api
    before = scoped.read()
    value = upload(client, headers, raw=pdf_bytes(), name="resume.pdf")
    assert value.status_code == 200
    assert confirm_upload(client, headers, value.json, "cancel").json["cancelled"]
    # A photo-sized resume PDF, far past the old 256 KB limit, previews like any other.
    large = upload(client, headers, raw=padded_pdf(1_000_000), name="resume.pdf")
    assert large.status_code == 200, large.json
    assert confirm_upload(client, headers, large.json, "cancel").json["cancelled"]
    writer = PdfWriter()
    for _ in range(16):
        writer.add_blank_page(500, 500)
    oversized = io.BytesIO()
    writer.write(oversized)
    for data in (b"%PDF-broken", pdf_bytes(encrypted=True), pdf_bytes(text=""), oversized.getvalue()):
        result = upload(client, headers, raw=data, name="resume.pdf")
        assert result.status_code == 409 and "error" in result.json
    assert scoped.read() == before


@pytest.mark.postgres
@pytest.mark.parametrize("delayed_success", [False, True])
def test_migration_backfills_only_proven_completed_diagnostics_once(pg_repo, delayed_success):
    from skillcoach.bootstrap import expected_activity_repair

    now = datetime(2026, 9, 27, 12, tzinfo=IST)
    journey = shared_journey(now)
    with pg_repo.connection() as conn:
        conn.execute("DROP TABLE learner_document_requests")
        conn.execute("DELETE FROM schema_migrations WHERE version IN (7,8)")
        conn.execute(
            "UPDATE coach_state SET body=%s WHERE learner_id='owner'",
            (Jsonb({"journey": journey.model_dump(mode="json"), "activity": []}),),
        )
        conn.execute(
            "INSERT INTO jobs(id,payload,status,created_at) VALUES ('completed','{}','done',%s)", (now,)
        )
        conn.execute("INSERT INTO ai_results VALUES ('completed','journey-rating',%s)", (Jsonb(READINESS),))
        for i in range(5):
            conn.execute(
                "INSERT INTO answer_keys(learner_id,session_id,question_id,job_id) VALUES ('owner',%s,%s,'completed')",
                (journey.id, f"diagnostic-{i}"),
            )
        conn.execute(
            "INSERT INTO outbox(id,job_id,body,status,delivered_at) VALUES "
            "('failed-notice','completed',%s,'sent',%s),('confirmed','completed',%s,'sent',%s)",
            (
                Jsonb({"kind": "text", "text": "Operation unavailable", "recovery_notice": True}),
                now,
                Jsonb({"kind": "text", "text": "Your five diagnostic answers are saved. Preparing a plan."}),
                now + timedelta(days=1) if delayed_success else now,
            ),
        )
        before = conn.execute("SELECT body,revision,displayed_target FROM coach_state WHERE id=1").fetchone()
        expected = expected_activity_repair(conn, before)
    pg_repo.migrate()
    with pg_repo.connection() as conn:
        after = conn.execute("SELECT body,revision,displayed_target FROM coach_state WHERE id=1").fetchone()
    assert expected == after
    assert after["body"]["activity"] == ([] if delayed_success else ["2026-09-27"])
    assert after["body"]["journey"].get("diagnostic_practice_date") == (
        None if delayed_success else "2026-09-27"
    )
    pg_repo.migrate()
    with pg_repo.connection() as conn:
        assert (
            conn.execute("SELECT body,revision,displayed_target FROM coach_state WHERE id=1").fetchone()
            == after
        )
