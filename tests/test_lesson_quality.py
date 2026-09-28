"""Lesson quality: validators, reviewed curriculum, compact delivery, full reference and feedback."""

import json
import time
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import pytest
from test_flows import command
from test_journey import callback

from lesson_content import LESSONS
from skillcoach import content_checks as checks
from skillcoach import curriculum
from skillcoach.catalog import TOPICS, find_topic
from skillcoach.clients import ExternalError
from skillcoach.formatting import md_blocks, md_chunks, plain, telegram_html
from skillcoach.lesson_delivery import feedback_summary, find_lesson, page, page_url
from skillcoach.models import Lesson
from skillcoach.pacing import PACING, build_session, split_minutes
from skillcoach.storyboard import reviewed_architecture
from skillcoach.web import create_app

CI = "ci pipeline design stages artifacts and caching"
PODS = "kubernetes pods deployments and replica sets"
TERRAFORM = "terraform providers resources data sources and modules"
RETIRED = """```yaml
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/upload-artifact@main
      - run: echo ok
```"""


def catalog_id(key):
    return next(ident for ident, (_, title) in TOPICS.items() if curriculum.normalize(title) == key)


def ai_lesson(title="Python automation", **changes):
    lesson = json.loads(json.dumps(LESSONS["ec2"]))
    lesson.update(title=title, reviewed_at="AI-generated; not independently reviewed", **changes)
    return lesson


def job_texts(h, job):
    return [row["body"]["text"] for row in h.repo.outbox.values() if row["job_id"] == job]


# Formatting ---------------------------------------------------------------------------------------


def test_telegram_html_escapes_first_and_converts_the_supported_subset():
    html = telegram_html("**Bold** <b>raw</b> & `a<b>`\n- item\n```yaml\nkey: <v>\n```")
    assert "<b>Bold</b>" in html and "&lt;b&gt;raw&lt;/b&gt; &amp;" in html
    assert "<code>a&lt;b&gt;</code>" in html and "• item" in html
    assert '<pre><code class="language-yaml">key: &lt;v&gt;</code></pre>' in html
    assert "**" not in html
    assert plain("**Bold** `x`") == "Bold x"


def test_md_chunks_never_split_inside_a_code_fence():
    fence = "```bash\n" + "\n".join(f"echo {i}" for i in range(60)) + "\n```"
    text = "\n\n".join(["Intro paragraph. " * 40, fence, "Outro. " * 40])
    chunks = md_chunks(text, limit=700)
    assert len(chunks) > 1
    assert all(chunk.count("```") % 2 == 0 for chunk in chunks)
    assert sum(chunk.count("echo 59") for chunk in chunks) == 1


def test_md_blocks_is_data_only_and_keeps_list_numbering():
    blocks = md_blocks("Line one **b** `c` <img>\n\n3. third\n4. fourth\n\n- dot\n\n```json\n{}\n```")
    kinds = [block["type"] for block in blocks]
    assert kinds == ["p", "ol", "ul", "code"]
    spans = blocks[0]["spans"]
    assert {"t": "b", "v": "b"} in spans and {"t": "code", "v": "c"} in spans
    assert any(span["t"] == "text" and "<img>" in span["v"] for span in spans)
    assert blocks[1].get("start") == 3 and len(blocks[1]["items"]) == 2
    assert blocks[3]["lang"] == "json" and blocks[3]["text"] == "{}"


# Content checks -----------------------------------------------------------------------------------


def test_validators_catch_each_known_defect_with_a_repair_hint():
    problems = checks.text_problems(RETIRED)
    assert any("actions/checkout@v3 is retired" in p for p in problems)
    assert any("not @main" in p for p in problems)
    assert any('"terraform:*" is not an IAM action' in p for p in checks.text_problems('"terraform:*"'))
    assert checks.text_problems('"s3:GetObject" and https://github.com/org/repo') == []
    nested = "```yaml\njobs:\n  deploy:\n    on: push\n    runs-on: ubuntu-latest\n```"
    assert any("top level" in p for p in checks.text_problems(nested))
    late = (
        "```yaml\nsteps:\n  - run: terraform plan\n  - uses: aws-actions/configure-aws-credentials@v6\n"
        "    with:\n      role-to-assume: arn\n```"
    )
    found = checks.text_problems(late)
    assert any("before any terraform" in p for p in found) and any("id-token: write" in p for p in found)
    assert any("not valid JSON" in p for p in checks.text_problems('```json\n{"a": 1,}\n```'))


