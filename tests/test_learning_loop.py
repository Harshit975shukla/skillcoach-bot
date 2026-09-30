import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from test_dashboard import signed
from test_flows import PROFILE, command, question_set
from test_journey import callback, core_guide, proposal, shared_journey

from skillcoach.cli import MENU, alert_late, configure_telegram
from skillcoach.clients import Budget, Telegram
from skillcoach.commands import COMMANDS, GROUPS, help_text
from skillcoach.dashboard import LEARNER_AUTH_AGE, DashboardDenied, verify_init_data
from skillcoach.models import Profile, State, Task
from skillcoach.progress import recap_text, summary, today_view
from skillcoach.runtime import silent_delivery
from skillcoach.timeutil import IST


def deliver_lesson(h, topic="EC2"):
    command(h, f"/learn {topic}")
    key = max(h.repo.state.lessons, key=lambda k: h.repo.state.lessons[k].get("prepared_at", ""))
    h.repo.state.lessons[key]["delivered_at"] = h.clock.now.isoformat()
    return key, h.repo.state.lessons[key]["id"]


def texts(h):
    return [text for text, _ in h.telegram.messages]


def test_only_the_first_message_of_each_reply_rings_and_quiet_hours_are_silent(harness):
    h = harness
    h.ai.responses.append({"text": "A" * 5000})
    command(h, "/ask what is a VPC endpoint?")
    assert h.telegram.silent[-2:] == [False, True]
    h.clock.now = datetime(2026, 9, 25, 23, 30, tzinfo=IST)
    h.ai.responses.append({"text": "Short answer."})
    command(h, "/ask why?")
    assert h.telegram.silent[-1] is True
    morning = datetime(2026, 9, 25, 9, tzinfo=IST)
    assert silent_delivery("job:0", State(), morning) is False
    assert silent_delivery("job:3", State(), morning) is True
    assert silent_delivery("job:preparing", State(), datetime(2026, 9, 25, 6, 59, tzinfo=IST)) is True
    assert silent_delivery("job:failure", State(), morning) is False


def test_telegram_client_sends_silent_flag_and_omits_chat_for_bot_settings(config):
    class FakeHTTP:
        def __init__(self):
            self.payloads = []

        def call(self, method, url, **kwargs):
            self.payloads.append((url.rsplit("/", 1)[1], kwargs.get("json")))
            return 200, {"ok": True, "result": True}

    http = FakeHTTP()
    telegram = Telegram(config, http)
    telegram.send("quiet", Budget(), silent=True)
    telegram.send("loud", Budget())
    telegram.call("setMyCommands", Budget(), data={"commands": []})
    assert http.payloads[0][1]["disable_notification"] is True
    assert "disable_notification" not in http.payloads[1][1]
    assert http.payloads[2] == ("setMyCommands", {"commands": []})


def test_quiz_feedback_and_next_question_arrive_together_then_lesson_fit_is_asked(harness):
    h = harness
    key, ident = deliver_lesson(h)
    h.ai.responses.append(question_set(5))
    h.repo.enqueue("quiz:today", {"type": "schedule", "kind": "quiz", "date": "2026-09-25"})
    h.runtime.recover(media=False)
    before = len(h.telegram.messages)
    command(h, "/q B")
    assert len(h.telegram.messages) == before + 1
    text = h.telegram.messages[-1][0]
    assert text.startswith("Correct.") and "Explanation 0." in text and "question 2/5" in text
    for _ in range(4):
        command(h, "/q B")
    final, buttons = h.telegram.messages[-1]
    assert "Daily assessment complete: 5/5" in final and "How was this lesson?" in final
    assert [b["callback_data"] for row in buttons for b in row] == [
        f"lf:{ident}:up",
        f"lf:{ident}:r:confusing",
        f"lf:{ident}:r:easy",
        f"lf:{ident}:r:hard",
    ]
    callback(h, f"lf:{ident}:r:hard")
    assert h.repo.state.lessons[key]["feedback"]["reports"] == ["hard"]
    assert "next plan proposal" in texts(h)[-1]
    assert len(h.repo.answer_keys) == 5


