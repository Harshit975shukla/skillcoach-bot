from datetime import date, datetime, timedelta

from test_flows import PROFILE, command, question_set
from test_journey import TOPIC, callback, shared_journey

from skillcoach.mastery import mastery_view
from skillcoach.models import Answer, Assessment, Profile, State
from skillcoach.progress import summary, today_view
from skillcoach.review import INTERVALS, backfill, due_cards
from skillcoach.timeutil import IST


def texts(h):
    return [text for text, _ in h.telegram.messages]


def quiz_with_answers(h, answers):
    """Deliver a catalog lesson, take its quiz with the given choices (B is correct)."""
    command(h, f"/learn {TOPIC}")
    key = max(h.repo.state.lessons, key=lambda k: h.repo.state.lessons[k].get("prepared_at", ""))
    h.repo.state.lessons[key]["delivered_at"] = h.clock.now.isoformat()
    ident = h.repo.state.lessons[key]["id"]
    h.ai.responses.append(question_set(5))
    callback(h, f"qnow:{ident}")
    session = h.repo.state.active_assessment
    for choice in answers:
        command(h, f"/q {choice}")
    return key, ident, session


def test_missed_questions_come_back_on_schedule_without_changing_quiz_scores(harness):
    h = harness
    _, _, quiz = quiz_with_answers(h, "AABBB")
    cards = h.repo.state.review
    assert sorted(c.box for c in cards.values()) == [0, 0, 2, 2, 2]
    assert {c.due for c in cards.values() if c.box == 0} == {date(2026, 9, 26)}
    assert {c.due for c in cards.values() if c.box == 2} == {date(2026, 10, 2)}
    command(h, "/review")
    assert "Nothing is due" in texts(h)[-1]
    h.clock.now = datetime(2026, 9, 26, 10, tzinfo=IST)
    assert len(due_cards(h.repo.state, h.clock.now)) == 2
    assert today_view(h.repo.state, h.clock.now)["next"]["callback"] == "review:start"
    command(h, "/review")
    review = h.repo.state.assessments[h.repo.state.active_assessment]
    assert review.kind == "review" and len(review.questions) == 2 and "Spaced review" in texts(h)[-1]
    command(h, "/q B")
    command(h, "/q A")
    assert "Review complete: 1/2 remembered" in texts(h)[-1]
    boxes = sorted((c.box, c.lapses) for c in h.repo.state.review.values() if c.reviews)
    assert boxes == [(0, 1), (1, 0)]
    moved = next(c for c in h.repo.state.review.values() if c.box == 1)
    assert moved.due == date(2026, 9, 26) + timedelta(days=INTERVALS[1])
    # Quiz evidence is unchanged; reviews are counted separately and have their own receipts.
    assert sum(a.correct for a in h.repo.state.assessments[quiz].answers) == 3
    stats = summary(h.repo.state, h.clock.now)
    assert stats["accuracy"] == 60 and stats["reviews_answered"] == 2 and stats["review_accuracy"] == 50
    assert stats["quizzes_completed"] == 1
    assert len(h.repo.answer_keys) == 7


def test_review_and_practice_never_replace_an_open_quiz(harness):
    h = harness
    _, _, quiz = quiz_with_answers(h, "AB")
    h.clock.now = datetime(2026, 9, 26, 10, tzinfo=IST)
    h.repo.state.assessments[quiz].date = date(2026, 9, 26)
    command(h, "/review")
    text, buttons = h.telegram.messages[-1]
    assert "Finish your current daily questions first (2/5 answered)" in text
    assert buttons == [[{"text": "Continue", "callback_data": f"resume:{quiz}"}]]
    callback(h, f"resume:{quiz}")
    assert "Daily question 3/5" in texts(h)[-1]
    assert h.repo.state.active_assessment == quiz


def test_practise_my_mistakes_uses_fresh_questions_once(harness):
    h = harness
    _, _, quiz = quiz_with_answers(h, "AABBB")
    final, buttons = h.telegram.messages[-1]
    assert buttons[0] == [{"text": "🧩 Practise my mistakes", "callback_data": f"practice:{quiz}"}]
    repeated = question_set(2)
    repeated["questions"][0]["question"] = "Question 0?"
    h.ai.responses.append(repeated)
    job = callback(h, f"practice:{quiz}")
    assert h.repo.jobs[job]["status"] == "failed" and h.repo.state.active_assessment is None
    fresh = question_set(2)
    for i, item in enumerate(fresh["questions"]):
        item["question"] = f"Scenario variant {i}?"
    h.ai.responses.append(fresh)
    callback(h, f"practice:{quiz}")
    practice = h.repo.state.assessments[h.repo.state.active_assessment]
    assert practice.kind == "practice" and practice.source == quiz and len(practice.questions) == 2
    command(h, "/q B")
    command(h, "/q B")
    assert "Practice complete: 2/2 correct" in texts(h)[-1]
    assert sum(a.correct for a in h.repo.state.assessments[quiz].answers) == 3
    callback(h, f"practice:{quiz}")
    assert "already practised" in texts(h)[-1]
    # Practice answers never create review cards or change quiz metrics.
    assert len(h.repo.state.review) == 5 and summary(h.repo.state, h.clock.now)["accuracy"] == 60


