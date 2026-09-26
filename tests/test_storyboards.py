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


def test_edge_labels_are_present_in_rendered_output():
    story = reviewed_architecture("EC2")
    font_set = fonts()
    original = render_frame(story, 0, 0.3, 0.1, font_set).crop((35, 555, 1245, 602))
    story.edges[0].label = "HTTPS request"
    labelled = render_frame(story, 0, 0.3, 0.1, font_set).crop((35, 555, 1245, 602))
    assert original.tobytes() != labelled.tobytes()


def test_authored_concept_actors_are_specific_not_generic_camera_slides():
    families = concept_walkthrough(Lesson.model_validate(LESSONS["ec2"]), 0)
    storage = concept_walkthrough(Lesson.model_validate(LESSONS["s3"]), 0)
    policies = concept_walkthrough(Lesson.model_validate(LESSONS["iam"]), 0)
    assert "Burstable CPU credits" in {actor.label for actor in families.actors}
    assert "Standard-IA" in {actor.label for actor in storage.actors}
    assert "Explicit deny" in {actor.label for actor in policies.actors}
    assert {actor.label for actor in families.actors} != {actor.label for actor in storage.actors}
    assert all(story.pattern == "comparison" and not story.edges for story in (families, storage, policies))


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


def test_static_generated_lesson_does_not_require_storyboard_or_voice_generation(harness):
    from test_flows import command

    command(harness, "/media static")
    raw = json.loads(json.dumps(LESSONS["ec2"]))
    raw["title"] = "Python automation"
    raw["reviewed_at"] = "AI-generated"
    harness.ai.responses.append(raw)
    command(harness, "/learn Python")
    assert len(harness.ai.calls) == 1
    assert len(harness.repo.state.tasks) == 3
    bodies = [row["body"] for row in harness.repo.outbox.values() if row["body"]["kind"] == "media"]
    assert len(bodies) == 5 and all("storyboard" not in body for body in bodies)


@pytest.mark.postgres
def test_slow_multicall_lesson_checkpoints_resume_without_exhausting_failures(pg_repo, config):
    from datetime import date, datetime, timedelta

    from conftest import FakeAI, FakePublisher, FakeTelegram
    from test_flows import PROFILE
    from test_postgres import seed

    from skillcoach.models import Profile
    from skillcoach.runtime import Runtime
    from skillcoach.timeutil import IST

    class TimedBudget:
        def __init__(self):
            self.left = 20

        def remaining(self):
            if self.left <= 0:
                raise ExternalError("request_budget_exhausted")
            return self.left

    class SlowAI(FakeAI):
        def structured(self, prompt, model, budget, validate=None):
            # Two ordinary 15-second generations cannot fit in a single 20-second request.
            assert budget.remaining() >= 15
            budget.left -= 15
            return super().structured(prompt, model, budget, validate)

    ai = SlowAI()
    start = date(2026, 9, 21)
    plan = {
        "days": {(start + timedelta(days=i)).isoformat(): "Python automation" for i in range(6)},
        "rationale": "Actual profile practice",
    }
    lesson = json.loads(json.dumps(LESSONS["ec2"]))
    lesson["title"], lesson["reviewed_at"] = "Python automation", "AI-generated"
    ai.responses.extend([plan, lesson, *[reviewed_architecture("EC2").model_dump() for _ in range(5)]])
    seed(pg_repo, lambda state: setattr(state, "profile", Profile(**PROFILE)))
    runtime = Runtime(
        config, pg_repo, ai, FakeTelegram(), FakePublisher(), lambda: datetime(2026, 9, 25, 9, tzinfo=IST)
    )
    pg_repo.enqueue("slow-lesson", {"type": "schedule", "kind": "lesson", "date": "2026-09-25"})
    for turn in range(7):
        assert runtime.process_one(TimedBudget())
        with pg_repo.connection() as conn:
            job = conn.execute("SELECT status,attempts FROM jobs WHERE id='slow-lesson'").fetchone()
            assert job["status"] == ("done" if turn == 6 else "pending")
            assert job["attempts"] == (1 if turn == 6 else 0)
        if turn < 6:
            assert pg_repo.read()[1].tasks == {}
    assert len(ai.calls) == 7 and not ai.responses
    assert len(pg_repo.read()[1].tasks) == 3
    with pg_repo.connection() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM ai_results WHERE job_id='slow-lesson'").fetchone()["n"]
            == 7
        )
        assert (
            conn.execute("SELECT count(*) AS n FROM ai_usage WHERE job_id='slow-lesson'").fetchone()["n"] == 7
        )
        assert (
            conn.execute("SELECT count(*) AS n FROM outbox WHERE id='slow-lesson:failure'").fetchone()["n"]
            == 0
        )


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