def test_upgrade_actions_rewrites_retired_and_branch_pins_only():
    upgraded = checks.upgrade_actions(RETIRED + "\nuses: actions/cache@v4.2.0 and some/other@v1")
    assert "actions/checkout@v7" in upgraded and "actions/upload-artifact@v7" in upgraded
    assert "actions/cache@v4.2.0" in upgraded and "some/other@v1" in upgraded
    assert checks.text_problems(upgraded) == []


def test_lesson_validator_requires_official_reference_unless_catalog_supplies_one():
    docs = "https://kubernetes.io/docs/concepts/workloads/"
    lesson = Lesson.model_validate(ai_lesson(references=["https://example.com/blog"]))
    with pytest.raises(ValueError, match="official documentation"):
        checks.lesson_validator(None)(lesson)
    checks.lesson_validator(docs)(lesson)
    assert checks.finalize_lesson(lesson, docs).references == [docs]
    bad = Lesson.model_validate(ai_lesson(why='Grant "terraform:*" to the runner.'))
    with pytest.raises(ValueError, match="not an IAM action"):
        checks.lesson_validator(docs)(bad)
    retired = Lesson.model_validate(ai_lesson(why=RETIRED.replace("@main", "@v4")))
    checks.lesson_validator(docs)(retired)
    assert "actions/checkout@v7" in checks.finalize_lesson(retired, docs).why


# Reviewed curriculum ------------------------------------------------------------------------------


def unsupported_markup(texts):
    import re

    italic = re.compile(r"(?<![*\w])\*(?![\s*])[^*\n]+(?<![\s*])\*(?![*\w])")
    found = []
    for text in texts:
        prose = re.sub(r"`[^`\n]+`", "", checks.FENCED.sub("", text))
        found += italic.findall(prose)
    return found


@pytest.mark.parametrize("key", sorted(curriculum.REVIEWED))
def test_reviewed_lessons_are_valid_on_topic_and_have_a_reviewed_video(key):
    entry = curriculum.REVIEWED[key]
    ident = catalog_id(key)
    title = TOPICS[ident][1]
    assert find_topic(ident)[2] == title
    lesson = Lesson.model_validate(curriculum.reviewed_lesson(title))
    checks.validate_lesson(lesson)
    assert checks.reference_urls(lesson.references) == lesson.references
    assert len(lesson.tasks) == 4 and all(checks.problems_for([checks.task_text(t)]) == [] for t in lesson.tasks)
    assert lesson.interview_question and 3 <= len(lesson.interview_points) <= 5
    assert not lesson.reviewed_at.startswith("AI-generated")
    assert checks.problems_for([entry["core"]]) == []
    assert unsupported_markup([entry["core"], *checks.lesson_texts(lesson), *lesson.interview_points]) == []
    assert len(entry["core"]) <= PACING[15][2]
    board = reviewed_architecture(title)
    assert board is not None and 3 <= len(board.scenes) <= 5


@pytest.mark.parametrize("key", sorted(LESSONS))
def test_authored_aws_lessons_have_their_own_interview_question_and_display_names(key):
    from skillcoach.lesson_delivery import closing, display_name, exercises

    lesson = Lesson.model_validate(LESSONS[key])
    checks.validate_lesson(lesson)
    assert unsupported_markup([*checks.lesson_texts(lesson), *lesson.interview_points]) == []
    assert lesson.interview_question and 3 <= len(lesson.interview_points) <= 5
    assert "Walk me through a design" not in closing(lesson, key)
    text = exercises(lesson, lesson.tasks, ["0" * 20] * len(lesson.tasks))
    assert "(20 min):" not in text and "(15 min):" not in text
    assert display_name(lesson.tasks[0].name) in text and len(md_chunks(text)) == 1


