"""Complete, bundled courses without runtime generation or private progress side effects."""

import json
from types import SimpleNamespace

import pytest
from test_dashboard import signed
from test_flows import command

from skillcoach import course_library as courses
from skillcoach.catalog import MODULES, TOPICS
from skillcoach.clients import ExternalError
from skillcoach.content_checks import lesson_texts, reference_urls
from skillcoach.curriculum import reviewed_entry
from skillcoach.lesson_delivery import stored_lesson
from skillcoach.models import Draft, LabAssignment
from skillcoach.pacing import PACING, build_session
from skillcoach.web import create_app


def topic_in(module):
    return next(ident for ident, (owner, _) in TOPICS.items() if owner.id == module)


@pytest.mark.parametrize("topic", list(TOPICS))
def test_every_catalog_topic_has_substantial_complete_stored_content(topic):
    package = courses.get_package(topic)
    lesson = package.lesson
    assert len(lesson.concepts) == len(lesson.tasks) == 4
    assert len(" ".join(lesson_texts(lesson)).split()) >= 400, topic
    assert len({task.name for task in lesson.tasks}) == 4
    assert len({concept.body for concept in lesson.concepts}) == 4
    assert reference_urls(lesson.references) == lesson.references
    assert lesson.interview_question and len(lesson.interview_points) >= 3
    if reviewed_entry(TOPICS[topic][1]) is None:
        assert lesson.reviewed_at.startswith("AI-generated offline")
    assert len(package.storyboard.scenes) >= 3
    assert package.objectives and package.prerequisites and package.core
    body = courses.page(topic)
    assert body["library"] and body["available"]
    assert body["id"] == topic and body["version"] == courses.VERSION
    assert body["exercises"] == [] and len(body["extension"]) == 4
    assert body["walkthrough"] == package.storyboard.model_dump(mode="json")
    assert "learning" not in body and "profile" not in body


def test_index_has_exact_coverage_and_cached_packages_are_not_mutable():
    index = courses.index()
    listed = [topic["id"] for module in index["modules"] for topic in module["topics"]]
    assert len(listed) == len(set(listed)) == index["total"] == 199
    assert set(listed) == set(TOPICS) and len(index["modules"]) == 23
    ident = topic_in("linux")
    first = courses.get_package(ident)
    title = first.lesson.title
    first.lesson.title = "changed by caller"
    assert courses.get_package(ident).lesson.title == title
    assert courses.get_package(TOPICS[ident][1]).lesson.title == title
    assert courses.get_package("../../private") is None
    with pytest.raises(ExternalError, match="course_content_unavailable"):
        courses.get_package(ident, "../2026-09-29")


def test_reviewed_exact_topic_packages_preserve_original_content():
    from lesson_content import get_lesson
    from skillcoach.models import Lesson
    from skillcoach.storyboard import reviewed_architecture

    found = 0
    for topic, (_, title) in TOPICS.items():
        entry = reviewed_entry(title)
        if entry is not None:
            package = courses.get_package(topic)
            assert package.lesson == Lesson.model_validate(get_lesson(title))
            assert package.core == entry["core"]
            assert package.storyboard == reviewed_architecture(title)
            found += 1
    assert found == 4


@pytest.mark.parametrize("document", ["null", "[]", "{broken", '{"version":"old","lessons":{}}'])
def test_malformed_bundle_is_explicit_and_never_falls_back_to_ai(tmp_path, monkeypatch, document):
    courses._module.cache_clear()
    monkeypatch.setattr(courses, "ROOT", tmp_path)
    folder = tmp_path / courses.VERSION
    folder.mkdir()
    (folder / "linux.json").write_text(document, encoding="utf-8")
    try:
        with pytest.raises(ExternalError, match="course_content_unavailable"):
            courses.get_package(topic_in("linux"))
    finally:
        courses._module.cache_clear()


