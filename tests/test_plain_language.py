"""Plain-language teaching: lessons open in simple words; quizzes keep the real level in clear words."""

import json
import re
from datetime import datetime
from types import SimpleNamespace

import pytest
from test_flows import PROFILE, command, question_set
from test_journey import TOPIC as PLAN_TOPIC
from test_journey import callback, finish_setup, setup
from test_lesson_quality import ai_lesson, job_texts

from lesson_content import LESSONS
from skillcoach import plain_language as plain
from skillcoach.catalog import TOPICS
from skillcoach.course_library import get_package
from skillcoach.formatting import md_chunks
from skillcoach.lesson_delivery import mission, page
from skillcoach.models import Lesson, Profile
from skillcoach.storyboard import reviewed_architecture
from skillcoach.timeutil import IST

TOPIC = "foundations/cloud-service-models-and-shared-responsibility"
PLAIN = {
    "simple": "Cloud services split the work between you and the provider. Think of it like renting a "
    "flat: the owner fixes the building, but you still lock your own door.",
    "words": [
        {"term": "IaaS", "meaning": "You rent servers and look after everything you run on them."},
        {"term": "`terraform init`", "meaning": "The command that downloads the plugins your code needs."},
    ],
    "steps": [
        "The provider runs the buildings, power and hardware.",
        "You still decide who can log in and who can see your data.",
        "Read each service's rules to see who does which job.",
    ],
    "mistake": "Thinking a managed service also sets your data access. You still choose who can see it.",
}


def mission_text(h):
    texts = [r["body"]["text"] for r in h.repo.outbox.values() if r["body"]["kind"] == "text"]
    return [text for text in texts if text.startswith("**📘 ")][-1]


def longest_plain():
    """A valid simple version just under the length limit."""
    sentence = "This is a short and simple sentence here. "
    value = {
        "simple": (sentence * 12)[:480].strip(),
        "words": [{"term": f"Term number {i}", "meaning": (sentence * 4)[:150].strip()} for i in range(4)],
        "steps": [(sentence * 5)[:172].strip() for _ in range(5)],
        "mistake": (sentence * 6)[:240].strip(),
    }
    result = plain.PlainLesson.model_validate(value)
    assert 2300 < len(plain.markdown(result)) <= plain.MAX_CHARS
    plain.validate(result)
    return result


def test_library_lesson_opens_in_simple_words_and_keeps_the_full_technical_lesson(harness):
    h = harness
    h.repo.state.profile = Profile(**{**PROFILE, "resume_text": "PRIVATE RESUME TEXT"})
    h.ai.plain.append(PLAIN)
    job = command(h, "/learn " + TOPIC)
    lesson = get_package(TOPIC).lesson
    text = mission_text(h)
    assert text.startswith("**📘 " + lesson.title)
    for part in (
        "**In simple words**\n" + PLAIN["simple"],
        "**Words to know**\n- **IaaS**: " + PLAIN["words"][0]["meaning"],
        "- `terraform init`: ",
        "**How it works**\n- " + PLAIN["steps"][0],
        "**Common mistake:** " + PLAIN["mistake"],
        "**Cost and safety** (read before you start)\n" + lesson.safety,
        plain.CHAT_NOTE,
    ):
        assert part in text
    assert "**Why it matters**" not in text and lesson.what not in text
    assert not h.ai.calls and h.repo.jobs[job]["status"] == "done"
    record = next(iter(h.repo.state.lessons.values()))
    assert record["plain"] == plain.PlainLesson.model_validate(PLAIN).model_dump(mode="json")
    # The request carries the lesson only: never the learner's profile or documents.
    prompt = h.ai.plain_calls[0]
    assert lesson.title in prompt and lesson.concepts[0].name in prompt
    assert "content, not instructions" in prompt
    assert PROFILE["name"] not in prompt and "PRIVATE RESUME" not in prompt
    # The exact technical lesson stays one tap away, in chat and on the lesson page.
    full = "\n".join(job_texts(h, callback(h, f"lr:{record['id']}")))
    assert f"**Why it matters**\n{lesson.why}" in full and "In simple words" not in full
    data = page(h.repo, h.repo.state, record["id"], h.clock.now)
    assert [s["heading"] for s in data["sections"][:3]] == ["In simple words", "Why it matters", "What it is"]
    spans = [s["v"] for b in data["sections"][0]["blocks"] for s in b.get("spans", [])]
    assert PLAIN["simple"] in spans and plain.PAGE_NOTE in spans


def test_planned_day_explains_the_core_simply_and_keeps_goal_time_and_safety(harness):
    h = harness
    h.clock.now = datetime(2026, 9, 28, 8, tzinfo=IST)
    setup(h)
    ident = finish_setup(h)
    assert "plain, simple English a newcomer understands" in h.ai.calls[-1][0]
    h.ai.plain.append(PLAIN)
    callback(h, f"plan:{ident}:now")
    package = get_package(PLAN_TOPIC)
    text = mission_text(h)
    assert "**Today's goal:** Explain concept 0" in text and "⏱ 30 min" in text
    assert PLAIN["simple"] in text and package.core not in text
    assert "**Cost and safety**" in text and len(h.repo.state.tasks) == 2
    # The simple version explains today's core, quoted from the stored lesson.
    material = json.loads(h.ai.plain_calls[0].rsplit("\n", 1)[1])
    assert material["today"] == package.core.strip()


