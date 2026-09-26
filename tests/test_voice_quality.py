from dataclasses import replace

import pytest

from skillcoach.clients import Budget
from skillcoach.models import State
from skillcoach.storyboard import asset_key, reviewed_architecture


def test_new_learners_default_to_silent_captioned_video():
    state = State()
    assert state.media == "video"
    assert state.voice is False


def test_unapproved_voice_cannot_be_enabled_by_command(harness):
    from test_flows import command

    command(harness, "/voice on")
    assert harness.repo.state.voice is False
    assert "unavailable" in harness.telegram.messages[-1][0]
    assert "no robotic fallback" in harness.telegram.messages[-1][0]


def media_item(harness):
    story = reviewed_architecture("EC2")
    harness.repo.enqueue("voice-quality", {"type": "telegram", "text": "/help"})
    harness.repo.jobs["voice-quality"]["status"] = "done"
    body = {
        "kind": "media",
        "mode": "video",
        "voice": True,
        "shared_reviewed": True,
        "storyboard": story.model_dump(),
        "caption": "EC2",
    }
    item = {"id": "voice-quality:0", "job_id": "voice-quality", "status": "pending", "body": body}
    harness.repo.outbox[item["id"]] = item
    return story, item


def test_voice_off_selects_silent_cache_even_when_queued_payload_requested_audio(harness, monkeypatch):
    h = harness
    h.runtime.config = replace(h.runtime.config, narration_enabled=True)
    story, item = media_item(h)
    narrated_key = asset_key(story, "owner", voice=True, shared_reviewed=True) + ":video"
    silent_key = asset_key(story, "owner", voice=False, shared_reviewed=True) + ":video"
    lookups, uploads = [], []

    def cached(key):
        lookups.append(key)
        return {
            "file_id": "OLD-NARRATED" if key == narrated_key else "SILENT",
            "kind": "video",
            "metadata": {"voice": key == narrated_key},
        }

    def deliver(telegram, body, budget, *, before_send, cached=None):
        before_send()
        uploads.append((body["voice"], cached["file_id"]))
        return cached

    monkeypatch.setattr(h.repo, "media_asset", cached, raising=False)
    monkeypatch.setattr("skillcoach.runtime.deliver_storyboard", deliver)
    assert h.runtime.deliver_one(Budget(20), media=True)
    assert lookups == [silent_key] and uploads == [(False, "SILENT")]
    assert item["status"] == "sent" and item["body"]["voice"] is True


def test_quality_gate_blocks_legacy_audio_without_overwriting_stored_preference(harness, monkeypatch):
    h = harness
    h.repo.state.voice = True
    _, item = media_item(h)
    seen = []
    monkeypatch.setattr(
        h.repo,
        "media_asset",
        lambda key: {"file_id": "SILENT", "kind": "video", "metadata": {"voice": False}},
        raising=False,
    )

    def deliver(telegram, body, budget, *, before_send, cached=None):
        before_send()
        seen.append(body["voice"])
        return cached

    monkeypatch.setattr("skillcoach.runtime.deliver_storyboard", deliver)
    assert h.runtime.deliver_one(Budget(20), media=True)
    assert seen == [False]
    assert h.repo.state.voice is True  # The explicit stored preference is not overwritten.
    assert item["status"] == "sent"


def test_voice_off_during_render_prevents_audio_upload_then_rerenders_silently(harness, monkeypatch):
    h = harness
    h.repo.state.voice = True
    h.runtime.config = replace(h.runtime.config, narration_enabled=True)
    _, item = media_item(h)
    uploads, saved = [], []
    monkeypatch.setattr(h.repo, "media_asset", lambda key: None, raising=False)
    monkeypatch.setattr(h.repo, "save_media_asset", lambda *args, **kwargs: saved.append(True), raising=False)

    def deliver(telegram, body, budget, *, before_send, cached=None):
        if body["voice"]:
            h.repo.state.voice = False  # The owner changes preference while rendering takes place.
        before_send()
        uploads.append(body["voice"])
        return {"file_id": "SILENT", "kind": "video", "metadata": {"voice": False}}

    monkeypatch.setattr("skillcoach.runtime.deliver_storyboard", deliver)
    assert not h.runtime.deliver_one(Budget(20), media=True)
    assert item["status"] == "pending" and uploads == [] and saved == []
    assert h.runtime.deliver_one(Budget(20), media=True)
    assert item["status"] == "sent" and uploads == [False] and saved == [True]


def test_silent_media_caption_does_not_claim_narration(tmp_path, monkeypatch, config):
    from skillcoach.media import deliver_storyboard

    path = tmp_path / "silent.mp4"
    path.write_bytes(b"test-video")
    monkeypatch.setattr(
        "skillcoach.story_renderer.render_storyboard",
        lambda *args, **kwargs: (path, {"kind": "video", "voice": False}),
    )
    sent = []

    class Telegram:
        def call(self, method, budget, *, data, files):
            sent.append(data["caption"])
            return {"video": {"file_id": "SILENT"}}

    deliver_storyboard(
        Telegram(),
        {
            "storyboard": reviewed_architecture("EC2").model_dump(),
            "caption": "EC2",
            "voice": False,
            "mode": "video",
            "shared_reviewed": True,
        },
        Budget(),
        before_send=lambda: None,
    )
    assert "Captioned walkthrough" in sent[0] and "narration" not in sent[0]


@pytest.mark.postgres
def test_owner_voice_change_does_not_modify_another_learner_or_future_quiz(pg_repo, config):
    from datetime import datetime, timedelta, timezone

    from test_multiuser import Bot

    bot = Bot(pg_repo, config)
    guest = bot.join(101)
    bot.save(guest, lambda state: setattr(state, "voice", True))
    due = datetime.now(timezone.utc) + timedelta(hours=4)
    pg_repo.enqueue("requested-quiz", {"type": "schedule", "kind": "quiz"}, available_at=due)
    bot.input(config.owner_id, "/voice off")
    assert pg_repo.read()[1].voice is False
    assert guest.read()[1].voice is True
    with pg_repo.connection() as conn:
        row = conn.execute("SELECT status,available_at FROM jobs WHERE id='requested-quiz'").fetchone()
        assert row["status"] == "pending" and row["available_at"] == due