@pytest.mark.parametrize("module", [m.id for m in MODULES])
def test_delivery_from_each_module_generates_no_lesson_content_and_is_idempotent(harness, module):
    h = harness
    topic = topic_in(module)
    first = command(h, "/learn " + topic)
    # Only the optional plain-language opening asks the AI (unavailable here); the lesson is stored.
    assert not h.ai.calls and len(h.ai.plain_calls) == 1
    assert len(h.repo.state.lessons) == 1 and len(h.repo.state.tasks) == 4
    record = next(iter(h.repo.state.lessons.values()))
    if reviewed_entry(TOPICS[topic][1]) is None:
        assert record["source"] == "library" and record["library_version"] == courses.VERSION
        assert record["topic_id"] == topic
    assert "plain" not in record
    media = [
        r["body"] for r in h.repo.outbox.values() if r["job_id"] == first and r["body"]["kind"] == "media"
    ]
    assert len(media) == 1 and media[0]["mode"] == "video" and media[0]["storyboard"]
    before = h.repo.state.model_dump(mode="json")
    command(h, "/learn " + topic)
    assert h.repo.state.model_dump(mode="json") == before and not h.ai.calls and len(h.ai.plain_calls) == 1
    assert stored_lesson(h.repo, "unused", record).title == courses.get_package(topic).lesson.title


def test_bundled_media_is_shared_without_claiming_expert_review(harness, monkeypatch, tmp_path):
    from skillcoach.clients import Budget
    from skillcoach.media import deliver_storyboard

    h = harness
    job = command(h, "/learn " + topic_in("linux"))
    body = next(
        r["body"] for r in h.repo.outbox.values() if r["job_id"] == job and r["body"]["kind"] == "media"
    )
    assert body["shared_library"] and not body["shared_reviewed"]
    rendered = tmp_path / "fixture.mp4"
    rendered.write_bytes(b"fake-video")
    reviews, captions = [], []

    def render(*args, reviewed, **kwargs):
        reviews.append(reviewed)
        return rendered, {"kind": "video", "voice": False}

    class Telegram:
        def call(self, method, budget, *, data, files):
            captions.append(data["caption"])
            return {"video": {"file_id": "FAKE-COURSE"}}

    monkeypatch.setattr("skillcoach.story_renderer.render_storyboard", render)
    deliver_storyboard(Telegram(), body, Budget(), before_send=lambda: None)
    assert reviews == [False] and "not independently expert-reviewed" in captions[0]
    shared = []
    monkeypatch.setattr(h.repo, "media_asset", lambda key: None, raising=False)
    monkeypatch.setattr(
        h.repo,
        "save_media_asset",
        lambda *args, **kwargs: shared.append(kwargs),
        raising=False,
    )
    monkeypatch.setattr(
        "skillcoach.runtime.deliver_storyboard",
        lambda *args, **kwargs: {"file_id": "FAKE-COURSE", "kind": "video", "metadata": {"voice": False}},
    )
    assert h.runtime.deliver_one(Budget(), media=True)
    assert shared == [{"shared_reviewed": False, "shared_library": True}]


@pytest.mark.parametrize("minutes", list(PACING))
def test_stored_pacing_has_exact_counts_and_no_ai(minutes):
    package = courses.get_package(topic_in("linux"))
    plan = SimpleNamespace(minutes=minutes, id="approved", level="beginner")
    guide, reading = build_session(None, package.lesson, None, plan, package=package)
    assert len(guide.tasks) == PACING[minutes][1]
    assert reading + sum(task.minutes for task in guide.tasks) == minutes
    assert guide.explanation == package.core
    assert [t.name for t in guide.tasks] == [t.name for t in package.lesson.tasks[: len(guide.tasks)]]


def test_read_command_is_optional_and_preserves_active_flows(harness):
    h = harness
    h.repo.state.paused = True
    h.repo.state.draft = Draft(id="unchanged", resume_text="PRIVATE DOCUMENT")
    h.repo.state.focus = "draft"
    h.repo.state.labs["required"] = LabAssignment(
        id="required",
        lab_id="s3-private-presigned",
        token="SC-TEST-TOKN",
        assigned_date=h.clock.now.date(),
        required=True,
    )
    before = h.repo.state.model_dump(mode="json")
    command(h, "/read " + topic_in("linux"))
    command(h, "/read missing-course")
    assert h.repo.state.model_dump(mode="json") == before
    assert not h.ai.calls
    assert all("PRIVATE DOCUMENT" not in text for text, _ in h.telegram.messages)
    assert "does not complete" in h.telegram.messages[0][0]


