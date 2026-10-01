"""Lesson videos in web mode: size caps, private chunked storage with capacity reservations, delivery that
stores and references media before a message counts as sent, the authenticated byte-range endpoint with
its byte budgets, and the rate-limited worker wake. Synthetic media bytes and a fake GitHub API only:
nothing here renders with ffmpeg, contacts GitHub or sends anything."""

import hashlib
import secrets
import threading
import time
from dataclasses import replace

import pytest
from psycopg.types.json import Jsonb
from test_web_channel import ORIGIN, build_web
from test_web_dashboard import browser, private

from skillcoach import web_media
from skillcoach.clients import Budget, ExternalError
from skillcoach.media import storyboard_caption
from skillcoach.scheduler import TriggerSettings
from skillcoach.storyboard import reviewed_architecture
from skillcoach.timeutil import IST
from skillcoach.web_channel import MEDIA_NOTE, feed_item
from skillcoach.web_media import MediaUnavailable, bounded, identity, note_for, parse_range

STORY = reviewed_architecture("EC2").model_dump()
SETTINGS = TriggerSettings("s" * 40, "Harshit975shukla/skillcoach-bot", "token-value")
DISPATCH = "https://api.github.com/repos/Harshit975shukla/skillcoach-bot/actions/workflows/recovery.yml/dispatches"


def lesson(**extra):
    return {"kind": "media", "mode": "video", "caption": "How the load balancer routes", "storyboard": STORY, **extra}


# Without a database ---------------------------------------------------------------------------


def test_single_ranges_and_everything_http_lets_a_server_ignore():
    size = 1000
    assert parse_range(None, size) is None
    assert parse_range("bytes=0-1", size) == (0, 1)  # Safari's first probe
    assert parse_range("bytes=0-", size) == (0, 999)
    assert parse_range("bytes=990-5000", size) == (990, 999)
    assert parse_range("bytes=-10", size) == (990, 999)
    assert parse_range("bytes=-5000", size) == (0, 999)
    assert parse_range("bytes = 5 - 9", size) == (5, 9)
    for ignored in ("bytes=5-2", "bytes=0-1,4-5", "items=0-1", "bytes=-", "bytes=a-b", "bytes=" + "9" * 16 + "-"):
        assert parse_range(ignored, size) is None, ignored
    assert parse_range("bytes=1000-", size) == "unsatisfiable"
    assert parse_range("bytes=-0", size) == "unsatisfiable"


def test_caps_keep_any_whole_video_inside_one_platform_response():
    assert web_media.VIDEO_BYTES == 7 * web_media.CHUNK_BYTES
    assert web_media.VIDEO_BYTES + 64 * 1024 < 4_500_000  # Vercel's response limit, with header room
    video = {"role": "video", "mime": "video/mp4", "data": b"v" * web_media.VIDEO_BYTES, "details": {}}
    poster = {"role": "poster", "mime": "image/png", "data": b"p" * 10, "details": {}}
    assert bounded([video, poster]) == [video, poster]
    oversized_poster = {**poster, "data": b"p" * (web_media.IMAGE_BYTES + 1)}
    assert bounded([video, oversized_poster]) == [video]  # a video plays without its poster
    with pytest.raises(MediaUnavailable) as caught:
        bounded([{**video, "data": b"v" * (web_media.VIDEO_BYTES + 1)}, poster])
    assert caught.value.reason == "too_large"
    with pytest.raises(MediaUnavailable):
        bounded([{"role": "image", "mime": "image/png", "data": b"i" * (web_media.IMAGE_BYTES + 1), "details": {}}])


def test_asset_identity_separates_learners_narration_mode_and_shared_sets():
    personal, owner = identity(lesson(), "u_a")
    assert owner == "u_a" and personal.endswith(":video")
    assert identity(lesson(), "u_b")[0] != personal
    assert identity(lesson(voice=True), "u_a")[0] != personal
    assert identity(lesson(mode="static"), "u_a")[0].endswith(":static")
    shared, nobody = identity(lesson(shared_reviewed=True), "u_a")
    assert nobody is None and identity(lesson(shared_reviewed=True), "u_b")[0] == shared
    diagram = {"kind": "media", "mode": "video", "caption": "Flow", "code": "graph TD; A-->B"}
    assert identity(diagram, "u_a")[0] != identity(diagram, "u_b")[0]
    for broken in ({**lesson(), "mode": "gif"}, {"kind": "media", "mode": "video", "caption": "x"},
                   {**lesson(), "storyboard": {"title": "No scenes"}}):
        with pytest.raises(MediaUnavailable):
            identity(broken, "u_a")


def test_messages_keep_their_honesty_labels_and_a_still_never_promises_motion():
    found = {
        "video": {"id": "a" * 32, "details": {"duration": 59.2, "width": 1280, "height": 720, "voice": False}},
        "poster": {"id": "b" * 32, "details": {"width": 1280, "height": 720}},
    }
    note = note_for(lesson(shared_reviewed=True), found)
    assert note["text"] == "How the load balancer routes"
    assert note["labels"] == ["Reviewed authored explanation.", "Captioned walkthrough."]
    assert (note["video"], note["poster"], note["duration"], note["voice"]) == ("a" * 32, "b" * 32, 59.2, False)
    still = note_for(lesson(mode="static"), {"image": {"id": "c" * 32, "details": {"width": 1280, "height": 720}}})
    assert still["type"] == "image" and still["labels"][-1] == "Still storyboard image, not a video."
    # Telegram keeps exactly the caption it always sent.
    assert storyboard_caption(lesson(shared_library=True)) == (
        "How the load balancer routes\nPrewritten AI-assisted explanation; not independently expert-reviewed."
        "\nCaptioned walkthrough."
    )


