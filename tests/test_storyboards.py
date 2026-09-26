import hashlib
import json
import subprocess
import wave
from pathlib import Path

import pytest
from pydantic import ValidationError

from lesson_content import LESSONS
from skillcoach.catalog import MODULES, TOPICS, catalog_text, find_topic
from skillcoach.clients import Budget, ExternalError
from skillcoach.models import Lesson
from skillcoach.story_renderer import fonts, prepare_audio, render_frame, render_storyboard
from skillcoach.storyboard import Storyboard, asset_key, concept_walkthrough, reviewed_architecture


def test_catalog_is_explicit_broad_and_addressable():
    assert len(TOPICS) >= 170 and len(MODULES) >= 20
    assert {
        "linux",
        "networking",
        "aws-core",
        "azure",
        "gcp",
        "containers",
        "kubernetes",
        "iac",
        "delivery",
        "observability",
        "sre",
        "security",
        "mlops",
        "finops",
    } <= {m.id for m in MODULES}
    assert len(TOPICS) == sum(len(m.topics) for m in MODULES)
    for ident, (module, title) in TOPICS.items():
        assert find_topic(ident) == (ident, module, title)
        assert module.reference.startswith("https://")
    assert "versioned syllabus" in catalog_text()
    assert "Unknown module" in catalog_text("not-a-module")
    assert "AWS EC2" in catalog_text("aws-core")


def test_all_authored_storyboards_validate_and_render_readable_frames():
    font_set = fonts()
    count = 0
    for topic, raw in LESSONS.items():
        lesson = Lesson.model_validate(raw)
        boards = [reviewed_architecture(topic), *(concept_walkthrough(lesson, i) for i in range(4))]
        for story in boards:
            assert 3 <= len(story.scenes) <= 5
            for index in range(len(story.scenes)):
                image = render_frame(story, index, 0.5, 0.5, font_set, reviewed=True)
                assert image.size == (1280, 720)
            count += 1
    assert count == 30


def test_scene_ids_counts_urls_and_generated_code_are_rejected():
    raw = reviewed_architecture("EC2").model_dump()
    raw["scenes"][0]["active_edges"] = ["missing"]
    with pytest.raises(ValidationError):
        Storyboard.model_validate(raw)
    raw = reviewed_architecture("EC2").model_dump()
    raw["python"] = "print('not executable')"
    with pytest.raises(ValidationError):
        Storyboard.model_validate(raw)
    raw.pop("python")
    raw["references"] = ["https://attacker.invalid/prompt"]
    with pytest.raises(ValidationError):
        Storyboard.model_validate(raw)


def test_request_markers_move_without_changing_camera_or_caption():
    story = reviewed_architecture("EC2")
    font_set = fonts()
    early = render_frame(story, 0, 0.3, 0.1, font_set).crop((380, 248, 475, 282))
    later = render_frame(story, 0, 1.5, 0.1, font_set).crop((380, 248, 475, 282))
    assert hashlib.sha256(early.tobytes()).digest() != hashlib.sha256(later.tobytes()).digest()


def test_narration_scene_lengths_follow_actual_wave_duration(tmp_path, monkeypatch):
    monkeypatch.setattr("skillcoach.story_renderer.shutil.which", lambda name: "/fake/espeak-ng")
    durations = iter((3.0, 5.0, 7.0, 4.0))

    def speak(args, **kwargs):
        output = Path(args[args.index("-w") + 1])
        with wave.open(str(output), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(22050)
            wav.writeframes(b"\1\0" * round(22050 * next(durations)))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr("skillcoach.story_renderer.subprocess.run", speak)
    scene_lengths, path = prepare_audio(reviewed_architecture("EC2"), tmp_path, Budget(), voice=True)
    assert scene_lengths[0] == 4 and scene_lengths[1] > 5.7 and scene_lengths[2] > 7.7
    with wave.open(str(path), "rb") as wav:
        assert abs(wav.getnframes() / wav.getframerate() - sum(scene_lengths)) < 0.001


def test_missing_narrator_is_explicit_and_static_mode_needs_no_voice(tmp_path, monkeypatch):
    monkeypatch.setattr("skillcoach.story_renderer.shutil.which", lambda name: None)
    with pytest.raises(ExternalError, match="offline_narrator_missing"):
        prepare_audio(reviewed_architecture("EC2"), tmp_path, Budget(), voice=True)
    file, metadata = render_storyboard(
        reviewed_architecture("EC2"), tmp_path, Budget(), voice=True, static=True
    )
    assert file.is_file() and metadata == {"kind": "photo", "voice": False}


def test_asset_cache_keys_separate_private_learners_and_voice_preferences():
    story = reviewed_architecture("EC2")
    assert asset_key(story, "a", voice=True) != asset_key(story, "b", voice=True)
    assert asset_key(story, "a", voice=True) != asset_key(story, "a", voice=False)
    assert asset_key(story, "a", voice=True, shared_reviewed=True) == asset_key(
        story, "b", voice=True, shared_reviewed=True
    )


def test_voice_controls_topics_and_generated_topic_storyboards(harness):
    from test_flows import command

    command(harness, "/voice off")
    command(harness, "/topics kubernetes")
    assert not harness.repo.state.voice
    assert any("Kubernetes" in text for text, _ in harness.telegram.messages)
    topic_id = next(key for key in TOPICS if key.startswith("automation/"))
    lesson = json.loads(json.dumps(LESSONS["ec2"]))
    lesson["title"] = TOPICS[topic_id][1]
    lesson["reviewed_at"] = "AI-generated; not independently reviewed"
    harness.ai.responses.extend([lesson, *[reviewed_architecture("ec2").model_dump() for _ in range(5)]])
    command(harness, "/learn " + topic_id)
    assert len(harness.repo.state.tasks) == 3
    media = [item["body"] for item in harness.repo.outbox.values() if item["body"]["kind"] == "media"]
    assert len(media) == 5 and all(not item["voice"] and not item["shared_reviewed"] for item in media)
    assert any("storyboard:concept" in key[1] for key in harness.repo.cache_data)


@pytest.mark.postgres
def test_private_media_cache_is_scoped_and_reviewed_assets_can_be_reused(pg_repo, config):
    from test_multiuser import Bot

    bot = Bot(pg_repo, config)
    a, b = bot.join(101), bot.join(102)
    token = pg_repo.acquire("delivery", 60)
    try:
        asset = {"file_id": "fake-private-video", "kind": "video", "metadata": {"voice": True}}
        a.save_media_asset("private-key", asset, token)
        assert a.media_asset("private-key")["file_id"] == "fake-private-video"
        assert b.media_asset("private-key") is None
        a.save_media_asset("reviewed-key", asset, token, shared_reviewed=True)
        assert b.media_asset("reviewed-key")["file_id"] == "fake-private-video"
    finally:
        pg_repo.release("delivery", token)
