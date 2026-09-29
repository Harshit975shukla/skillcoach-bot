from datetime import date, datetime, timedelta, timezone

import pytest
from test_flows import command, question_set

from skillcoach.clients import ExternalError
from skillcoach.export import public_export
from skillcoach.quizzes import catalogue, deadline
from skillcoach.timeutil import IST


def delivered(state, day="2026-09-24", topic="Terraform"):
    state.lessons[day] = {"date": day, "topic": topic, "delivered_at": day + "T04:00:00+00:00"}


def start(h):
    delivered(h.repo.state)
    h.ai.responses.append(question_set(5))
    command(h, "/quiz 2026-09-24")
    return h.repo.state.active_assessment


def test_missed_quiz_created_once_and_date_link_remains_valid(harness):
    h = harness
    ident = start(h)
    session = h.repo.state.assessments[ident]
    assert len(session.questions) == 5 and session.date == date(2026, 9, 24)
    command(h, "/q B")
    command(h, "/start quiz_2026-09-24")
    assert h.repo.state.active_assessment == ident
    assert len(h.repo.state.assessments[ident].answers) == 1
    assert len(h.ai.calls) == len(h.repo.state.assessments) == len(h.repo.answer_keys) == 1
    assert "question 2/5" in h.telegram.messages[-1][0]


def test_midnight_no_longer_expires_daily_and_sunday_boundary_is_exact(harness):
    h = harness
    ident = start(h)
    h.clock.now = datetime(2026, 9, 26, 0, 1, tzinfo=IST)
    command(h, "/q B")
    assert len(h.repo.state.assessments[ident].answers) == 1
    assert deadline(date(2026, 9, 24)) == datetime(2026, 9, 28, tzinfo=IST)
    h.clock.now = datetime(2026, 9, 27, 18, 29, 59, tzinfo=timezone.utc)
    command(h, "/q B")
    assert len(h.repo.state.assessments[ident].answers) == 2
    h.clock.now += timedelta(seconds=1)
    command(h, "/q B")
    assert h.repo.state.assessments[ident].status == "expired"
    assert len(h.repo.answer_keys) == 2
    command(h, "/quiz " + ident)
    assert h.repo.state.active_assessment is None
    assert "deadline has passed" in h.telegram.messages[-1][0]


def test_resume_preserves_answers_and_does_not_replace_another_assessment(harness):
    h = harness
    first = start(h)
    command(h, "/q B")
    original = h.repo.state.assessments[first].model_copy(deep=True)
    command(h, "/cancel")
    delivered(h.repo.state, "2026-09-25", "CI")
    h.ai.responses.append(question_set(5))
    command(h, "/quiz 2026-09-25")
    second = h.repo.state.active_assessment
    command(h, "/quiz " + first)
    assert h.repo.state.active_assessment == second
    assert h.repo.state.assessments[first].answers == original.answers
    assert "Finish the current assessment first" in h.telegram.messages[-1][0]
    for _ in range(5):
        command(h, "/q B")
    command(h, "/quiz " + first)
    assert h.repo.state.active_assessment == first
    assert h.repo.state.assessments[first].question_ids == original.question_ids
    assert h.repo.state.assessments[first].date == original.date
    for _ in range(4):
        command(h, "/q B")
    assert len(h.repo.answer_keys) == 10
    before = h.repo.state.assessments[first].model_copy(deep=True)
    command(h, "/quiz " + first)
    assert h.repo.state.assessments[first] == before
    assert "already completed" in h.telegram.messages[-1][0]


def test_saturday_assessment_takes_priority_but_daily_can_resume_afterwards(harness):
    h = harness
    daily = start(h)
    target = h.repo.state.target()
    h.clock.now = datetime(2026, 9, 26, 9, tzinfo=IST)
    h.ai.responses.append(question_set(10))
    h.repo.enqueue("weekly", {"type": "schedule", "kind": "weekly", "date": "2026-09-26"})
    # Legacy scheduled weekly generation requires a configured profile.
    from test_flows import PROFILE

    from skillcoach.models import Profile

    h.repo.state.profile = Profile(**PROFILE)
    h.runtime.recover(media=False)
    weekly = h.repo.state.active_assessment
    assert weekly != daily and len(h.repo.state.assessments[weekly].questions) == 10
    h.repo.enqueue("stale", {"type": "telegram", "callback": f"q:{daily}:{target['question']}:B"})
    h.runtime.recover(media=False)
    assert not h.repo.state.assessments[weekly].answers
    command(h, "/quiz " + daily)
    assert h.repo.state.active_assessment == weekly
    for _ in range(10):
        command(h, "/q B")
    command(h, "/quiz " + daily)
    assert h.repo.state.active_assessment == daily
    assert len(h.ai.calls) == 2


