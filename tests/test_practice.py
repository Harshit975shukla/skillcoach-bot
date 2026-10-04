"""Practice (/web/practice): lesson content, the derived library lessons and the read-only routes."""

import json
import math
import re

import pytest
from pydantic import ValidationError
from test_web_channel import ORIGIN, build_web, post, sign_in

from skillcoach import practice
from skillcoach.catalog import MODULES, TOPICS
from skillcoach.web import create_app

FEATURED = practice.FEATURED


def unit():
    return practice.units()[FEATURED]


def text_of(spans):
    return "".join(str(span["v"]) for span in spans)


def walk(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)
    elif isinstance(value, str):
        yield value


# Content ---------------------------------------------------------------------------------------------


def test_the_hand_crafted_unit_is_valid_and_teaches_with_every_exercise_type():
    crafted = practice.units()
    assert list(crafted) == [FEATURED]
    lessons = unit().lessons
    assert [lesson.id for lesson in lessons] == ["pods", "replicasets", "rolling-updates", "rollback"]
    assert all(url.startswith("https://kubernetes.io/docs/") for url in unit().references)
    assert "Not independently expert-reviewed" in unit().review
    types = {step.type for lesson in lessons for step in lesson.steps}
    assert types == {"teach", "choice", "truefalse", "match", "order", "fill", "spot", "explain"}
    for lesson in lessons:
        assert 8 <= len(lesson.steps) <= 12 and 2 <= len(lesson.takeaways) <= 4
        # Answer first: every lesson opens with a question (a guess before teaching or a check), and
        # most of it is answering, not reading.
        assert lesson.steps[0].type != "teach" or lesson.steps[1].type != "teach"
        graded = [
            step for step in lesson.steps if step.type != "teach" and not getattr(step, "pretest", False)
        ]
        assert len(graded) >= len(lesson.steps) / 2
        for step in lesson.steps:
            if step.type == "choice":
                assert all(option.why for option in step.options), "every option explains itself"
    assert [lesson.icon for lesson in lessons] == ["pod", "replicaset", "rollout", "rollback"]
    assert [lesson.steps[0].id for lesson in lessons] == [
        "guess-node-fails",
        "guess-labels",
        "guess-rollout",
        "guess-users",
    ]
    # Markdown italics are not part of the lesson subset, so stray asterisks would show as text.
    raw = practice.DATA.joinpath("kubernetes-pods-deployments-and-replica-sets.json").read_text(
        encoding="utf-8"
    )
    assert not re.search(r"(?<!\*)\*(?!\*)", raw)


def test_rolling_update_arithmetic_in_the_lessons_matches_the_kubernetes_rounding_rules():
    """maxSurge rounds up and maxUnavailable rounds down (both default 25%): the authored numbers must
    stay consistent with that rule if anyone edits them."""
    steps = {step.id: step for lesson in unit().lessons for step in lesson.steps}

    def limits(replicas):
        return math.ceil(replicas * 0.25), math.floor(replicas * 0.25)

    surge, unavailable = limits(10)
    assert steps["ten-replicas"].answer == [str(surge), str(replicas_left := 10 - unavailable)]
    assert replicas_left == 8 and surge == 3
    three = next(option.text for option in steps["three-replicas"].options if option.correct)
    assert limits(3) == (1, 0) and three == "Up to 1 extra Pod, and all 3 must stay available"
    assert limits(4) == (1, 1) and "at least 3 must stay available" in steps["two-limits"].body
    assert "600 s" in steps["stalled"].body and "default **10**" in steps["history"].body


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda s: s["lessons"][0]["steps"][0]["options"][0].update(correct=True), "exactly one correct"),
        (lambda s: s["lessons"][0]["steps"][7].update(template="kubectl get pod ___ ___"), "Each blank"),
        (lambda s: s["lessons"][0]["steps"][7].update(distractors=["ownerReferences"]), "unique"),
        (lambda s: s["lessons"][1]["steps"][8].update(answers=[40]), "non-empty lines"),
        (
            lambda s: s["lessons"][1]["steps"][7]["pairs"].__setitem__(4, ["Pod", "Something else"]),
            "distinct",
        ),
        (lambda s: s.update(topic="kubernetes/not-a-topic"), "library topic"),
        (lambda s: s["lessons"][0]["steps"][2].update(id=s["lessons"][0]["steps"][3]["id"]), "Step IDs"),
        (lambda s: s["lessons"][1].update(id="pods"), "Lesson IDs"),
        (
            lambda s: s["lessons"][0].update(
                steps=s["lessons"][0]["steps"][:1]
                + [{"type": "teach", "id": f"t{n}", "title": "T", "body": "B"} for n in range(4)]
            ),
            "three practice",
        ),
        (lambda s: s.update(references=["http://insecure.example"]), "references"),
    ],
)
def test_invalid_authored_content_is_rejected(change, message):
    source = json.loads(
        practice.DATA.joinpath("kubernetes-pods-deployments-and-replica-sets.json").read_text(
            encoding="utf-8"
        )
    )
    change(source)
    with pytest.raises(ValidationError) as error:
        practice.Unit.model_validate(source)
    assert message in str(error.value)