@pytest.mark.parametrize("base,total", [([8, 10, 12, 10], 10), ([8, 10, 12], 30), ([8, 12], 7), ([5], 3)])
def test_split_minutes_is_exact_and_positive(base, total):
    minutes = split_minutes(base, total)
    assert sum(minutes) == total and all(m >= 1 for m in minutes) and len(minutes) == len(base)


@pytest.mark.parametrize("minutes", sorted(PACING))
def test_reviewed_topic_session_is_deterministic_and_exact(minutes):
    title = TOPICS[catalog_id(PODS)][1]
    lesson = Lesson.model_validate(curriculum.reviewed_lesson(title))
    plan = SimpleNamespace(id="plan", minutes=minutes, level="beginner")
    session = SimpleNamespace(objective="OBJECTIVE", practice="PRACTICE")
    # No service: a reviewed topic must never reach the AI provider.
    guide, reading = build_session(None, lesson, session, plan, title)
    assert reading == PACING[minutes][0] and len(guide.tasks) == PACING[minutes][1]
    assert sum(t.minutes for t in guide.tasks) + reading == minutes
    assert [t.name for t in guide.tasks] == [t.name for t in lesson.tasks[: len(guide.tasks)]]
    assert guide.explanation == curriculum.REVIEWED[PODS]["core"]


# Compact delivery ---------------------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(curriculum.REVIEWED))
def test_every_reviewed_lesson_fits_one_message_per_part_at_every_pace(key):
    from datetime import date

    from skillcoach.lesson_delivery import closing, exercises, mission

    title = TOPICS[catalog_id(key)][1]
    lesson = Lesson.model_validate(curriculum.reviewed_lesson(title))
    session = SimpleNamespace(objective="O" * 300, practice="P" * 300)
    ids = ["0" * 20] * 4
    parts = [mission(lesson, date(2026, 9, 29)), exercises(lesson, lesson.tasks, ids), closing(lesson, title)]
    for minutes in PACING:
        plan = SimpleNamespace(id="plan", minutes=minutes, level="beginner")
        guide, reading = build_session(None, lesson, session, plan, title)
        parts += [
            mission(lesson, date(2026, 9, 29), guide, reading, session, plan),
            exercises(lesson, guide.tasks, ids, minutes - reading),
        ]
    assert all(len(md_chunks(part)) == 1 for part in parts)


def test_reviewed_topic_lesson_is_compact_on_topic_and_needs_no_ai(harness):
    h = harness
    h.runtime.config = replace(h.runtime.config, private_dashboard_url="https://example.com/app")
    job = command(h, "/learn " + catalog_id(CI))
    assert not h.ai.calls
    bodies = [row["body"] for row in h.repo.outbox.values() if row["job_id"] == job]
    assert [b["kind"] for b in bodies] == ["text", "media", "text", "text"]
    mission, media, exercises, closing = bodies
    assert all(b["format"] == "md" and len(b["text"]) <= 4000 for b in (mission, exercises, closing))
    assert "Cost and safety" in mission["text"] and "Cleanup when you finish" in closing["text"]
    assert media["shared_reviewed"] and media["storyboard"]["scenes"]
    key, record = next(iter(h.repo.state.lessons.items()))
    ident = record["id"]
    assert record["source"] == "authored" and closing["lesson_key"] == key
    assert mission["buttons"] == [
        [{"text": "Open lesson page", "web_app": {"url": f"https://example.com/app?lesson={ident}"}}],
        [{"text": "Read the full lesson here", "callback_data": f"lr:{ident}"}],
    ]
    assert len(h.repo.state.tasks) == 4
    assert all(f"/complete {task}" in exercises["text"] for task in h.repo.state.tasks)
    lesson = Lesson.model_validate(curriculum.reviewed_lesson(TOPICS[catalog_id(CI)][1]))
    assert lesson.interview_question in closing["text"] and "Walk me through a design" not in closing["text"]
    feedback = [b["callback_data"] for row in closing["buttons"] for b in row]
    assert feedback == [f"lf:{ident}:up", f"lf:{ident}:down", f"lf:{ident}:report"]
    assert all(len(data.encode()) <= 64 for data in feedback)
    text = "\n".join(b.get("text", "") for b in bodies)
    for retired in ("upload-artifact@v3", "checkout@v3", "terraform:*"):
        assert retired not in text
    # Only the mission is sent before the (skipped) video render; its HTML carries no raw Markdown.
    assert h.telegram.messages[0][0].startswith("<b>📘 ")