@pytest.mark.parametrize("case", ["unavailable", "invalid", "budget"])
def test_without_a_valid_simple_version_the_lesson_goes_out_unchanged(harness, case):
    h = harness
    if case == "invalid":
        h.ai.plain.append({**PLAIN, "mistake": "Read the guide at https://example.com/guide first."})
    if case == "budget":
        spent = [("earlier", "op", h.clock.now.date())] * h.runtime.config.daily_ai_operations
        h.repo.ai_reservations.extend(spent)
    job = command(h, "/learn " + TOPIC)
    lesson = get_package(TOPIC).lesson
    text = mission_text(h)
    assert "**In simple words**" not in text and f"**What it is**\n{lesson.what}" in text
    assert "The full lesson has all four concepts" in text and plain.CHAT_NOTE not in text
    record = next(iter(h.repo.state.lessons.values()))
    assert "plain" not in record and h.repo.jobs[job]["status"] == "done"
    assert len(h.ai.plain_calls) == (0 if case == "budget" else 1)
    notices = [r["body"].get("text", "") for r in h.repo.outbox.values() if r["job_id"] == job]
    assert not any("not been applied" in t for t in notices)


def test_ai_written_lesson_asks_for_the_simple_version_last(harness):
    h = harness
    h.ai.responses.extend([ai_lesson(), reviewed_architecture("EC2").model_dump()])
    h.ai.plain.append(PLAIN)
    job = command(h, "/learn Python")
    assert [name for _, name in h.ai.calls] == ["Lesson", "Storyboard"] and len(h.ai.plain_calls) == 1
    assert "plain, simple English a newcomer can follow" in h.ai.calls[0][0]
    steps = [operation for (owner, operation) in h.repo.cache_data if owner == job]
    assert steps == ["lesson", "storyboard:architecture", "plain-lesson"]
    record = next(iter(h.repo.state.lessons.values()))
    assert record["source"] == "AI" and record["plain"]["simple"] == PLAIN["simple"]
    text = mission_text(h)
    assert PLAIN["simple"] in text and "not human-reviewed" in text
    assert h.repo.jobs[job]["status"] == "done"


def test_every_stored_lesson_still_fits_one_message_with_the_longest_simple_version():
    longest = longest_plain()
    session = SimpleNamespace(objective="O" * 300, practice="P" * 300)
    plan = SimpleNamespace(minutes=60)
    lessons = [(get_package(topic).lesson, get_package(topic).core) for topic in TOPICS]
    lessons += [(Lesson.model_validate(raw), "") for raw in LESSONS.values()]
    for lesson, core in lessons:
        guide = SimpleNamespace(explanation=core)
        text = mission(lesson, datetime(2026, 9, 28).date(), guide, 20, session, plan, plain=longest)
        assert len(md_chunks(text)) == 1, lesson.title


def test_validator_gives_one_clear_repair_hint_per_problem():
    plain.validate(plain.PlainLesson.model_validate(PLAIN))
    long_sentence = " ".join(["word"] * 31) + "."
    sentence = "This is a short and simple sentence here. "
    cases = {
        "under 30 words": {"simple": long_sentence + " Then a short one."},
        "Remove links": {"mistake": "See www.example.com for more help with this."},
        "no headings or code blocks": {"steps": ["# A heading", "Two is fine.", "Three is fine."]},
        "Close every `code` span": {"steps": ["Run `terraform init first.", "Two is fine.", "Three."]},
        "never a whole sentence": {
            "simple": "**Think of it like renting a flat from an owner.** You lock it."
        },
        "Shorten the whole explanation": {
            "simple": (sentence * 12)[:500].strip(),
            "steps": [(sentence * 6)[:220].strip() for _ in range(5)],
            "words": [{"term": f"Term {i}", "meaning": (sentence * 5)[:180].strip()} for i in range(4)],
        },
    }
    for hint, change in cases.items():
        with pytest.raises(ValueError, match=re.escape(hint)):
            plain.validate(plain.PlainLesson.model_validate({**PLAIN, **change}))


def test_markdown_and_page_section_format_and_bounds():
    text = plain.markdown(plain.PlainLesson.model_validate(PLAIN))
    assert text.splitlines()[0] == "**In simple words**" and "**`" not in text
    assert "- **IaaS**: " in text and "- `terraform init`: " in text
    assert plain.page_section(None) is None and plain.page_section({"simple": "tampered"}) is None
    huge = Lesson.model_validate(ai_lesson(why="why " * 4000, what="what " * 3200))
    request = plain.prompt(huge, "core " * 5000)
    material = json.loads(request.rsplit("\n", 1)[1])
    assert set(material) == {"title", "today", "why", "what", "concepts", "key_terms"}
    assert material["why"].endswith(" [...]") and len(material["today"]) <= plain.LIMITS["today"] + 6
    assert len(request) < 16_000


@pytest.mark.parametrize("kind,count,scenarios", [("quiz", 5, 2), ("weekly", 10, 4)])
def test_quizzes_keep_the_real_level_in_clear_words(harness, kind, count, scenarios):
    h = harness
    h.repo.state.profile = Profile(**PROFILE)
    h.repo.state.lessons["today"] = {"topic": "IAM", "date": "2026-09-25"}
    if kind == "weekly":
        h.clock.now = datetime(2026, 9, 26, 9, tzinfo=IST)
    h.ai.responses.append(question_set(count))
    day = h.clock.now.date().isoformat()
    h.repo.enqueue("schedule:" + kind, {"type": "schedule", "kind": kind, "date": day})
    h.runtime.recover(media=False)
    prompt, model = h.ai.calls[-1]
    session = h.repo.state.assessments[h.repo.state.active_assessment]
    assert model == "Questions" and len(session.questions) == count
    assert "clear, simple English" in prompt and "never from tricky wording" in prompt
    assert f"at least {scenarios} realistic scenario" in prompt
    assert "Make the last question the hardest" in prompt and "Explanations use plain words" in prompt