def test_one_tap_exercises_record_done_skip_time_and_progressive_hints(harness):
    h = harness
    command(h, "/learn EC2")
    ids = list(h.repo.state.tasks)
    body = next(
        row["body"] for row in h.repo.outbox.values() if "Today's exercises" in row["body"].get("text", "")
    )
    assert [b["callback_data"] for b in body["buttons"][0]] == [
        f"ex:{ids[0]}:done",
        f"ex:{ids[0]}:skip",
        f"ex:{ids[0]}:stuck",
    ]
    callback(h, f"ex:{ids[0]}:done")
    task = h.repo.state.tasks[ids[0]]
    assert task.status == "done" and task.completed_at and date(2026, 9, 25) in h.repo.state.activity
    text, buttons = h.telegram.messages[-1]
    assert "2 more from this lesson" in text and buttons[0][1]["callback_data"] == f"ex:{ids[0]}:m20"
    callback(h, f"ex:{ids[0]}:m20")
    callback(h, f"ex:{ids[0]}:m45")
    assert h.repo.state.tasks[ids[0]].actual_minutes == 20
    callback(h, f"ex:{ids[0]}:done")
    assert "already recorded as done" in texts(h)[-1]
    callback(h, f"ex:{ids[1]}:skip")
    assert h.repo.state.tasks[ids[1]].status == "skipped"
    h.ai.responses.append({"hints": ["First nudge.", "More specific.", "1. Do this\n2. Then that"]})
    for expected in ("Hint 1", "Hint 2", "Solution outline", "Solution outline"):
        callback(h, f"ex:{ids[2]}:stuck")
        assert expected in texts(h)[-1]
    assert len(h.ai.calls) == 1 and h.repo.state.tasks[ids[2]].hint_level == 3
    assert h.repo.state.tasks[ids[2]].status == "pending"
    callback(h, "ex:" + "f" * 20 + ":done")
    assert "no longer available" in texts(h)[-1]
    callback(h, f"ex:{ids[2]}:m999")
    assert "Unsupported" in texts(h)[-1]
    progress = summary(h.repo.state, h.clock.now)
    assert progress["exercises_done"] == 1 and progress["exercises_skipped"] == 1


def test_quiz_me_now_starts_once_and_the_scheduled_quiz_only_reminds(harness):
    h = harness
    command(h, "/learn EC2")
    key = next(iter(h.repo.state.lessons))
    ident = h.repo.state.lessons[key]["id"]
    callback(h, f"qnow:{ident}")
    assert "Wait until the full lesson has arrived" in texts(h)[-1] and not h.ai.calls
    h.repo.state.lessons[key]["delivered_at"] = h.clock.now.isoformat()
    h.ai.responses.append(question_set(5))
    callback(h, f"qnow:{ident}")
    session = h.repo.state.assessments[h.repo.state.active_assessment]
    assert session.date == date(2026, 9, 25) and len(session.questions) == 5
    command(h, "/q B")
    h.repo.enqueue("quiz:1800", {"type": "schedule", "kind": "quiz", "date": "2026-09-25"})
    h.runtime.recover(media=False)
    assert len(h.ai.calls) == 1
    text, buttons = h.telegram.messages[-1]
    assert "waiting: 1/5 answered" in text
    assert buttons == [[{"text": "Continue quiz", "callback_data": f"quiz:{session.id}"}]]
    for _ in range(4):
        command(h, "/q B")
    count = len(h.telegram.messages)
    h.repo.enqueue("quiz:rerun", {"type": "schedule", "kind": "quiz", "date": "2026-09-25"})
    h.runtime.recover(media=False)
    assert len(h.telegram.messages) == count and len(h.ai.calls) == 1
    callback(h, f"qnow:{ident}")
    assert "already completed" in texts(h)[-1]


def test_explain_it_differently_is_generated_once_and_kept_out_of_ai_context(harness):
    h = harness
    key, ident = deliver_lesson(h)
    h.ai.responses.append({"text": "Think of it like renting a flat."})
    callback(h, f"explain:{ident}")
    assert "renting a flat" in texts(h)[-1]
    callback(h, f"explain:{ident}")
    assert len(h.ai.calls) == 1 and h.repo.state.lessons[key]["alt_explanation"]
    assert date(2026, 9, 25) in h.repo.state.activity
    h.ai.responses.append({"text": "Answer."})
    command(h, "/ask what next?")
    assert "renting a flat" not in h.ai.calls[-1][0]