@pytest.mark.parametrize("identifier", ["2026-09-23", "2026-09-31", "f" * 20, "<script>"])
def test_unknown_or_foreign_quiz_does_not_change_state_or_use_ai(harness, identifier):
    command(harness, "/quiz " + identifier)
    assert not harness.repo.state.assessments and not harness.ai.calls


def test_undelivered_and_future_lessons_are_not_available(harness):
    h = harness
    h.repo.state.lessons["not-sent"] = {"date": "2026-09-25", "topic": "Unsent"}
    delivered(h.repo.state, "2026-09-26", "Future")
    command(h, "/quizzes")
    assert "No unfinished" in h.telegram.messages[-1][0]
    command(h, "/quiz 2026-09-25")
    assert not h.ai.calls


def test_catalogue_does_not_expose_questions_keys_or_publish_private_topics(harness):
    h = harness
    delivered(h.repo.state, topic="PRIVATE-QUIZ-TOPIC")
    h.ai.responses.append(question_set(5))
    command(h, "/quiz 2026-09-24")
    entry = catalogue(h.repo.state, h.clock.now)[0]
    assert entry["can_resume"] and entry["score"] is None
    assert set(entry) == {
        "id",
        "date",
        "title",
        "status",
        "answered",
        "total",
        "score",
        "can_resume",
        "deadline",
    }
    assert "PRIVATE-QUIZ-TOPIC" not in str(public_export(h.repo.state, h.clock.now))
    command(h, "/quizzes")
    assert h.telegram.messages[-1][1][0][0]["callback_data"] == "quiz:" + entry["id"]


@pytest.mark.parametrize("count", [4, 6, 10])
def test_missing_quiz_still_requires_exactly_five_questions(harness, count):
    delivered(harness.repo.state)
    harness.ai.responses.append(question_set(count))
    key = command(harness, "/quiz 2026-09-24")
    assert harness.repo.jobs[key]["status"] == "failed"
    assert not harness.repo.state.assessments


def test_failed_generation_and_delivery_retry_reuses_saved_questions(harness):
    h = harness
    delivered(h.repo.state)
    h.ai.responses.append(ExternalError("temporary_ai_failure"))
    key = command(h, "/quiz 2026-09-24")
    assert h.repo.jobs[key]["status"] == "failed"
    h.ai.responses.append(question_set(5))
    h.telegram.fail = True
    command(h, "/retry")
    ident = h.repo.state.active_assessment
    h.telegram.fail = False
    command(h, "/retry")
    assert len(h.ai.calls) == 2 and h.repo.state.active_assessment == ident
    assert len(h.repo.state.assessments) == 1


@pytest.mark.postgres
def test_catchup_recipient_isolation_durable_answers_and_dashboard(pg_repo, config):
    import time
    from concurrent.futures import ThreadPoolExecutor

    from test_dashboard import signed
    from test_multiuser import Bot

    from skillcoach.web import create_app

    bot = Bot(pg_repo, config)
    a, b = bot.join(101), bot.join(102)
    bot.save(a, lambda state: delivered(state, topic="ONLY-A"))
    bot.save(b, lambda state: delivered(state, topic="ONLY-B"))
    bot.runtime.ai.responses.append(question_set(5))
    bot.input(101, "/quiz 2026-09-24")
    session = a.read()[1].assessments[a.read()[1].active_assessment]
    bot.input(102, callback="quiz:" + session.id)
    assert not b.read()[1].assessments
    callback = f"q:{session.id}:{session.question_ids[0]}:B"
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda i: bot.input(101, callback=callback, drain=False, update_id=i), [5000, 5001]))
    bot.runtime.recover(media=False)
    bot.input(101, "/cancel")
    bot.input(101, "/start quiz_" + session.id)
    resumed = a.read()[1].assessments[session.id]
    assert len(resumed.answers) == 1 and resumed.question_ids == session.question_ids
    with pg_repo.connection() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM answer_keys WHERE learner_id=%s", (a.learner_id,)
            ).fetchone()["n"]
            == 1
        )
    bot.runtime.clock = lambda: datetime.now(IST)
    client = create_app(bot.runtime).test_client()
    response = client.post(
        "/app/data", json={"init_data": signed(101, config.telegram_token, int(time.time()) + 2)}
    )
    assert response.status_code == 200
    assert response.json["quizzes"][0]["title"] == "ONLY-A"
    assert "ONLY-B" not in response.get_data(as_text=True)
    assert "Question 0?" not in str(response.json["quizzes"])