def test_every_library_topic_gets_lessons_without_ai():
    counts = practice.validate_all()
    assert counts["crafted"] == 1 and counts["derived"] == len(TOPICS) - 1 == 198
    for topic in TOPICS:
        if topic == FEATURED:
            continue
        core, apply = practice._derived(topic)
        guess, *rest = core.steps
        # A guess comes first: which step of the end-to-end flow happens first.
        assert guess.type == "choice" and guess.pretest and len(guess.options) == 3
        assert next(option.text for option in guess.options if option.correct) == apply.steps[1].steps[0]
        assert [step.type for step in rest].count("choice") == 4
        assert {"teach", "choice", "match"} <= {step.type for step in core.steps}
        assert {"order", "explain"} <= {step.type for step in apply.steps}
        assert (core.icon, apply.icon) == ("idea", "target")
        for lesson in (core, apply):
            for step in lesson.steps:
                assert practice.ITEM.fullmatch(f"{topic}|{lesson.id}|{step.id}")
                if step.type == "choice":
                    # The described idea is one of the four names offered, exactly once.
                    assert sum(option.correct for option in step.options) == 1


def test_sentence_and_term_helpers_never_cut_inside_code_or_bold():
    assert practice._gist("Use `a. B` here. Next sentence.") == "Use `a. B` here."
    assert practice._gist("**Rule. One** applies. Then more.") == "**Rule. One** applies."
    long = "word " * 90 + "end. Short."
    assert practice._gist(long) == long
    assert practice._term("Pod — one or more containers") == ("Pod", "one or more containers")
    assert practice._term("maxSurge / maxUnavailable — limits") == ("maxSurge / maxUnavailable", "limits")
    assert practice._term("CIDR: an address range") == ("CIDR", "an address range")
    assert practice._term("no separator here") is None


def test_views_carry_spans_and_blocks_never_html():
    view = practice.lesson(FEATURED, "pods")
    assert view["crafted"] and view["topic"]["title"] == "Kubernetes Pods, ReplicaSets and Deployments"
    assert [lesson["id"] for lesson in view["lessons"]] == [
        "pods",
        "replicasets",
        "rolling-updates",
        "rollback",
    ]
    steps = view["lesson"]["steps"]
    assert all(step["item"] == f"{FEATURED}|pods|{step['id']}" for step in steps)
    teach = next(step for step in steps if step["id"] == "what-is-a-pod")
    assert teach["visual"]["kind"] == "tree" and teach["body"][0]["type"] == "p"
    fill = next(step for step in steps if step["type"] == "fill")
    assert len(fill["parts"]) == len(fill["answer"]) + 1 and set(fill["answer"]) <= set(fill["tokens"])
    choice = next(step for step in steps if step["id"] == "localhost")
    assert text_of(next(o["text"] for o in choice["options"] if o["correct"])) == "localhost:8080"
    assert not any("<" in value and ">" in value and "</" in value for value in walk(view))
    assert practice.lesson(FEATURED, "missing") is None
    assert practice.lesson("../../etc/passwd", "pods") is None
    derived = next(topic for topic in TOPICS if topic.startswith("linux/"))
    assert practice.lesson(derived, "core")["provenance"].startswith("Built automatically")


def test_review_returns_only_known_practice_questions():
    items = [
        f"{FEATURED}|pods|localhost",
        f"{FEATURED}|pods|localhost",
        f"{FEATURED}|pods|what-is-a-pod",
        f"{FEATURED}|pods|guess-node-fails",
        f"{FEATURED}|pods|retired-step",
        "nope|pods|localhost",
        "../x|y|z",
        42,
        f"{FEATURED}|rollback|interview",
    ]
    steps = practice.review(items)
    assert [step["item"] for step in steps] == [
        f"{FEATURED}|pods|localhost",
        f"{FEATURED}|rollback|interview",
    ]
    assert all(step["topic"] == "Kubernetes Pods, ReplicaSets and Deployments" for step in steps)
    many = [f"{FEATURED}|{lesson.id}|{step.id}" for lesson in unit().lessons for step in lesson.steps]
    assert len(practice.review(many)) <= practice.REVIEW_LIMIT