def test_home_today_progress_and_one_tap_ask(harness):
    h = harness
    command(h, "/start")
    text, buttons = h.telegram.messages[-1]
    assert "Welcome to SkillCoach" in text and buttons[0][0]["callback_data"] == "onboard:start"
    h.repo.state.profile = Profile(**PROFILE)
    deliver_lesson(h)
    command(h, "/menu")
    text, buttons = h.telegram.messages[-1]
    data = {b.get("callback_data") for row in buttons for b in row}
    assert text.startswith("🏠 SkillCoach") and "Next:" in text
    assert {"home:today", "home:quizzes", "home:progress", "home:ask", "home:help"} <= data
    callback(h, "home:today")
    text, buttons = h.telegram.messages[-1]
    assert "Exercises (tap when done)" in text and "Quiz me now" in json.dumps(buttons, ensure_ascii=False)
    assert any(b.get("callback_data", "").startswith("ex:") for row in buttons for b in row)
    callback(h, "home:progress")
    assert texts(h)[-1].startswith("📈 Your progress")
    callback(h, "home:ask")
    assert h.repo.state.focus == "ask"
    h.ai.responses.append({"text": "A VPC endpoint keeps traffic private."})
    command(h, "What is a VPC endpoint?")
    assert "keeps traffic private" in texts(h)[-1] and h.repo.state.focus is None
    callback(h, "home:ask")
    command(h, "/progress")
    assert h.repo.state.focus is None and texts(h)[-1].startswith("📈 Your progress")
    callback(h, "home:help")
    assert "EVERY DAY" in texts(h)[-1]


def test_late_night_study_counts_for_the_previous_day_and_milestones_celebrate_once(harness):
    h = harness
    h.repo.state.activity = [date(2026, 9, 23), date(2026, 9, 24)]
    h.clock.now = datetime(2026, 9, 26, 1, 30, tzinfo=IST)
    h.ai.responses.append({"text": "Answer."})
    command(h, "/ask something")
    assert date(2026, 9, 25) in h.repo.state.activity and date(2026, 9, 26) not in h.repo.state.activity
    assert "3-day study streak" in texts(h)[-1] and h.repo.state.milestones == [3]
    h.ai.responses.append({"text": "Answer 2."})
    command(h, "/ask again")
    assert "study streak" not in texts(h)[-1]


def test_weekly_recap_counts_real_effort_instead_of_zero_sessions(harness):
    h = harness
    key, ident = deliver_lesson(h)
    h.ai.responses.append(question_set(5))
    callback(h, f"qnow:{ident}")
    for _ in range(5):
        command(h, "/q B")
    text = recap_text(h.repo.state, datetime(2026, 9, 27, 10, tzinfo=IST))
    assert "Lessons: 1 received" in text and "Quiz questions: 5 answered · 100% correct" in text
    assert "Strongest: IAM (5/5)" in text and "0/5" not in text
    view = today_view(h.repo.state, h.clock.now)
    assert view["quiz"]["status"] == "completed" and view["next"]["kind"] == "exercise"


def test_next_week_starts_even_when_a_change_request_was_left_unfinished(harness):
    h = harness
    journey = shared_journey(h.clock.now)
    for index, day in enumerate(journey.plans["plan-test"].sessions):
        day.lesson_key = f"lesson:{index}"
        h.repo.state.lessons[day.lesson_key] = {
            "topic": "x",
            "date": day.date.isoformat(),
            "delivered_at": h.clock.now.isoformat(),
        }
    h.repo.state.journey = journey
    h.repo.state.profile = Profile(**PROFILE)
    h.ai.responses.append(proposal())
    h.clock.now = datetime(2026, 10, 4, 10, tzinfo=IST)
    h.repo.enqueue("review", {"type": "schedule", "kind": "review", "date": "2026-10-04"})
    h.runtime.recover(media=False)
    proposed = h.repo.state.journey.proposed_id
    assert any("starts automatically" in text for text in texts(h))
    callback(h, f"plan:{proposed}:edit")
    assert h.repo.state.journey.stage == "revision" and h.repo.state.focus == "onboarding"
    h.ai.responses.append(core_guide())
    h.clock.now = datetime(2026, 10, 5, 9, tzinfo=IST)
    h.repo.enqueue("lesson", {"type": "schedule", "kind": "lesson", "date": "2026-10-05"})
    h.runtime.recover(media=False)
    j = h.repo.state.journey
    assert j.active_id == proposed and j.stage == "active" and h.repo.state.focus is None
    assert j.plans[proposed].auto_started_at and j.plans["plan-test"].approved_at
    assert any("started today as planned" in text for text in texts(h))


def test_late_delivery_alert_reaches_the_owner_once(harness):
    h = harness
    key = "schedule:lesson:2026-09-25"
    h.repo.enqueue(key, {"type": "schedule", "kind": "lesson", "date": "2026-09-25"})
    h.repo.jobs[key]["status"] = "done"
    h.repo.outbox[key + ":0"] = {
        "id": key + ":0",
        "job_id": key,
        "body": {"kind": "text", "text": "lesson"},
        "status": "sent",
        "delivered_at": datetime(2026, 9, 25, 9, 45, tzinfo=IST),
    }
    h.clock.now = datetime(2026, 9, 25, 9, 10, tzinfo=IST)
    assert alert_late(h.runtime, "lesson", date(2026, 9, 25)) is None
    h.clock.now = datetime(2026, 9, 25, 9, 50, tzinfo=IST)
    assert alert_late(h.runtime, "lesson", date(2026, 9, 25)) == "alert:late:lesson:2026-09-25"
    assert "finished 45 min after 09:00 IST" in texts(h)[-1]
    count = len(h.telegram.messages)
    alert_late(h.runtime, "lesson", date(2026, 9, 25))
    assert len(h.telegram.messages) == count