def test_ai_lesson_is_validated_upgraded_and_uses_one_architecture_video(harness):
    h = harness
    generated = ai_lesson(why="Start from this workflow:\n" + RETIRED.replace("@main", "@v4"))
    h.ai.responses.extend([generated, reviewed_architecture("EC2").model_dump()])
    job = command(h, "/learn Python")
    assert [name for _, name in h.ai.calls] == ["Lesson", "Storyboard"]
    record = next(iter(h.repo.state.lessons.values()))
    assert record["source"] == "AI" and record["job_id"] == job
    callback(h, f"lr:{record['id']}")
    text = "\n".join(job_texts(h, list(h.repo.jobs)[-1]))
    assert "actions/checkout@v7" in text and "checkout@v3" not in text
    assert "not human-reviewed" in text


def test_full_reference_callback_reads_authored_and_cached_ai_lessons(harness):
    h = harness
    command(h, "/learn EC2")
    record = next(iter(h.repo.state.lessons.values()))
    job = callback(h, f"lr:{record['id']}")
    text = "\n".join(job_texts(h, job))
    for heading in ("Full lesson", "End to end", "Key terms", "Official references"):
        assert heading in text
    assert any(message.startswith("<b>📖 Full lesson") for message, _ in h.telegram.messages)
    h.ai.responses.extend([ai_lesson(title="Python full lesson"), reviewed_architecture("EC2").model_dump()])
    command(h, "/learn Python")
    ai_record = next(r for r in h.repo.state.lessons.values() if r["source"] == "AI")
    del ai_record["job_id"]  # older records find their job through the outbox
    job = callback(h, f"lr:{ai_record['id']}")
    assert "Python full lesson" in "\n".join(job_texts(h, job))
    calls = len(h.ai.calls)
    job = callback(h, "lr:" + "0" * 20)
    assert "not available" in job_texts(h, job)[0] and len(h.ai.calls) == calls


def test_lesson_feedback_stores_only_controlled_choices(harness):
    h = harness
    command(h, "/learn EC2")
    key, record = next(iter(h.repo.state.lessons.items()))
    ident = record["id"]
    callback(h, f"lf:{ident}:up")
    callback(h, f"lf:{ident}:down")
    callback(h, f"lf:{ident}:report")
    reasons = [b["callback_data"] for row in h.telegram.messages[-1][1] for b in row]
    assert reasons == [f"lf:{ident}:r:{code}" for code in ("wrong", "outdated", "confusing", "hard", "easy")]
    callback(h, f"lf:{ident}:r:outdated")
    callback(h, f"lf:{ident}:r:outdated")
    job = callback(h, f"lf:{ident}:r:free-text")
    assert "Unsupported" in job_texts(h, job)[0]
    feedback = h.repo.state.lessons[key]["feedback"]
    assert feedback["rating"] == "down" and feedback["reports"] == ["outdated"]
    assert set(feedback) == {"rating", "rated_at", "reports", "reported_at"}
    assert feedback_summary([h.repo.state]) == {
        "ratings": {"up": 0, "down": 1},
        "reports": {"wrong": 0, "outdated": 1, "confusing": 0, "hard": 0, "easy": 0},
    }
    job = callback(h, "lf:" + "0" * 20 + ":up")
    assert "not recorded" in job_texts(h, job)[0]