def test_course_auth_shapes_and_storage_failure_are_explicit(harness, monkeypatch):
    h = harness
    client = create_app(h.runtime).test_client()
    monkeypatch.setattr("skillcoach.dashboard.authorize_learner", lambda *a: ("owner", h.repo.state))
    signed_data = signed(42, h.runtime.config.telegram_token, int(h.clock.now.timestamp()))
    for payload in (
        {},
        {"init_data": ""},
        {"init_data": "", "topic": topic_in("linux")},
        {"init_data": signed_data, "topic": topic_in("linux"), "learner_id": "someone"},
    ):
        assert client.post("/app/course", json=payload).status_code == 403
    assert (
        client.post(
            "/app/course?x=1", json={"init_data": signed_data, "topic": topic_in("linux")}
        ).status_code
        == 403
    )
    assert client.post("/app/course", json={"init_data": signed_data, "topic": "../../x"}).status_code == 404
    before = h.repo.state.model_dump(mode="json")
    response = client.post("/app/course", json={"init_data": signed_data, "topic": topic_in("linux")})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store, private"
    assert response.json["lesson"]["library"]
    assert h.repo.state.model_dump(mode="json") == before and not h.ai.calls
    assert list(h.repo.usage.items()) == [(("2026-09-25", "course_page"), 1)]

    def damaged(*args):
        raise ExternalError("course_content_unavailable", retryable=False)

    monkeypatch.setattr(courses, "get_package", damaged)
    assert (
        client.post("/app/course", json={"init_data": signed_data, "topic": topic_in("linux")}).status_code
        == 503
    )


def test_missing_module_cannot_advertise_a_complete_library(tmp_path, monkeypatch):
    courses._module.cache_clear()
    monkeypatch.setattr(courses, "ROOT", tmp_path)
    try:
        with pytest.raises(ExternalError, match="course_content_unavailable"):
            courses.index()
    finally:
        courses._module.cache_clear()


def test_readiness_rejects_an_incomplete_deployment(harness, monkeypatch):
    def unavailable():
        raise ExternalError("course_content_unavailable", retryable=False)

    monkeypatch.setattr(courses, "index", unavailable)
    client = create_app(harness.runtime).test_client()
    assert client.get("/health/ready").status_code == 403
    response = client.get(
        "/health/ready",
        headers={
            "X-Telegram-Bot-Api-Secret-Token": harness.runtime.config.webhook_secret,
        },
    )
    assert response.status_code == 503 and response.json == {"error": "course_content_unavailable"}


def test_all_walkthrough_frames_fit_the_existing_local_renderer():
    from skillcoach.story_renderer import fonts, render_frame

    font_set = fonts()
    for topic in TOPICS:
        story = courses.get_package(topic).storyboard
        for i in range(len(story.scenes)):
            image = render_frame(story, i, 0, 0, font_set)
            assert image.size == (1280, 720), topic


@pytest.mark.postgres
def test_course_access_requires_approved_membership_without_changing_progress(pg_repo, config):
    import time
    from datetime import datetime

    from test_multiuser import Bot

    bot = Bot(pg_repo, config)
    learner = bot.join(101)
    before = learner.read()[1].model_dump(mode="json")
    bot.runtime.clock = lambda: datetime.now().astimezone()
    client = create_app(bot.runtime).test_client()
    issued = int(time.time()) + 2
    response = client.post(
        "/app/course",
        json={
            "init_data": signed(101, config.telegram_token, issued),
            "topic": topic_in("linux"),
        },
    )
    assert response.status_code == 200 and response.json["private"]
    assert learner.read()[1].model_dump(mode="json") == before
    expired = client.post(
        "/app/course",
        json={
            "init_data": signed(101, config.telegram_token, issued - 600),
            "topic": topic_in("linux"),
        },
    )
    assert expired.status_code == 403
    denied = client.post(
        "/app/course",
        json={
            "init_data": signed(999, config.telegram_token, issued),
            "topic": topic_in("linux"),
        },
    )
    assert denied.status_code == 403
    assert "PRIVATE" not in json.dumps(response.json["lesson"])
    bot.input(config.owner_id, "/revoke " + learner.learner_id)
    assert (
        client.post(
            "/app/course",
            json={
                "init_data": signed(101, config.telegram_token, issued),
                "topic": topic_in("linux"),
            },
        ).status_code
        == 403
    )