def test_configure_telegram_sets_core_commands_and_dashboard_menu(harness):
    h = harness
    calls = []

    class Fake:
        def call(self, method, budget, *, data=None, files=None):
            calls.append((method, data))
            return True

    h.runtime.telegram = Fake()
    h.runtime.config = replace(h.runtime.config, private_dashboard_url="https://example.com/app")
    assert configure_telegram(h.runtime) == {"commands": len(MENU), "menu_button": True}
    assert calls[0][0] == "setMyCommands"
    assert [c["command"] for c in calls[0][1]["commands"]] == [name for name, _ in MENU]
    assert all(name in COMMANDS for name, _ in MENU)
    assert calls[1] == (
        "setChatMenuButton",
        {
            "menu_button": {
                "type": "web_app",
                "text": "Dashboard",
                "web_app": {"url": "https://example.com/app"},
            }
        },
    )


def test_help_groups_every_command_once_and_fits_one_message():
    grouped = [name for _, names in GROUPS for name in names]
    assert sorted(grouped) == sorted(COMMANDS) and len(grouped) == len(set(grouped))
    assert len(help_text()) <= 3480 and "/publish - " not in help_text(admin=False)


def test_learner_launch_window_is_thirty_minutes_while_admin_stays_five():
    raw = signed(42, "token", 1000)
    assert verify_init_data(raw, "token", 1000 + 1700, LEARNER_AUTH_AGE) == (42, 1000)
    with pytest.raises(DashboardDenied):
        verify_init_data(raw, "token", 1000 + 1700)
    with pytest.raises(DashboardDenied):
        verify_init_data(raw, "token", 1000 + 1801, LEARNER_AUTH_AGE)


@pytest.mark.postgres
def test_dashboard_exercise_taps_are_durable_idempotent_and_learner_scoped(pg_repo, config):
    from test_multiuser import Bot

    from skillcoach.web import create_app

    bot = Bot(pg_repo, config)
    learners = {}
    for user in (101, 102):
        scoped = bot.join(user)

        def seed(state, user=user):
            state.tasks[f"{user:020x}"[-20:]] = Task(
                id=f"{user:020x}"[-20:],
                origin=f"lesson-{user}:0",
                title=f"Exercise {user}",
                skill="iam",
                detail="Steps",
                assigned_date=datetime.now(IST).date(),
            )

        bot.save(scoped, seed)
        learners[user] = scoped
    bot.runtime.clock = lambda: datetime.now(IST) + timedelta(seconds=2)
    client = create_app(bot.runtime).test_client()
    raw = signed(101, config.telegram_token, int(bot.runtime.clock().timestamp()))
    data = client.post("/app/data", base_url="https://localhost", json={"init_data": raw})
    assert data.status_code == 200 and {"progress", "today"} <= set(data.json)
    headers = {
        "Origin": "https://localhost",
        "X-Telegram-Init-Data": raw,
        "X-CSRF-Token": data.json["document_csrf"],
    }
    own, other = f"{101:020x}"[-20:], f"{102:020x}"[-20:]

    def tap(task, action="done", ident=None, extra=None):
        return client.post(
            "/app/exercise",
            base_url="https://localhost",
            headers=extra or headers,
            json={"request_id": ident or str(uuid4()), "task_id": task, "action": action},
        )

    ident = str(uuid4())
    assert tap(own, ident=ident).json == {"queued": True, "duplicate": False}
    assert learners[101].read()[1].tasks[own].status == "done"
    assert date.today() - timedelta(days=1) <= learners[101].read()[1].activity[-1]
    assert tap(own, ident=ident).json == {"queued": True, "duplicate": True}
    assert tap(own, "skip", ident=ident).status_code == 409
    assert tap(own).status_code == 409  # Already closed.
    before = learners[102].read()[1]
    assert tap(other).status_code == 409  # Another learner's exercise.
    assert learners[102].read()[1] == before
    for bad in ({}, {**headers, "X-CSRF-Token": "bad"}, {**headers, "Origin": "https://attacker.invalid"}):
        assert tap(own, extra=bad or {"Origin": "https://localhost"}).status_code == 403
    assert tap(own, "delete").status_code == 409