def test_lesson_page_is_structured_and_scoped_to_the_learner_history(harness):
    h = harness
    command(h, "/learn " + catalog_id(TERRAFORM))
    record = next(iter(h.repo.state.lessons.values()))
    data = page(h.repo, h.repo.state, record["id"], h.clock.now)
    assert data["available"] and data["title"].startswith("Terraform")
    headings = [s["heading"] for s in data["sections"]]
    assert headings[:2] == ["Why it matters", "What it is"] and headings[-1] == "Cost and safety"
    assert [n["heading"] for n in data["notes"]] == ["Cleanup"]
    assert [e["id"] for e in data["exercises"]] == list(h.repo.state.tasks)
    assert data["interview"]["points"] and all(u.startswith("https://") for u in data["references"])
    blocks = [b for s in data["sections"] for b in s["blocks"]] + [
        b for e in data["exercises"] for b in e["blocks"]
    ]
    assert any(b["type"] == "code" for b in blocks)
    json.dumps(data)
    assert page(h.repo, h.repo.state, "f" * 20, h.clock.now) is None
    assert find_lesson(h.repo.state, "../etc") == (None, None)
    assert page_url("https://x.test/app?lesson=old&a=1", "b" * 20) == "https://x.test/app?a=1&lesson=" + "b" * 20


def test_runtime_sends_markdown_as_html_and_falls_back_to_plain_text_once(harness):
    h = harness
    sent = []

    def send(text, budget, buttons=None, *, parse_mode=None):
        sent.append((text, parse_mode))
        if parse_mode == "HTML" and len(sent) == 1:
            raise ExternalError("http_400")

    h.telegram.send = send
    job = command(h, "/learn EC2")
    assert sent[0][1] == "HTML" and "<b>📘 " in sent[0][0]
    assert sent[1][1] is None and sent[1][0].startswith("📘 ") and "**" not in sent[1][0]
    assert len(sent) == 2 and h.repo.outbox[f"{job}:0"]["status"] == "sent"


# Dashboard lesson endpoint ------------------------------------------------------------------------


def test_lesson_endpoint_rejects_bad_shapes_before_storage(harness, monkeypatch):
    monkeypatch.setattr(
        "skillcoach.dashboard.authorize_learner", lambda *a: pytest.fail("reached private storage")
    )
    client = create_app(harness.runtime).test_client()
    assert client.post("/app/lesson", json={"init_data": "x"}).status_code == 403
    assert client.post("/app/lesson?x=1", json={"init_data": "x", "lesson": "a" * 20}).status_code == 403
    assert client.post("/app/lesson", json={"init_data": "x", "lesson": "../../x"}).status_code == 404
    response = client.post("/app/lesson", json={"init_data": "x", "lesson": "a" * 20})
    assert response.status_code == 403 and response.headers["Cache-Control"] == "no-store, private"


@pytest.mark.postgres
def test_lesson_endpoint_returns_only_the_signed_learners_lesson(pg_repo, config):
    from test_dashboard import signed
    from test_multiuser import Bot

    bot = Bot(pg_repo, config)
    a, b = bot.join(101), bot.join(102)
    bot.input(101, "/learn " + catalog_id(CI))
    ident = next(iter(a.read()[1].lessons.values()))["id"]
    bot.runtime.clock = lambda: datetime.now().astimezone()
    client = create_app(bot.runtime).test_client()
    issued = int(time.time()) + 2
    token = config.telegram_token
    response = client.post("/app/lesson", json={"init_data": signed(101, token, issued), "lesson": ident})
    assert response.status_code == 200 and response.json["private"]
    assert response.json["lesson"]["id"] == ident and len(response.json["lesson"]["exercises"]) == 4
    assert response.headers["Cache-Control"] == "no-store, private"
    other = client.post("/app/lesson", json={"init_data": signed(102, token, issued), "lesson": ident})
    assert other.status_code == 404 and "exercises" not in other.get_data(as_text=True)
    stranger = client.post("/app/lesson", json={"init_data": signed(999, token, issued), "lesson": ident})
    assert stranger.status_code == 403
    listed = client.post("/app/data", json={"init_data": signed(101, token, issued)})
    assert [item["id"] for item in listed.json["lessons"]] == [ident]
    assert b.read()[1].lessons == {}