def test_weekly_mistakes_are_reviewed_but_correct_weekly_answers_are_not(harness):
    h = harness
    h.repo.state.profile = Profile(**PROFILE)
    h.repo.state.lessons["x"] = {"topic": "IAM", "date": "2026-09-25", "delivered_at": "2026-09-25"}
    h.clock.now = datetime(2026, 9, 26, 9, tzinfo=IST)
    h.ai.responses.append(question_set(10))
    h.repo.enqueue("weekly", {"type": "schedule", "kind": "weekly", "date": "2026-09-26"})
    h.runtime.recover(media=False)
    for choice in "ABBBBBBBBB":
        command(h, f"/q {choice}")
    assert [c.box for c in h.repo.state.review.values()] == [0]
    assert "try /interview" in texts(h)[-1]


def test_i_understand_offers_an_immediate_check(harness):
    h = harness
    journey = shared_journey(h.clock.now)
    day = journey.plans["plan-test"].sessions[0]
    day.lesson_key = "lesson:0"
    h.repo.state.lessons["lesson:0"] = {
        "topic": "x",
        "date": day.date.isoformat(),
        "delivered_at": h.clock.now.isoformat(),
        "id": "a" * 20,
    }
    h.repo.state.journey = journey
    callback(h, "understand:plan-test:0")
    text, buttons = h.telegram.messages[-1]
    assert "Understanding recorded" in text and buttons == [
        [{"text": "📝 Check myself now", "callback_data": "qnow:" + "a" * 20}]
    ]
    assert h.repo.state.journey.plans["plan-test"].sessions[0].understood_at


def test_roadmap_states_follow_evidence_not_exposure(harness):
    h = harness
    view = mastery_view(h.repo.state, h.clock.now)
    assert view["summary"]["started"] == 0 and view["next"]["id"]
    quiz_with_answers(h, "AAABB")
    view = mastery_view(h.repo.state, h.clock.now)
    assert view["states"][TOPIC]["state"] == "needs_review" and view["next"]["id"] == TOPIC
    assert view["summary"] == {"total": view["summary"]["total"], "started": 1, "solid": 0, "needs_review": 1}
    # Remembering questions after spaced gaps moves the topic to solid; a quiz alone never does.
    for card in h.repo.state.review.values():
        card.box, card.due = 3, date(2026, 12, 1)
    for session in h.repo.state.assessments.values():
        for answer in session.answers:
            answer.correct = True
    view = mastery_view(h.repo.state, h.clock.now)
    assert view["states"][TOPIC] == {"state": "solid", "label": "Solid"}
    assert view["next"]["reason"] == "Next on your roadmap" and view["next"]["id"] != TOPIC


def test_answers_from_before_spaced_review_are_backfilled_once_with_their_real_spacing(harness):
    h = harness
    old = Assessment(
        id="old-quiz",
        kind="daily",
        date=date(2026, 9, 22),
        week="2026-W39",
        status="completed",
        questions=question_set(5)["questions"],
        question_ids=[f"q{i}" for i in range(5)],
        answers=[
            Answer(
                question_id=f"q{i}",
                given=g,
                correct=g == "B",
                created_at=datetime(2026, 9, 23, 1, 30, tzinfo=IST),
            )
            for i, g in enumerate("ABBBA")
        ],
    )
    h.repo.state.assessments[old.id] = old
    h.repo.state.review_backfilled = False
    before = h.repo.state.model_dump(mode="json")
    command(h, "/progress")
    command(h, "/resources")
    assert h.repo.state.model_dump(mode="json") == before  # Browsing never migrates or mutates.
    h.repo.enqueue("quiz-1800", {"type": "schedule", "kind": "quiz", "date": "2026-09-25"})
    h.runtime.recover(media=False)
    state = h.repo.state
    assert state.review_backfilled and len(state.review) == 5
    # Answered at 01:30 on 23 Sep, which is study day 22 Sep: misses were due 23 Sep, correct ones 29 Sep.
    assert sorted((c.box, c.due) for c in state.review.values()) == [
        (0, date(2026, 9, 23)),
        (0, date(2026, 9, 23)),
        (2, date(2026, 9, 29)),
        (2, date(2026, 9, 29)),
        (2, date(2026, 9, 29)),
    ]
    assert len(due_cards(state, h.clock.now)) == 2  # 25 Sep: only the two misses are due.
    assert today_view(state, h.clock.now)["next"]["kind"] == "review"
    h.clock.now = datetime(2026, 9, 30, 12, tzinfo=IST)
    assert len(due_cards(state, h.clock.now)) == 5
    before = {k: v.model_copy() for k, v in state.review.items()}
    backfill(state)
    assert state.review == before
    # Once marked, later jobs never re-seed cards that a learner already reviewed.
    command(h, "/review")
    for _ in range(5):
        command(h, "/q B")
    assert all(c.reviews == 1 for c in h.repo.state.review.values())
    command(h, "/progress")
    assert all(c.reviews == 1 for c in h.repo.state.review.values())


def test_new_state_marks_backfill_pending_for_existing_learners():
    assert State().review_backfilled is False
