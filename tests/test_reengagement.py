import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from test_dashboard import signed
from test_flows import PROFILE, command, question_set
from test_journey import callback

from skillcoach.adoption import action_of, weekday_gap
from skillcoach.catalog import TOPICS
from skillcoach.cli import schedule
from skillcoach.models import Profile
from skillcoach.reengage import ENCOURAGEMENTS, idle_days
from skillcoach.timeutil import IST


def texts(h):
    return [text for text, _ in h.telegram.messages]


def delivered_learner(h, *, last_study):
    h.repo.state.profile = Profile(**PROFILE)
    h.repo.state.lessons["x"] = {"topic": "IAM", "date": "2026-09-21", "delivered_at": "2026-09-21"}
    h.repo.state.activity = [last_study]


def quiz_slot(h, day):
    h.clock.now = datetime.combine(day, datetime.min.time(), IST).replace(hour=18)
    h.repo.enqueue(f"quiz:{day}", {"type": "schedule", "kind": "quiz", "date": day.isoformat()})
    h.runtime.recover(media=False)


def test_idle_days_skip_sundays_and_start_after_the_first_lesson():
    assert weekday_gap(date(2026, 9, 25), date(2026, 9, 28)) == 1  # Saturday only; Sunday rests.
    assert weekday_gap(date(2026, 9, 28), date(2026, 9, 29)) == 0
    from skillcoach.models import State

    state = State()
    assert idle_days(state, datetime(2026, 9, 30, 18, tzinfo=IST)) == 0
    state.lessons["x"] = {"topic": "x", "date": "2026-09-28", "delivered_at": "2026-09-28"}
    assert idle_days(state, datetime(2026, 9, 30, 18, tzinfo=IST)) == 2
    state.resumed_at = datetime(2026, 9, 30, 10, tzinfo=IST)  # Coaching switched back on today.
    assert idle_days(state, datetime(2026, 9, 30, 18, tzinfo=IST)) == 0
    assert idle_days(state, datetime(2026, 10, 2, 18, tzinfo=IST)) == 2


def test_gentle_nudge_after_two_missed_days_is_rate_limited(harness):
    h = harness
    delivered_learner(h, last_study=date(2026, 9, 22))
    quiz_slot(h, date(2026, 9, 23))
    assert not any("Haven't seen you" in text for text in texts(h))
    quiz_slot(h, date(2026, 9, 25))
    nudge, buttons = h.telegram.messages[-1]
    assert "Haven't seen you for a couple of days" in nudge
    assert buttons[-1] == [{"text": "📅 Today", "callback_data": "home:today"}]
    assert h.repo.state.nudged_at is not None
    count = len(h.telegram.messages)
    h.clock.now += timedelta(hours=2)
    h.repo.enqueue("quiz-rerun", {"type": "schedule", "kind": "quiz", "date": "2026-09-25"})
    h.runtime.recover(media=False)
    assert not any("Haven't seen you" in text for text in texts(h)[count:])
    # Studying resets the idle count: no nudge the next time.
    h.clock.now = datetime(2026, 9, 28, 9, tzinfo=IST)
    h.repo.state.activity.append(date(2026, 9, 28))
    quiz_slot(h, date(2026, 9, 29))
    assert not any("Haven't seen you" in text for text in texts(h)[count:])


def test_pace_offer_after_five_missed_days_and_each_reply(harness):
    h = harness
    delivered_learner(h, last_study=date(2026, 9, 21))
    quiz_slot(h, date(2026, 9, 28))
    text, buttons = h.telegram.messages[-1]
    assert "Life gets busy" in text
    assert [row[0]["callback_data"] for row in buttons] == ["nudge:light", "nudge:pause7", "nudge:keep"]
    callback(h, "nudge:keep")
    assert "your plan stays" in texts(h)[-1]
    callback(h, "nudge:light")
    assert h.repo.state.preference.startswith("Lighter pace")
    callback(h, "nudge:pause7")
    state = h.repo.state
    assert state.paused and state.pause_until == datetime(2026, 10, 5, 4, tzinfo=IST)
    assert "Paused until Mon 05 Oct" in texts(h)[-1]
    callback(h, "nudge:bogus")
    assert "Unsupported" in texts(h)[-1]