def test_catalog_lists_every_topic_once_and_features_the_crafted_unit():
    data = practice.catalog()
    assert data["featured"] == FEATURED
    assert [module["id"] for module in data["modules"]] == [module.id for module in MODULES]
    topics = [topic for module in data["modules"] for topic in module["topics"]]
    assert [topic["id"] for topic in topics] == list(TOPICS)
    assert [topic["id"] for topic in topics if topic["crafted"]] == [FEATURED]
    assert all(topic["lessons"] and topic["title"] for topic in topics)
    assert {lesson["icon"] for topic in topics for lesson in topic["lessons"]} == {
        "pod",
        "replicaset",
        "rollout",
        "rollback",
        "idea",
        "target",
    }


# Routes -------------------------------------------------------------------------------------------


def test_practice_data_is_off_outside_web_mode(harness):
    client = create_app(harness.runtime).test_client()
    page = client.get("/web/practice", base_url=ORIGIN)
    assert page.status_code == 200 and b"/static/practice.js" in page.data
    assert page.headers["Cache-Control"] == "no-store, private"
    policy = page.headers["Content-Security-Policy"]
    assert (
        "script-src 'self';" in policy
        and "style-src 'self';" in policy
        and "frame-ancestors 'none'" in policy
    )
    for path in ("/web/practice/catalog", "/web/practice/lesson", "/web/practice/review"):
        response = client.post(path, base_url=ORIGIN, json={}, headers={"Origin": ORIGIN})
        assert response.status_code == 404 and response.json["enabled"] is False


@pytest.fixture
def web(pg_repo, config, monkeypatch):
    return build_web(pg_repo, config, monkeypatch)


def counts(web):
    with web.bot.repo.connection() as conn:
        return {
            table: conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
            for table in ("jobs", "outbox", "usage_daily", "telegram_receipts", "web_sessions")
        }


@pytest.mark.postgres
def test_practice_routes_need_the_session_and_change_nothing(web):
    assert post(web, "/web/practice/catalog", {}).status_code == 403
    sign_in(web, "learner@example.test")
    before = counts(web)
    catalog = post(web, "/web/practice/catalog", {})
    assert catalog.status_code == 200 and catalog.json["featured"] == FEATURED
    assert len(catalog.json["modules"]) == len(MODULES)
    key = catalog.json["progress_key"]
    assert re.fullmatch(r"[0-9a-f]{32}", key)
    assert post(web, "/web/practice/catalog", {}).json["progress_key"] == key
    lesson = post(web, "/web/practice/lesson", {"topic": FEATURED, "lesson": "pods"})
    assert lesson.status_code == 200 and lesson.json["lesson"]["steps"][0]["item"].startswith(FEATURED)
    review = post(web, "/web/practice/review", {"items": [f"{FEATURED}|pods|localhost", "bad|item|x"]})
    assert review.status_code == 200 and [s["item"] for s in review.json["steps"]] == [
        f"{FEATURED}|pods|localhost"
    ]
    # Malformed or unexpected requests are refused, and nothing in the database changed.
    assert post(web, "/web/practice/lesson", {"topic": FEATURED, "lesson": "nope"}).status_code == 404
    assert post(web, "/web/practice/lesson", {"topic": "../x", "lesson": "pods"}).status_code == 404
    assert post(web, "/web/practice/lesson", {"topic": 7, "lesson": "pods"}).status_code == 404
    assert post(web, "/web/practice/lesson", {"topic": FEATURED, "lesson": "pods", "x": 1}).status_code == 403
    assert post(web, "/web/practice/catalog", {"learner": "owner"}).status_code == 403
    assert post(web, "/web/practice/review", {"items": []}).status_code == 403
    assert post(web, "/web/practice/review", {"items": ["a|b|c"] * 21}).status_code == 403
    assert post(web, "/web/practice/review", {"items": [1]}).status_code == 403
    assert post(web, "/web/practice/catalog", {}, csrf=False).status_code == 403
    assert post(web, "/web/practice/catalog", {}, origin="https://evil.invalid").status_code == 403
    query = web.client.post(
        "/web/practice/catalog?learner=owner",
        base_url=ORIGIN,
        json={},
        headers={"Origin": ORIGIN, "X-CSRF-Token": web.csrf},
    )
    assert query.status_code == 403
    assert counts(web) == before
    # Another learner on the same browser gets a different progress key.
    owner = web.app.test_client()
    sign_in(web, "owner@example.test", client=owner)
    other = post(web, "/web/practice/catalog", {}, client=owner)
    assert other.status_code == 200 and other.json["progress_key"] != key