def test_the_feed_shows_stored_media_or_an_honest_note():
    stored = {
        "status": "ready", "type": "video", "video": "a" * 32, "poster": "b" * 32, "text": "Caption",
        "labels": ["Captioned walkthrough."], "width": 1280, "height": 720, "duration": 12.5,
    }
    row = {"delivered_seq": 4, "delivered_at": None, "body": {"kind": "media", "web_media": stored}, "media_kept": True}
    item = feed_item(row, None)
    assert item["kind"] == "media" and item["text"] == "Caption" and item["labels"] == ["Captioned walkthrough."]
    assert item["media"] == {
        "type": "video", "src": "/web/media/" + "a" * 32, "poster": "/web/media/" + "b" * 32,
        "width": 1280, "height": 720, "duration": 12.5,
    }
    removed = feed_item({**row, "media_kept": False}, None)
    assert removed["kind"] == "text" and "no longer kept" in removed["text"] and "Open lesson page" in removed["text"]
    forged = feed_item({**row, "body": {"kind": "media", "web_media": {**stored, "video": "../admin"}}}, None)
    assert forged["kind"] == "text" and "media" not in forged
    for reason, words in (("too_large", "too large"), ("storage_full", "storage is full"),
                          ("not_made", "could not be made"), ("unknown", "could not be made")):
        note = feed_item({**row, "body": {"kind": "media", "web_media": {"status": "unavailable", "reason": reason}}}, None)
        assert words in note["text"] and "Open lesson page" in note["text"] and note["kind"] == "text"
    legacy = feed_item({**row, "body": {"kind": "media"}}, None)
    assert legacy["text"] == MEDIA_NOTE and "animated" not in legacy["text"]


def test_a_wake_needs_the_scheduler_settings(harness):
    unconfigured = TriggerSettings("s" * 40, "Harshit975shukla/skillcoach-bot", "")
    session = {"learner_id": "owner", "access_generation": 1}
    assert web_media.wake(harness.runtime, session, settings=unconfigured) == "unconfigured"
    wrong = TriggerSettings("s" * 40, "not a repository", "token-value")
    assert web_media.wake(harness.runtime, session, settings=wrong) == "unconfigured"


# On a real database ---------------------------------------------------------------------------


def synthetic(body, size=700_000):
    """A random 'video' over two chunks and a small poster, like the renderer's output."""
    return [
        {
            "role": "video",
            "mime": "video/mp4",
            "data": secrets.token_bytes(size),
            "details": {"duration": 30.0, "width": 1280, "height": 720, "voice": bool(body.get("voice"))},
        },
        {"role": "poster", "mime": "image/png", "data": secrets.token_bytes(20_000), "details": {"width": 1280, "height": 720}},
    ]


@pytest.fixture
def web(pg_repo, config, monkeypatch):
    web = build_web(pg_repo, config, monkeypatch)
    with pg_repo.connection() as conn:
        conn.execute("UPDATE learners SET email='second@example.test' WHERE id=%s", (web.silent.learner_id,))
    web.renders, web.files, web.during_render = [], synthetic, None

    def render(body, folder, budget):
        web.renders.append(dict(body))
        if web.during_render:
            web.during_render()
        return web.files(body)

    monkeypatch.setattr(web_media, "render", render)
    web.owner = web.bot.repo.for_learner("owner")
    return web


def queue(web, scoped, *bodies):
    """One lesson job whose messages are delivered in order."""
    job = "lesson:" + secrets.token_hex(4)
    with web.bot.repo.connection() as conn:
        generation = conn.execute(
            "SELECT generation FROM learners WHERE id=%s", (scoped.learner_id,)
        ).fetchone()["generation"]
        conn.execute(
            "INSERT INTO jobs(id,payload,status,learner_id,access_generation) VALUES (%s,%s,'done',%s,%s)",
            (job, Jsonb({"type": "test"}), scoped.learner_id, generation),
        )
        for index, body in enumerate(bodies):
            conn.execute(
                "INSERT INTO outbox(id,job_id,body,learner_id,access_generation) VALUES (%s,%s,%s,%s,%s)",
                (f"{job}:{index}", job, Jsonb(body), scoped.learner_id, generation),
            )
    return [f"{job}:{index}" for index in range(len(bodies))]


def deliver(web, *, media=True):
    while web.bot.runtime.deliver_one(Budget(200), media=media):
        pass


def outbox(web, key):
    with web.bot.repo.connection() as conn:
        return conn.execute("SELECT * FROM outbox WHERE id=%s", (key,)).fetchone()


def refs(web, key):
    with web.bot.repo.connection() as conn:
        rows = conn.execute("SELECT role, media_id FROM web_media_refs WHERE outbox_id=%s", (key,)).fetchall()
    return {row["role"]: row["media_id"] for row in rows}


def media_rows(web):
    with web.bot.repo.connection() as conn:
        return conn.execute("SELECT * FROM web_media ORDER BY created_at, id").fetchall()