def test_week_long_pause_resumes_itself_but_manual_pause_does_not(harness):
    h = harness
    delivered_learner(h, last_study=date(2026, 9, 28))
    h.clock.now = datetime(2026, 9, 28, 18, tzinfo=IST)
    callback(h, "nudge:pause7")
    h.clock.now = datetime(2026, 10, 2, 9, tzinfo=IST)
    schedule(h.runtime, "lesson", date(2026, 10, 2), media=False)
    assert h.repo.state.paused  # Still inside the pause.
    h.clock.now = datetime(2026, 10, 5, 9, tzinfo=IST)
    week = {(date(2026, 10, 5) + timedelta(days=i)).isoformat(): "IAM" for i in range(6)}
    h.ai.responses.append({"days": week, "rationale": "Revise IAM after the break."})
    schedule(h.runtime, "lesson", date(2026, 10, 5), media=False)
    assert not h.repo.state.paused and h.repo.state.pause_until is None
    assert any(key.startswith("2026-10-05") for key in h.repo.state.lessons)  # That morning's lesson arrives.
    assert any("Your pause has ended" in text for text in texts(h))
    command(h, "/pause")
    assert h.repo.state.paused and h.repo.state.pause_until is None
    h.clock.now = datetime(2026, 10, 12, 9, tzinfo=IST)
    schedule(h.runtime, "lesson", date(2026, 10, 12), media=False)
    assert h.repo.state.paused


def test_paused_days_never_count_as_missed_days(harness):
    def reengaged(start):
        return [t for t in texts(h)[start:] if "Haven't seen you" in t or "Life gets busy" in t]

    h = harness
    delivered_learner(h, last_study=date(2026, 9, 21))
    quiz_slot(h, date(2026, 9, 28))  # Pace offer after five missed days.
    callback(h, "nudge:pause7")
    h.clock.now = datetime(2026, 10, 5, 9, tzinfo=IST)
    week = {(date(2026, 10, 5) + timedelta(days=i)).isoformat(): "IAM" for i in range(6)}
    h.ai.responses.append({"days": week, "rationale": "Revise IAM after the break."})
    schedule(h.runtime, "lesson", date(2026, 10, 5), media=False)
    assert not h.repo.state.paused and h.repo.state.resumed_at == h.clock.now
    count = len(h.telegram.messages)
    h.ai.responses.append(question_set(5))
    quiz_slot(h, date(2026, 10, 5))  # Welcomed back this morning: no nudge the same evening.
    assert h.repo.state.active_assessment and not reengaged(count)
    assert idle_days(h.repo.state, h.clock.now) == 0
    quiz_slot(h, date(2026, 10, 7))  # Two scheduled days missed since coming back.
    assert "Haven't seen you" in texts(h)[-1]

    # A manual pause: /unpause in the morning is not followed by a pace offer that evening.
    command(h, "/pause")
    h.clock.now = datetime(2026, 10, 26, 10, tzinfo=IST)
    command(h, "/unpause")
    assert h.repo.state.resumed_at == h.clock.now
    count = len(h.telegram.messages)
    quiz_slot(h, date(2026, 10, 26))
    assert not reengaged(count) and idle_days(h.repo.state, h.clock.now) == 0
    # /unpause while not paused cannot reset the missed-day count.
    command(h, "/unpause")
    assert h.repo.state.resumed_at == datetime(2026, 10, 26, 10, tzinfo=IST)