def video_of(web, key):
    return outbox(web, key)["body"]["web_media"]["video"]


def get(client, media_id, *, method="GET", **headers):
    return client.open(f"/web/media/{media_id}", method=method, base_url=ORIGIN,
                       headers={key.replace("_", "-"): value for key, value in headers.items()})


def usage(web):
    with web.bot.repo.connection() as conn:
        return {row["learner_id"]: row["bytes"] for row in conn.execute("SELECT * FROM web_media_usage")}


def retry_now(web, key, attempts=None):
    with web.bot.repo.connection() as conn:
        conn.execute(
            "UPDATE outbox SET available_at=now(), attempts=coalesce(%s, attempts) WHERE id=%s", (attempts, key)
        )
    deliver(web)


def set_voice(web, scoped, on):
    with web.bot.repo.connection() as conn:
        conn.execute(
            "UPDATE coach_state SET body=jsonb_set(body,'{voice}',to_jsonb(%s::boolean)) WHERE learner_id=%s",
            (on, scoped.learner_id),
        )


def bump_generation(web, scoped):
    with web.bot.repo.connection() as conn:
        conn.execute("UPDATE learners SET generation=generation+1 WHERE id=%s", (scoped.learner_id,))


@pytest.mark.postgres
def test_a_video_is_stored_and_referenced_before_its_message_counts_as_sent(web):
    video, text = queue(web, web.learner, lesson(), {"kind": "text", "text": "After the video"})
    # A request handler without renderers leaves the video, and the text after it waits.
    deliver(web, media=False)
    assert (outbox(web, video)["status"], outbox(web, text)["status"]) == ("pending", "pending")
    deliver(web)
    first, second = outbox(web, video), outbox(web, text)
    assert first["status"] == second["status"] == "sent" and first["delivered_seq"] < second["delivered_seq"]
    note = first["body"]["web_media"]
    assert refs(web, video) == {"video": note["video"], "poster": note["poster"]}
    stored = {row["id"]: row for row in media_rows(web)}
    assert stored[note["video"]]["state"] == "ready" and stored[note["video"]]["chunks"] == 2
    assert stored[note["video"]]["learner_id"] == web.learner.learner_id and stored[note["video"]]["lease"] is None
    client, csrf = browser(web, "learner@example.test")
    feed = private(client, csrf, "/web/feed").json
    item = next(message for message in feed["messages"] if message["kind"] == "media")
    assert item["media"]["src"] == "/web/media/" + note["video"] and feed["preparing"] is None
    whole = client.get(item["media"]["src"], base_url=ORIGIN)
    assert whole.status_code == 200 and len(whole.data) == 700_000
    assert hashlib.sha256(whole.data).hexdigest() == stored[note["video"]]["sha256"]
    assert client.get(item["media"]["poster"], base_url=ORIGIN).headers["Content-Type"] == "image/png"


@pytest.mark.postgres
def test_media_is_served_only_to_learners_whose_own_messages_show_it(web):
    shared = lesson(shared_reviewed=True)
    learner_shared, personal = queue(web, web.learner, shared, lesson(caption="Personal"))
    deliver(web)
    assert len(web.renders) == 2
    [owner_shared] = queue(web, web.owner, shared)
    deliver(web)
    assert len(web.renders) == 2  # the shared video was stored once and reused
    assert video_of(web, owner_shared) == video_of(web, learner_shared)
    learner, _ = browser(web, "learner@example.test")
    owner, _ = browser(web, "owner@example.test")
    other, _ = browser(web, "second@example.test")
    unknown = "f" * 32
    for client, allowed in (
        (learner, {video_of(web, learner_shared), video_of(web, personal)}),
        (owner, {video_of(web, learner_shared)}),
        (other, set()),
    ):
        for media_id in (video_of(web, learner_shared), video_of(web, personal), unknown):
            response = get(client, media_id)
            if media_id in allowed:
                assert response.status_code == 200
            else:
                # Someone else's video and one that never existed look exactly the same.
                assert (response.status_code, response.data) == web_media.NOT_FOUND[::2]
    anonymous = web.app.test_client()
    assert get(anonymous, video_of(web, learner_shared)).status_code == 403
    assert get(learner, video_of(web, learner_shared), Sec_Fetch_Site="cross-site").status_code == 403
    assert get(learner, video_of(web, learner_shared), Sec_Fetch_Site="same-site").status_code == 403
    assert get(learner, video_of(web, learner_shared), Sec_Fetch_Site="none").status_code == 200
    address = f"/web/media/{video_of(web, learner_shared)}?learner=owner"
    assert learner.get(address, base_url=ORIGIN).status_code == 403
    assert get(learner, "not-a-media-id").status_code == 404


@pytest.mark.postgres
def test_byte_ranges_heads_and_byte_budgets(web, monkeypatch):
    [key] = queue(web, web.learner, lesson())
    deliver(web)
    media_id, chunk = video_of(web, key), web_media.CHUNK_BYTES
    client, _ = browser(web, "learner@example.test")
    returned = 0

    def fetch(**headers):
        nonlocal returned
        response = get(client, media_id, **headers)
        if response.status_code in (200, 206):
            returned += len(response.data)
        return response

    whole = fetch()
    size = len(whole.data)
    for name, value in (
        ("Content-Type", "video/mp4"), ("Accept-Ranges", "bytes"), ("Content-Length", str(size)),
        ("Content-Disposition", "inline"), ("Cross-Origin-Resource-Policy", "same-origin"),
        ("Cache-Control", "no-store, private"), ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"),
    ):
        assert whole.headers[name] == value, name
    probe = fetch(Range="bytes=0-1")
    assert probe.status_code == 206 and probe.data == whole.data[:2]
    assert probe.headers["Content-Range"] == f"bytes 0-1/{size}" and probe.headers["Content-Length"] == "2"
    parts = [fetch(Range=f"bytes=0-{chunk - 2}"), fetch(Range=f"bytes={chunk - 1}-{chunk + 9}"), fetch(Range=f"bytes={chunk + 10}-")]
    assert all(part.status_code == 206 for part in parts) and b"".join(part.data for part in parts) == whole.data
    assert fetch(Range="bytes=-100").data == whole.data[-100:]
    past = fetch(Range=f"bytes={size}-")
    assert past.status_code == 416 and past.headers["Content-Range"] == f"bytes */{size}" and past.data == b""
    for ignored in ("bytes=5-2", "bytes=0-1,5-6"):
        assert fetch(Range=ignored).status_code == 200
    tag = whole.headers["ETag"]
    assert fetch(Range="bytes=0-1", If_Range=tag).status_code == 206
    assert fetch(Range="bytes=0-1", If_Range='"another-version"').status_code == 200
    # HEAD returns the headers only and spends nothing.
    before = usage(web)
    head = get(client, media_id, method="HEAD")
    assert head.status_code == 200 and head.headers["Content-Length"] == str(size) and head.data == b""
    ranged_head = get(client, media_id, method="HEAD", Range="bytes=0-1")
    assert ranged_head.status_code == 206 and ranged_head.headers["Content-Length"] == "2"
    assert usage(web) == before == {web.learner.learner_id: returned}
    # Budgets are reserved before reading: past them, a private 429 points to the walkthrough instead.
    monkeypatch.setattr(web_media, "DAILY_BYTES", returned + 10)
    over = fetch()
    assert over.status_code == 429 and "lesson page" in over.json["error"]
    assert over.headers["Cache-Control"] == "no-store, private" and over.headers["Content-Type"] == "application/json"
    assert fetch(Range="bytes=0-9").status_code == 206
    assert fetch(Range="bytes=0-0").status_code == 429
    monkeypatch.setattr(web_media, "DAILY_BYTES", 10**12)
    monkeypatch.setattr(web_media, "MONTHLY_BYTES", returned)
    assert fetch(Range="bytes=0-0").status_code == 429
    assert usage(web) == {web.learner.learner_id: returned}


@pytest.mark.postgres
def test_sign_out_revocation_address_change_and_readmission_end_media_access(web):
    [key] = queue(web, web.learner, lesson())
    deliver(web)
    media_id = video_of(web, key)
    client, csrf = browser(web, "learner@example.test")
    assert get(client, media_id).status_code == 200
    assert private(client, csrf, "/web/logout").status_code == 200
    assert get(client, media_id).status_code == 403
    client, _ = browser(web, "learner@example.test")
    assert get(client, media_id).status_code == 200
    with web.bot.repo.connection() as conn:
        conn.execute("UPDATE learners SET email='moved@example.test' WHERE id=%s", (web.learner.learner_id,))
    assert get(client, media_id).status_code == 403
    with web.bot.repo.connection() as conn:
        conn.execute("UPDATE learners SET email='learner@example.test' WHERE id=%s", (web.learner.learner_id,))
    client, _ = browser(web, "learner@example.test")
    assert get(client, media_id).status_code == 200
    bump_generation(web, web.learner)  # removed and admitted again
    assert get(client, media_id).status_code == 403
    client, _ = browser(web, "learner@example.test")
    assert get(client, media_id).status_code == 404  # messages from earlier access stay closed


@pytest.mark.postgres
def test_narration_turned_off_or_access_removed_while_rendering_is_respected(web):
    web.bot.runtime.config = replace(web.bot.runtime.config, narration_enabled=True)
    set_voice(web, web.learner, True)
    [key] = queue(web, web.learner, lesson(voice=True))
    web.during_render = lambda: set_voice(web, web.learner, False)
    assert not web.bot.runtime.deliver_one(Budget(200), media=True)
    row = outbox(web, key)
    assert (row["status"], row["attempts"]) == ("pending", 0) and not refs(web, key)
    web.during_render = None
    deliver(web)
    assert web.renders[-1]["voice"] is False and len(web.renders) == 2
    note = outbox(web, key)["body"]["web_media"]
    assert note["voice"] is False and note["labels"][-1] == "Captioned walkthrough."
    [later] = queue(web, web.learner, lesson(caption="Second", storyboard={**STORY, "title": "A second walkthrough"}))
    web.during_render = lambda: bump_generation(web, web.learner)
    deliver(web)
    assert len(web.renders) == 3
    assert outbox(web, later)["status"] == "suppressed" and not refs(web, later)