def test_feature_keys_never_include_arguments_or_typed_text():
    assert action_of({"type": "telegram", "text": "/ask what is my secret project?"}) == "/ask"
    assert action_of({"type": "telegram", "text": "My private answer"}) is None
    assert action_of({"type": "telegram", "callback": "ex:0123456789abcdef0123:done"}) == "button:ex"
    assert action_of({"type": "exercise", "task_id": "x", "action": "done"}) == "exercise"
    assert action_of({"type": "schedule", "kind": "quiz"}) is None


@pytest.mark.postgres
def test_adoption_funnel_risk_counters_and_encouragement_are_private_and_scoped(pg_repo, config):
    from test_admin import confirm, login, post, preview
    from test_multiuser import Bot

    from skillcoach.web import create_app

    bot = Bot(pg_repo, config)
    now = datetime.now(timezone.utc)
    bot.runtime.clock = lambda: now
    active, quiet = bot.join(101), bot.join(102)
    bot.join(103, approve=False)

    def studied(state):
        state.profile = Profile(**PROFILE)
        state.lessons["l"] = {
            "topic": "IAM",
            "date": (now - timedelta(days=9)).date().isoformat(),
            "delivered_at": "x",
        }
        state.activity = [(now - timedelta(days=d)).astimezone(IST).date() for d in (9, 8, 7)]

    bot.save(active, studied)
    bot.input(101, "/ask PRIVATE-QUESTION-TEXT", drain=False)
    client = create_app(bot.runtime).test_client()
    launch = signed(101, config.telegram_token, int(now.timestamp()))
    for _ in range(3):  # Refreshes of one launch count once.
        assert client.post("/app/data", json={"init_data": launch}).status_code == 200
    second = signed(101, config.telegram_token, int(now.timestamp()) - 1)
    assert client.post("/app/data", json={"init_data": second}).status_code == 200
    topic = next(iter(TOPICS))
    assert client.post("/app/course", json={"init_data": launch, "topic": topic}).status_code == 200
    with pg_repo.connection() as conn:
        counts = {
            r["event"]: r["count"]
            for r in conn.execute(
                "SELECT event,count FROM usage_daily WHERE learner_id=%s", (active.learner_id,)
            )
        }
    assert counts == {"dashboard_open": 2, "course_page": 1}

    admin = SimpleNamespace(bot=bot, client=client, csrf=None, clock=SimpleNamespace(now=now))
    assert login(admin).status_code == 200
    data = post(admin, "/admin/adoption").json
    encoded = json.dumps(data)
    assert "PRIVATE-QUESTION-TEXT" not in encoded
    funnel = {row["stage"]: row["count"] for row in data["funnel"]}
    assert funnel["Joined or requested access"] == 4 and funnel["Approved"] == 3
    assert funnel["First lesson received"] == 1 and funnel["3+ study days in first week"] == 1
    features = {row["feature"]: row for row in data["features"]}
    assert features["Dashboard opens"]["uses"] == 2 and features["AI tutor"]["learners"] == 1
    assert features["Library lesson opens"]["uses"] == 1
    risk = {row["id"]: row for row in data["at_risk"]}
    assert active.learner_id in risk and risk[active.learner_id]["idle_days"] >= 2
    assert quiet.learner_id not in risk  # Nothing delivered yet, so nothing to come back to.

    body = preview(admin, "encourage", active.learner_id, {"message": "checkin"}).json
    assert ENCOURAGEMENTS["checkin"] in body["preview"]["details"]
    assert confirm(admin, body).json["state"] == "queued"
    bot.runtime.recover(media=False)
    received = bot.runtime.telegram.chat_messages[101][-1]
    assert received[0] == ENCOURAGEMENTS["checkin"] and received[1][-1][0]["callback_data"] == "home:today"
    assert preview(admin, "encourage", active.learner_id, {"message": "checkin"}).status_code == 409
    assert preview(admin, "encourage", quiet.learner_id, {"message": "made-up"}).status_code == 403
    bot.input(102, "/pause")
    assert preview(admin, "encourage", quiet.learner_id, {"message": "goal"}).status_code == 409
    assert post(admin, "/admin/adoption", origin="https://evil.invalid").status_code == 403