@pytest.mark.postgres
def test_unmade_videos_are_announced_honestly_and_never_block_the_lesson(web):
    def failing(code, retryable):
        def files(body):
            raise ExternalError(code, retryable=retryable)

        return files

    web.files = lambda body: [{"role": "video", "mime": "video/mp4", "data": b"v" * (web_media.VIDEO_BYTES + 1), "details": {}}]
    big, after = queue(web, web.learner, lesson(caption="Big"), {"kind": "text", "text": "Next step"})
    deliver(web)
    assert outbox(web, big)["body"]["web_media"] == {"status": "unavailable", "reason": "too_large"}
    assert outbox(web, big)["status"] == outbox(web, after)["status"] == "sent" and not media_rows(web)
    # A lesson error is final at once.
    web.files = failing("scene_caption_does_not_fit", False)
    [bad] = queue(web, web.learner, lesson(caption="Bad"))
    deliver(web)
    assert outbox(web, bad)["body"]["web_media"] == {"status": "unavailable", "reason": "not_made"}
    # A passing fault, or a renderer missing on one worker, is retried with no /retry notice for the learner.
    web.files = failing("storyboard_encoding_failed", True)
    [flaky] = queue(web, web.learner, lesson(caption="Flaky"))
    deliver(web)
    row = outbox(web, flaky)
    assert (row["status"], row["attempts"], row["error_code"]) == ("failed", 1, "storyboard_encoding_failed")
    assert outbox(web, flaky + ":delivery-error") is None
    web.files = failing("ffmpeg_missing", False)
    retry_now(web, flaky)
    assert (outbox(web, flaky)["status"], outbox(web, flaky)["attempts"]) == ("failed", 2)
    # The fifth attempt never leaves the lesson blocked: the message goes out with the honest note.
    retry_now(web, flaky, attempts=4)
    assert outbox(web, flaky)["status"] == "sent"
    assert outbox(web, flaky)["body"]["web_media"] == {"status": "unavailable", "reason": "not_made"}
    client, csrf = browser(web, "learner@example.test")
    texts = [message.get("text", "") for message in private(client, csrf, "/web/feed").json["messages"]]
    assert sum("Video unavailable" in text for text in texts) == 3 and "Next step" in texts


@pytest.mark.postgres
def test_capacity_counts_every_reservation_so_concurrent_writers_never_overshoot(web, monkeypatch):
    repo = web.bot.repo
    monkeypatch.setattr(web_media, "STORE_BYTES", 3 * 600_000 + 1000)
    barrier, results = threading.Barrier(6), []

    def writer(number):
        files = [{"role": "video", "mime": "video/mp4", "data": secrets.token_bytes(600_000), "details": {}}]
        barrier.wait()
        try:
            web_media.store(repo, f"{number:064x}:video", None, files)
            results.append("stored")
        except MediaUnavailable as exc:
            results.append(exc.reason)

    threads = [threading.Thread(target=writer, args=(number,)) for number in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["storage_full"] * 3 + ["stored"] * 3
    rows = media_rows(web)
    assert len(rows) == 3 and all(row["state"] == "ready" for row in rows)
    assert sum(row["bytes"] for row in rows) <= web_media.STORE_BYTES


@pytest.mark.postgres
def test_an_active_reservation_counts_and_only_an_abandoned_one_is_reclaimed(web, monkeypatch):
    repo = web.bot.repo
    monkeypatch.setattr(web_media, "STORE_BYTES", 1_000_000)
    with repo.connection() as conn:
        conn.execute(
            "INSERT INTO web_media(id,asset_key,role,mime,bytes,chunks,sha256,lease,reserved_until) "
            "VALUES (%s,%s,'video','video/mp4',600000,2,%s,'another-writer',now()+interval '5 minutes')",
            ("e" * 32, "a" * 64 + ":video", "0" * 64),
        )
    files = [{"role": "video", "mime": "video/mp4", "data": secrets.token_bytes(600_000), "details": {}}]
    with pytest.raises(MediaUnavailable):
        web_media.store(repo, "b" * 64 + ":video", None, files)
    with pytest.raises(ExternalError, match="media_busy"):
        web_media.store(repo, "a" * 64 + ":video", None, files)
    assert [row["id"] for row in media_rows(web)] == ["e" * 32]  # the active writer was left alone
    with repo.connection() as conn:
        conn.execute("UPDATE web_media SET reserved_until=now()-interval '1 second'")
    stored = web_media.store(repo, "b" * 64 + ":video", None, files)
    assert [row["id"] for row in media_rows(web)] == [stored["video"]["id"]]


@pytest.mark.postgres
def test_corrupt_or_interrupted_uploads_are_never_published(web, monkeypatch):
    repo, original = web.bot.repo, web_media._write_chunk
    files = [{"role": "video", "mime": "video/mp4", "data": secrets.token_bytes(700_000), "details": {}}]
    monkeypatch.setattr(
        web_media, "_write_chunk", lambda repo, media, lease, seq, data: original(repo, media, lease, seq, b"x" + data[1:])
    )
    with pytest.raises(ExternalError, match="media_integrity_failed"):
        web_media.store(repo, "c" * 64 + ":video", None, files)
    assert not media_rows(web)  # the writer released its own reservation

    def crash(repo, media, lease, seq, data):
        if seq:
            raise RuntimeError("worker stopped")
        original(repo, media, lease, seq, data)

    monkeypatch.setattr(web_media, "_write_chunk", crash)
    monkeypatch.setattr(web_media, "_abandon", lambda *args: None)  # as if the process died
    with pytest.raises(RuntimeError):
        web_media.store(repo, "c" * 64 + ":video", None, files)
    assert [row["state"] for row in media_rows(web)] == ["reserved"] and web_media.ready(repo, "c" * 64 + ":video") is None
    monkeypatch.setattr(web_media, "_write_chunk", original)
    with repo.connection() as conn:
        conn.execute("UPDATE web_media SET reserved_until=now()-interval '1 second'")
    stored = web_media.store(repo, "c" * 64 + ":video", None, files)
    assert [row["state"] for row in media_rows(web)] == ["ready"] and stored["video"]["id"]


@pytest.mark.postgres
def test_database_watermark_and_retention_keep_storage_bounded(web, monkeypatch):
    repo = web.bot.repo

    def files(size):
        return [{"role": "video", "mime": "video/mp4", "data": secrets.token_bytes(size), "details": {}}]

    guard = web_media.DATABASE_GUARD
    monkeypatch.setattr(web_media, "DATABASE_GUARD", 1)
    with pytest.raises(MediaUnavailable) as full:
        web_media.store(repo, "d" * 64 + ":video", None, files(1000))
    assert full.value.reason == "storage_full" and not media_rows(web)
    monkeypatch.setattr(web_media, "DATABASE_GUARD", guard)
    for letter, size in (("1", 300_000), ("2", 300_000), ("3", 300_000)):
        web_media.store(repo, letter * 64 + ":video", None, files(size))
    with repo.connection() as conn:
        # Unseen for longer than the retention period; shown ten days ago; stored just now.
        conn.execute("UPDATE web_media SET created_at=now()-interval '40 days', last_used_at=now()-interval '31 days' "
                     "WHERE asset_key=%s", ("1" * 64 + ":video",))
        conn.execute("UPDATE web_media SET created_at=now()-interval '10 days', last_used_at=now()-interval '10 days' "
                     "WHERE asset_key=%s", ("2" * 64 + ":video",))
    monkeypatch.setattr(web_media, "STORE_BYTES", 700_000)
    web_media.store(repo, "4" * 64 + ":video", None, files(300_000))
    assert sorted(row["asset_key"][0] for row in media_rows(web)) == ["3", "4"]
    # Only media stored more than a day ago may be removed for room; otherwise new media is refused.
    with pytest.raises(MediaUnavailable):
        web_media.store(repo, "5" * 64 + ":video", None, files(300_000))


class FakeGitHub:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    def call(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.error:
            raise self.error
        return 204, None


def session_for(web, scoped):
    with web.bot.repo.connection() as conn:
        generation = conn.execute("SELECT generation FROM learners WHERE id=%s", (scoped.learner_id,)).fetchone()
    return {"learner_id": scoped.learner_id, "access_generation": generation["generation"]}


def reset_wake(web, **values):
    with web.bot.repo.connection() as conn:
        conn.execute(
            "UPDATE web_media_wake SET requested_at=coalesce(%s,'-infinity'::timestamptz), "
            "count=coalesce(%s,0), day=%s",
            (values.get("requested_at"), values.get("count"), values.get("day")),
        )


@pytest.mark.postgres
def test_a_wake_is_only_for_the_learners_own_due_work_and_strictly_bounded(web):
    runtime, hub = web.bot.runtime, FakeGitHub()
    learner, other = session_for(web, web.learner), session_for(web, web.silent)
    assert web_media.wake(runtime, learner, http=hub, settings=SETTINGS) == "skipped" and not hub.calls
    queue(web, web.learner, lesson())
    assert web_media.wake(runtime, other, http=hub, settings=SETTINGS) == "skipped"  # not this learner's work
    assert web_media.wake(runtime, learner, http=hub, settings=SETTINGS) == "dispatched"
    [(method, url, kwargs)] = hub.calls
    assert (method, url, kwargs["json"], kwargs["attempts"]) == ("POST", DISPATCH, {"ref": "main"}, 1)
    assert kwargs["headers"]["Authorization"] == "Bearer token-value" and kwargs["budget"].remaining() <= 4
    assert web_media.wake(runtime, learner, http=hub, settings=SETTINGS) == "skipped" and len(hub.calls) == 1
    today = runtime.clock().astimezone(IST).date()
    reset_wake(web, count=web_media.WAKE_PER_DAY, day=today)
    assert web_media.wake(runtime, learner, http=hub, settings=SETTINGS) == "skipped"
    reset_wake(web, count=web_media.WAKE_PER_DAY, day=today.replace(year=today.year - 1))
    assert web_media.wake(runtime, learner, http=hub, settings=SETTINGS) == "dispatched"
    # Never while a worker already holds a lease.
    reset_wake(web)
    token = web.bot.repo.acquire("delivery", 60)
    assert web_media.wake(runtime, learner, http=hub, settings=SETTINGS) == "skipped"
    web.bot.repo.release("delivery", token)
    # Work from before a learner's access changed, or of a removed learner, never wakes a worker.
    stale = dict(learner)
    bump_generation(web, web.learner)
    assert web_media.wake(runtime, stale, http=hub, settings=SETTINGS) == "skipped"
    assert web_media.wake(runtime, session_for(web, web.learner), http=hub, settings=SETTINGS) == "skipped"
    queue(web, web.silent, lesson())
    with web.bot.repo.connection() as conn:
        conn.execute("UPDATE learners SET status='revoked' WHERE id=%s", (web.silent.learner_id,))
    assert web_media.wake(runtime, other, http=hub, settings=SETTINGS) == "skipped"
    assert len(hub.calls) == 2


@pytest.mark.postgres
def test_concurrent_polls_dispatch_once_and_a_failed_dispatch_changes_no_delivery(web):
    runtime, hub = web.bot.runtime, FakeGitHub()
    queue(web, web.learner, lesson())
    queue(web, web.silent, lesson())
    sessions = (session_for(web, web.learner), session_for(web, web.silent))
    barrier, results = threading.Barrier(2), []

    def poll(session):
        barrier.wait()
        results.append(web_media.wake(runtime, session, http=hub, settings=SETTINGS))

    threads = [threading.Thread(target=poll, args=(session,)) for session in sessions]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["dispatched", "skipped"] and len(hub.calls) == 1
    reset_wake(web)
    with web.bot.repo.connection() as conn:
        before = conn.execute("SELECT id, status, attempts, available_at FROM outbox ORDER BY id").fetchall()
    uncertain = FakeGitHub(ExternalError("network_unavailable"))
    assert web_media.wake(runtime, sessions[0], http=uncertain, settings=SETTINGS) == "failed"
    # The claim stays: an answer that may have started a worker is not followed by a second request.
    assert web_media.wake(runtime, sessions[0], http=hub, settings=SETTINGS) == "skipped" and len(hub.calls) == 1
    with web.bot.repo.connection() as conn:
        assert conn.execute("SELECT id, status, attempts, available_at FROM outbox ORDER BY id").fetchall() == before


@pytest.mark.postgres
def test_the_feed_reports_a_waiting_video_and_only_its_own_work_wakes_a_worker(web, monkeypatch):
    hub = FakeGitHub()
    monkeypatch.setattr(web_media, "HTTP", lambda: hub)
    monkeypatch.setenv("SCHEDULER_REPO", "Harshit975shukla/skillcoach-bot")
    monkeypatch.setenv("SCHEDULER_GITHUB_TOKEN", "token-value")
    client, csrf = browser(web, "learner@example.test")
    assert private(client, csrf, "/web/feed").json["preparing"] is None and not hub.calls
    [key] = queue(web, web.learner, lesson())
    assert private(client, csrf, "/web/feed").json["preparing"] == "queued" and len(hub.calls) == 1
    # Ordinary reads and requests without the page's CSRF token never wake anything.
    assert client.get("/web/session", base_url=ORIGIN).status_code == 200
    assert private(client, None, "/web/feed").status_code == 403 and len(hub.calls) == 1
    with web.bot.repo.connection() as conn:
        conn.execute("UPDATE outbox SET available_at=now()-interval '20 minutes' WHERE id=%s", (key,))
    assert private(client, csrf, "/web/feed").json["preparing"] == "delayed"
    # A wake that cannot even be recorded never breaks the conversation.
    reset_wake(web)
    waiting = web_media.WAITING
    monkeypatch.setattr(web_media, "WAITING", "SELECT 1 FROM no_such_table")
    response = private(client, csrf, "/web/feed")
    assert response.status_code == 200 and response.json["preparing"] == "delayed" and len(hub.calls) == 1
    monkeypatch.setattr(web_media, "WAITING", waiting)
    deliver(web)
    feed = private(client, csrf, "/web/feed").json
    assert feed["preparing"] is None and feed["messages"][-1]["kind"] == "media"


@pytest.mark.postgres
def test_waiting_videos_never_hold_back_other_learners_or_their_reminders(web):
    queue(web, web.learner, lesson(), {"kind": "text", "text": "After the video"})
    hello, reminder = queue(
        web, web.silent, {"kind": "text", "text": "Hello"},
        {"kind": "email", "subject": "Your SkillCoach lesson is ready", "text": "Open SkillCoach"},
    )
    deliver(web, media=False)
    assert outbox(web, hello)["status"] == outbox(web, reminder)["status"] == "sent"
    assert [mail["to"] for mail in web.email.sent] == ["second@example.test"]


def set_state(web, scoped, field, value):
    with web.bot.repo.connection() as conn:
        conn.execute(
            "UPDATE coach_state SET body=jsonb_set(body,%s,%s), revision=revision+1 WHERE learner_id=%s",
            ([field], Jsonb(value), scoped.learner_id),
        )


@pytest.mark.postgres
def test_a_pause_or_cancellation_while_rendering_is_never_overruled(web):
    today = web.bot.runtime.clock().astimezone(IST).date().isoformat()
    [scheduled] = queue(web, web.learner, lesson(scheduled=True, scheduled_date=today))
    web.during_render = lambda: set_state(web, web.learner, "paused", True)
    deliver(web)
    row = outbox(web, scheduled)
    assert row["status"] == "suppressed" and "web_media" not in row["body"] and not refs(web, scheduled)
    set_state(web, web.learner, "paused", False)
    # Withdrawn by other work during rendering (as /cancel does): it stays withdrawn.
    [cancelled] = queue(web, web.learner, lesson(storyboard={**STORY, "title": "Cancelled walkthrough"}))

    def cancel():
        with web.bot.repo.connection() as conn:
            conn.execute("UPDATE outbox SET status='suppressed' WHERE id=%s", (cancelled,))

    web.during_render = cancel
    deliver(web)
    row = outbox(web, cancelled)
    assert (row["status"], row["delivered_seq"]) == ("suppressed", None) and not refs(web, cancelled)


@pytest.mark.postgres
def test_publishing_waits_for_concurrent_domain_work_in_the_same_lock_order(web):
    """Domain work locks the learner, then the coaching state, then messages. Publishing a rendered
    video takes the same order, so it waits for that work and sees its result; it never deadlocks."""
    errors = []

    def domain_work(key, *, withdraw):
        locked, done = threading.Event(), threading.Event()

        def run():
            try:
                with web.bot.repo.connection() as conn:
                    conn.execute("SELECT 1 FROM learners WHERE id=%s FOR UPDATE", (web.learner.learner_id,))
                    locked.set()
                    time.sleep(0.6)
                    conn.execute(
                        "SELECT 1 FROM coach_state WHERE learner_id=%s FOR UPDATE", (web.learner.learner_id,)
                    )
                    conn.execute(
                        "UPDATE outbox SET status=CASE WHEN %s THEN 'suppressed' ELSE status END, "
                        "body=body || '{\"touched\": true}' WHERE id=%s",
                        (withdraw, key),
                    )
            except Exception as exc:  # noqa: BLE001  (reported below)
                errors.append(exc)
            finally:
                done.set()

        thread = threading.Thread(target=run)

        def start():
            thread.start()
            assert locked.wait(5)

        return start, thread

    [kept] = queue(web, web.learner, lesson(shared_reviewed=True, storyboard={**STORY, "title": "Kept walkthrough"}))
    web.during_render, thread = domain_work(kept, withdraw=False)
    deliver(web)
    thread.join()
    row = outbox(web, kept)
    assert row["status"] == "sent" and row["body"]["touched"] is True and refs(web, kept)
    [withdrawn] = queue(
        web, web.learner, lesson(shared_reviewed=True, storyboard={**STORY, "title": "Withdrawn walkthrough"})
    )
    web.during_render, thread = domain_work(withdrawn, withdraw=True)
    deliver(web)
    thread.join()
    row = outbox(web, withdrawn)
    assert row["status"] == "suppressed" and row["delivered_seq"] is None and not refs(web, withdrawn)
    assert not errors


@pytest.mark.postgres
def test_current_video_failures_are_reported_and_retried_while_telegram_history_is_kept(web):
    from test_web_channel import send, sign_in

    with web.bot.repo.connection() as conn:
        generation = conn.execute("SELECT generation FROM learners WHERE id='owner'").fetchone()["generation"]
        conn.execute(
            "INSERT INTO jobs(id,payload,status,learner_id,access_generation) VALUES "
            "('telegram:old','{}','done','owner',%s)",
            (generation,),
        )
        for key, body in (
            ("telegram:old:0", {"kind": "text", "text": "Delivery delay"}),
            ("telegram:old:1", lesson(caption="Sent to Telegram once")),
        ):
            conn.execute(
                "INSERT INTO outbox(id,job_id,body,status,attempts,error_code,learner_id,access_generation) "
                "VALUES (%s,'telegram:old',%s,'failed',5,'http_401','owner',%s)",
                (key, Jsonb(body), generation),
            )

    def failing(body):
        raise ExternalError("storyboard_encoding_failed")

    web.files = failing
    [current] = queue(web, web.owner, lesson(caption="Current video", storyboard={**STORY, "title": "Current"}))
    deliver(web)
    row = outbox(web, current)
    assert (row["status"], row["body"]["web_failure"]) == ("failed", "storyboard_encoding_failed")
    repo = web.bot.runtime.repo
    assert repo.failure_counts(web_mode=True, all_learners=True) == {"jobs": 0, "deliveries": 1, "telegram_history": 2}
    web.files = synthetic
    sign_in(web, "owner@example.test")
    assert send(web, text="/retry").json["status"] == "queued"
    web.bot.runtime.recover(media=False)
    assert (outbox(web, current)["status"], outbox(web, current)["attempts"]) == ("pending", 0)
    deliver(web)
    assert outbox(web, current)["status"] == "sent" and refs(web, current)
    for key in ("telegram:old:0", "telegram:old:1"):
        old = outbox(web, key)
        assert (old["status"], old["attempts"], old["error_code"], old["delivered_seq"]) == ("failed", 5, "http_401", None)
    assert repo.failure_counts(web_mode=True, all_learners=True) == {"jobs": 0, "deliveries": 0, "telegram_history": 2}


@pytest.mark.postgres
def test_only_lesson_work_can_wake_a_worker(web):
    runtime, hub = web.bot.runtime, FakeGitHub()
    learner = session_for(web, web.learner)

    def job(payload):
        with web.bot.repo.connection() as conn:
            conn.execute(
                "INSERT INTO jobs(id,payload,learner_id,access_generation) VALUES (%s,%s,%s,%s)",
                ("waiting:" + secrets.token_hex(4), Jsonb(payload), web.learner.learner_id, learner["access_generation"]),
            )

    for ordinary in ({"type": "telegram", "channel": "web", "text": "/help"},
                     {"type": "journey", "action": "propose"}, {"type": "telegram", "text": "/learnings"}):
        job(ordinary)
    assert web_media.wake(runtime, learner, http=hub, settings=SETTINGS) == "skipped" and not hub.calls
    job({"type": "telegram", "channel": "web", "text": "/learn kubernetes probes"})
    assert web_media.wake(runtime, learner, http=hub, settings=SETTINGS) == "dispatched" and len(hub.calls) == 1
