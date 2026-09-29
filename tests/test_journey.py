import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError
from test_flows import PROFILE, READINESS, RESUME, command

from skillcoach.catalog import TOPICS
from skillcoach.clients import ExternalError
from skillcoach.journey import safe_learning_view, session_dates
from skillcoach.journey_models import Journey, LearningPlan, PlanDraft
from skillcoach.models import Profile
from skillcoach.timeutil import IST
from skillcoach.web import create_app

TOPIC = next(key for key, (_, title) in TOPICS.items() if "EC2" in title)
DIAGNOSTIC = {
    "questions": [{"skill": "Cloud", "question": f"Explain a concrete cloud concept {i}."} for i in range(5)]
}


def proposal():
    return {
        "sessions": [
            {
                "topic_id": TOPIC,
                "objective": f"Explain concept {i}",
                "practice": "Draw and explain the flow",
                "reason": "foundation",
            }
            for i in range(5)
        ],
        "rationale": "Private initial estimate based on stated goals and sampled diagnostic skills.",
    }


def core_guide(minutes=30):
    count = {15: 1, 30: 2, 45: 3, 60: 4}[minutes]
    budget = minutes - {15: 5, 30: 10, 45: 15, 60: 20}[minutes]
    return {
        "explanation": f"Core study for {minutes} minutes: explain and apply the approved concept.",
        "tasks": [
            {
                "name": f"Core exercise {i}",
                "goal": "Apply the approved practice",
                "steps": [f"Draw and explain scenario {i}; compare alternatives."],
                "minutes": budget // count,
            }
            for i in range(count)
        ],
    }


def callback(h, data, *, drain=True):
    key = f"callback:{len(h.repo.jobs) + 1}"
    h.repo.enqueue(key, {"type": "telegram", "callback": data})
    if drain:
        h.runtime.recover(media=False)
    return key


def setup(h, *, documents=False):
    for value in ["/onboard", "agree", "Cloud engineering", "2", "beginner", "30", "Asia/Kolkata"]:
        command(h, value)
    assert h.repo.state.profile is None or h.repo.state.profile.name == PROFILE["name"]
    command(h, RESUME if documents else "/skip")
    h.ai.responses.append(DIAGNOSTIC)
    command(
        h,
        "A job description requiring cloud knowledge and practical infrastructure skills."
        if documents
        else "/skip",
    )
    assert h.repo.state.journey.stage == "diagnostic"


def finish_setup(h):
    for index in range(4):
        command(h, f"Actual diagnostic answer {index}")
    h.ai.responses.extend([READINESS, proposal()])
    command(h, "Fifth actual answer")
    assert h.repo.state.journey.stage == "ready"
    return h.repo.state.journey.proposed_id


@pytest.mark.parametrize("documents", [False, True])
def test_guided_setup_is_optional_private_and_plan_requires_approval(harness, documents):
    h = harness
    setup(h, documents=documents)
    ident = finish_setup(h)
    assert h.repo.state.profile is None and not h.repo.state.tasks
    assert len(h.repo.answer_keys) == 5
    assert len(h.ai.calls) == 3
    for kind in ("lesson", "quiz", "weekly", "review"):
        h.repo.enqueue(
            "before-approval:" + kind,
            {"type": "schedule", "kind": kind, "date": h.clock.now.date().isoformat()},
        )
    h.runtime.recover(media=False)
    assert len(h.ai.calls) == 3 and not h.repo.state.lessons
    callback(h, f"plan:{ident}:approve")
    assert h.repo.state.journey.active_id == ident and h.repo.state.journey.stage == "active"
    assert h.repo.state.profile.years_experience == 2
    assert bool(h.repo.state.profile.resume_text) == documents
    assert bool(h.repo.state.profile.jd_text) == documents
    callback(h, f"plan:{ident}:approve")
    assert len(h.ai.calls) == 3 and len(h.repo.answer_keys) == 5


def test_unknown_diagnostic_button_is_question_bound_and_no_score_on_failure(harness):
    h = harness
    h.repo.state.profile = Profile(**PROFILE)
    setup(h)
    j = h.repo.state.journey
    stale = f"j:{j.id}:diagnostic-0:unknown"
    callback(h, stale)
    assert h.repo.state.journey.diagnostic_answers == ["I do not know yet"]
    callback(h, stale)
    assert len(h.repo.state.journey.diagnostic_answers) == 1
    for _ in range(3):
        command(h, "An actual answer")
    h.ai.responses.append(ExternalError("ai_unavailable"))
    failed = command(h, "Actual fifth answer")
    assert h.repo.jobs[failed]["status"] == "failed"
    assert len(h.repo.answer_keys) == 4 and h.repo.state.journey.diagnostic_rating is None
    assert h.repo.state.profile == Profile(**PROFILE)
    h.ai.responses.extend([READINESS, proposal()])
    command(h, "/retry")
    assert len(h.repo.answer_keys) == 5 and h.repo.state.journey.stage == "ready"
    assert h.repo.state.profile == Profile(**PROFILE)


def test_cancel_preserves_old_profile_and_does_not_implicitly_start_new_learning(harness):
    h = harness
    h.repo.state.profile = Profile(**PROFILE)
    setup(h)
    command(h, "/cancel")
    assert h.repo.state.profile == Profile(**PROFILE)
    assert h.repo.state.focus is None and h.repo.state.journey.stage == "welcome"
    h.repo.enqueue("blocked", {"type": "schedule", "kind": "lesson", "date": h.clock.now.date().isoformat()})
    h.runtime.recover(media=False)
    assert not h.repo.state.lessons


def test_plan_edit_invalidates_old_buttons_and_updates_explicit_pace_and_level(harness):
    h = harness
    setup(h)
    old = finish_setup(h)
    callback(h, f"plan:{old}:edit")
    command(h, "/pace 15")
    command(h, "/level intermediate")
    h.ai.responses.append(proposal())
    command(h, "Put networking before compute; keep prerequisites.")
    j = h.repo.state.journey
    assert j.proposed_id != old
    assert j.plans[j.proposed_id].minutes == 15 and j.plans[j.proposed_id].level == "intermediate"
    callback(h, f"plan:{old}:now")
    assert h.repo.state.journey.active_id is None
    callback(h, "plan:another-users-plan:approve")
    assert h.repo.state.journey.active_id is None


def test_start_now_and_weekday_schedule_do_not_duplicate_day_one(harness):
    h = harness
    h.clock.now = datetime(2026, 9, 28, 8, tzinfo=IST)
    setup(h)
    ident = finish_setup(h)
    callback(h, f"plan:{ident}:now")
    assert len(h.repo.state.lessons) == 1 and len(h.repo.state.tasks) == 2
    before = h.repo.state.model_copy(deep=True)
    h.clock.now = datetime(2026, 9, 28, 9, tzinfo=IST)
    h.repo.enqueue("scheduled", {"type": "schedule", "kind": "lesson", "date": "2026-09-28"})
    h.runtime.recover(media=False)
    assert h.repo.state.lessons == before.lessons and h.repo.state.tasks == before.tasks
    callback(h, f"plan:{ident}:now")
    assert len(h.repo.state.lessons) == 1


def test_proposal_redates_only_after_showing_new_version(harness):
    h = harness
    setup(h)
    ident = finish_setup(h)
    h.clock.now += timedelta(days=10)
    callback(h, f"plan:{ident}:approve")
    j = h.repo.state.journey
    assert j.active_id is None and j.proposed_id != ident
    callback(h, f"plan:{j.proposed_id}:approve")
    assert h.repo.state.journey.stage == "active"


def test_pause_and_plan_revision_cannot_bypass_approval(harness):
    h = harness
    setup(h)
    ident = finish_setup(h)
    command(h, "/pause")
    callback(h, f"plan:{ident}:now")
    assert not h.repo.state.lessons and h.repo.state.journey.active_id is None
    command(h, "/unpause")
    callback(h, f"plan:{ident}:approve")
    callback(h, f"plan:{ident}:edit")
    callback(h, f"plan:{ident}:approve")
    assert h.repo.state.journey.stage == "revision"
    command(h, "/cancel")
    assert h.repo.state.journey.stage == "active" and h.repo.state.journey.active_id == ident


def test_no_proposal_may_invent_progress_and_admin_never_sees_private_rationale(harness):
    h = harness
    setup(h)
    for _ in range(4):
        command(h, "Actual answer")
    invalid = proposal()
    invalid["sessions"][0]["lesson_key"] = "invented-completion"
    h.ai.responses.extend([READINESS, invalid])
    command(h, "Fifth answer")
    assert h.repo.state.journey.stage == "planning"
    assert not h.repo.state.lessons and len(h.repo.answer_keys) == 5
    h.ai.responses.append(proposal())
    command(h, "/retry")
    ident = h.repo.state.journey.proposed_id
    callback(h, f"plan:{ident}:approve")
    j = h.repo.state.journey
    private = "PRIVATE-RESUME-EMPLOYER-ANSWER"
    j.goal = j.resume_text = j.jd_text = j.revision_request = private
    j.plans[ident].rationale = private
    j.plans[ident].sessions[0].objective = private
    j.plans[ident].sessions[0].practice = private
    encoded = json.dumps(safe_learning_view(h.repo.state, h.clock.now))
    assert private not in encoded and TOPICS[TOPIC][1] in encoded
    assert "foundation" not in encoded or "foundations" in encoded
    j.consent_at = None
    assert safe_learning_view(h.repo.state, h.clock.now)["sessions"] == []


@pytest.mark.parametrize("count", [0, 4, 6])
def test_plan_requires_exactly_five_sessions(count):
    value = proposal()
    value["sessions"] = value["sessions"][:count] if count < 5 else value["sessions"] + value["sessions"][:1]
    with pytest.raises(ValidationError):
        PlanDraft.model_validate(value)


def test_exact_catalog_and_no_arbitrary_private_topic_titles():
    value = proposal()
    value["sessions"][0]["topic_id"] = "My private employer project"
    with pytest.raises(ValidationError):
        PlanDraft.model_validate(value)


def test_day_one_dates_respect_ist_and_weekend_slots():
    sunday = datetime(2026, 9, 27, 23, 59, tzinfo=IST)
    assert session_dates(sunday)[0].isoformat() == "2026-09-28"
    assert session_dates(sunday, start_now=True)[0].isoformat() == "2026-09-27"
    assert len(set(session_dates(sunday))) == 5
    assert all(day.weekday() < 5 for day in session_dates(sunday))
    assert session_dates(datetime(2026, 9, 28, 9, tzinfo=IST))[0].isoformat() == "2026-09-29"


@pytest.mark.postgres
def test_public_requests_are_verified_pending_bounded_and_idempotent(pg_repo, config):
    from test_multiuser import Bot

    bot = Bot(pg_repo, replace(config, access_requests_enabled=True))
    client = create_app(bot.runtime).test_client()
    before = bot.repo.read()
    assert client.get("/join").status_code == 200
    assert client.get("/join/config").json["telegram_url"].endswith("?start=request")
    assert bot.repo.read() == before
    assert client.post("/join", json={"user_id": 101}).status_code == 405
    assert client.post("/", json={"user_id": 101}).status_code == 403

    def request(i):
        return bot.repo.accept_update(
            9000 + i,
            {"type": "telegram", "actor_id": 101, "display_name": "Learner", "text": "/start request"},
            bot.config,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(request, range(2))) == ["pending", "pending"]
    assert bot.member(101)["status"] == "pending"
    scoped = bot.repo.for_learner(bot.member(101)["id"])
    assert scoped.read()[1].journey.stage == "welcome"
    with bot.repo.connection() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM access_audit WHERE action='request_access'").fetchone()[
                "n"
            ]
            == 1
        )
        assert (
            conn.execute("SELECT count(*) AS n FROM jobs WHERE payload->>'type'='access_request'").fetchone()[
                "n"
            ]
            == 1
        )
    assert bot.input(101, "/ask private") == "pending"
    bot.runtime.recover(media=False)
    assert not bot.runtime.ai.calls and not bot.runtime.telegram.messages
    assert bot.input(101, "/approve " + scoped.learner_id) == "denied"
    bot.input(config.owner_id, "/approve " + scoped.learner_id)
    assert bot.member(101)["status"] == "active"
    bot.input(101, callback="onboard:start")
    assert scoped.read()[1].journey.stage == "consent"
    bot.input(config.owner_id, "/revoke " + scoped.learner_id)
    assert bot.input(101, "/start request") == "revoked"
    assert scoped.read()[1].journey.stage == "consent"


@pytest.mark.postgres
def test_public_request_caps_and_disabled_mode(pg_repo, config):
    from test_multiuser import Bot

    bot = Bot(pg_repo, config)
    assert bot.input(101, "/request") == "invite_required"
    assert bot.member(101) is None
    bot.config = replace(bot.config, access_requests_enabled=True, max_learners=1)
    assert bot.input(101, "/request") == "pending"
    bot.input(config.owner_id, "/approve " + bot.member(101)["id"])
    assert bot.member(101)["status"] == "pending"
    bot.input(config.owner_id, "/reject " + bot.member(101)["id"])
    assert bot.input(101, "/request") == "rejected"
    with bot.repo.connection() as conn:
        conn.execute(
            "INSERT INTO learners(id,telegram_id,status) SELECT 'cap_'||n,10000+n,'pending' FROM generate_series(1,100) n"
        )
    assert bot.input(102, "/request") == "pending_capacity_reached"
    assert bot.member(102) is None


@pytest.mark.postgres
def test_plan_followup_transaction_rollback_and_learner_isolation(pg_repo, config):
    from test_multiuser import Bot

    bot = Bot(pg_repo, config)
    a, b = bot.join(101), bot.join(102)
    before_b = b.read()
    key = "learner:" + a.learner_id + ":finish"
    a.enqueue("finish", {"type": "telegram", "text": "/help"})
    token = pg_repo.acquire("domain", 60)
    try:
        revision, state = a.read()
        state.journey = Journey(id="test-journey", stage="planning")
        with pytest.raises(ValueError):
            a.finish(key, token, revision, state, [], [], {"type": "arbitrary"})
        assert a.read()[0] == revision and a.read()[1].journey is None
        a.finish(
            key,
            token,
            revision,
            state,
            [],
            [],
            {"type": "journey", "journey_id": "test-journey", "action": "propose"},
        )
    finally:
        pg_repo.release("domain", token)
    assert b.read() == before_b
    with pg_repo.connection() as conn:
        row = conn.execute(
            "SELECT learner_id,access_generation FROM jobs WHERE id=%s", (key + ":next",)
        ).fetchone()
        assert row["learner_id"] == a.learner_id
    bot.input(config.owner_id, "/revoke " + a.learner_id, drain=False)
    bot.runtime.recover(media=False)
    assert not bot.runtime.ai.calls


def shared_journey(now):
    draft = proposal()
    for day, due in zip(draft["sessions"], session_dates(now)):
        day["date"] = due
    plan = LearningPlan(
        **draft,
        id="plan-test",
        version=1,
        created_at=now,
        approved_at=now,
        expires_at=now + timedelta(days=7),
        minutes=30,
        level="beginner",
        timezone="Asia/Kolkata",
    )
    return Journey(
        id="journey-test",
        stage="active",
        consent_at=now,
        years=2,
        goal="private goal",
        plans={plan.id: plan},
        active_id=plan.id,
        diagnostic_answers=["private"] * 5,
        diagnostic_rating=READINESS,
    )


@pytest.mark.postgres
def test_real_new_learner_flow_concurrent_approval_and_completed_history(pg_repo, config):
    from test_multiuser import Bot

    bot = Bot(pg_repo, replace(config, access_requests_enabled=True))
    owner_before = pg_repo.read()
    assert bot.input(101, "/start request") == "pending"
    member = bot.member(101)
    bot.input(config.owner_id, "/approve " + member["id"])
    scoped = pg_repo.for_learner(member["id"])
    for value in ["/onboard", "agree", "Cloud engineer", "0", "beginner", "15", "UTC", "/skip"]:
        bot.input(101, value)
    bot.runtime.ai.responses.append(DIAGNOSTIC)
    bot.input(101, "/skip")
    for i in range(4):
        bot.input(101, "Actual response " + str(i))
    bot.runtime.ai.responses.extend([READINESS, proposal()])
    bot.input(101, "Actual fifth response")
    state = scoped.read()[1]
    ident = state.journey.proposed_id
    assert state.profile is None and state.journey.active_id is None

    # Two accepted updates selecting the same version must start just one Day 1 job.
    def approve(index):
        return pg_repo.accept_update(
            19000 + index,
            {
                "type": "telegram",
                "actor_id": 101,
                "callback": f"plan:{ident}:now",
                "callback_id": "test",
            },
            bot.config,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(approve, range(2))) == ["queued", "queued"]
    bot.runtime.recover(media=False)
    state = scoped.read()[1]
    assert state.profile.years_experience == 0 and state.profile.skills == []
    assert state.profile.resume_text == state.profile.jd_text == ""
    assert len(state.lessons) == 1 and len(state.tasks) == 1
    with pg_repo.connection() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM answer_keys WHERE learner_id=%s", (member["id"],)
            ).fetchone()["n"]
            == 5
        )
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM jobs WHERE learner_id=%s AND payload->>'action'='lesson'",
                (member["id"],),
            ).fetchone()["n"]
            == 1
        )
    assert pg_repo.read() == owner_before


def test_revision_preserves_prepared_sessions_and_requires_real_delivery_for_understanding(harness):
    h = harness
    h.clock.now = datetime(2026, 9, 28, 8, tzinfo=IST)
    setup(h)
    first = finish_setup(h)
    callback(h, f"plan:{first}:now")
    prepared = h.repo.state.journey.plans[first].sessions[0].model_copy(deep=True)
    tasks = h.repo.state.tasks.copy()
    callback(h, f"understand:{first}:0")
    assert h.repo.state.journey.plans[first].sessions[0].understood_at is None
    callback(h, f"plan:{first}:edit")
    h.ai.responses.append(proposal())
    command(h, "Change only the remaining sessions.")
    j = h.repo.state.journey
    assert j.plans[j.proposed_id].sessions[0] == prepared
    assert h.repo.state.tasks == tasks
    callback(h, f"plan:{j.proposed_id}:now")
    assert h.repo.state.journey.active_id == first  # Do not start a second plan lesson on the same day.
    callback(h, f"plan:{j.proposed_id}:approve")
    active = h.repo.state.journey.plans[h.repo.state.journey.active_id]
    assert active.sessions[0] == prepared
    assert active.sessions[1].date.isoformat() == "2026-09-29"


def test_proposal_failure_does_not_repeat_diagnostic_grading(harness):
    h = harness
    setup(h)
    for _ in range(4):
        command(h, "Actual answer")
    h.ai.responses.extend([READINESS, ExternalError("rate_limited")])
    command(h, "Fifth actual answer")
    assert h.repo.state.journey.stage == "planning" and len(h.repo.answer_keys) == 5
    h.ai.responses.append(proposal())
    command(h, "/retry")
    assert h.repo.state.journey.stage == "ready"
    assert len([call for call in h.ai.calls if call[1] == "Readiness"]) == 1
    assert len(h.repo.answer_keys) == 5


def test_existing_approved_plan_keeps_running_and_stale_revision_is_reconciled(harness):
    h = harness
    h.clock.now = datetime(2026, 9, 28, 8, tzinfo=IST)
    setup(h)
    first = finish_setup(h)
    callback(h, f"plan:{first}:approve")
    callback(h, f"plan:{first}:edit")
    h.ai.responses.append(proposal())
    command(h, "Change future sessions, not existing work.")
    candidate = h.repo.state.journey.proposed_id
    assert h.repo.state.journey.plans[candidate].replaces_plan_id == first
    h.clock.now = datetime(2026, 9, 28, 9, tzinfo=IST)
    h.repo.enqueue("day1", {"type": "schedule", "kind": "lesson", "date": "2026-09-28"})
    h.runtime.recover(media=False)
    assert len(h.repo.state.lessons) == 1
    assert h.repo.state.journey.active_id == first and h.repo.state.journey.proposed_id == candidate
    prepared = h.repo.state.journey.plans[first].sessions[0].model_copy(deep=True)
    callback(h, f"plan:{candidate}:approve")
    j = h.repo.state.journey
    assert j.active_id == first and j.proposed_id != candidate
    assert j.plans[j.proposed_id].sessions[0] == prepared
    callback(h, f"plan:{j.proposed_id}:approve")
    assert h.repo.state.journey.active_id != first
    assert len(h.repo.state.lessons) == 1 and len(h.repo.state.tasks) == 2


def test_old_understanding_button_maps_only_to_exact_carried_lesson(harness):
    h = harness
    h.clock.now = datetime(2026, 9, 28, 8, tzinfo=IST)
    setup(h)
    first = finish_setup(h)
    callback(h, f"plan:{first}:now")
    key = h.repo.state.journey.plans[first].sessions[0].lesson_key
    # Fake confirmed transport, without changing tasks or answers.
    h.repo.state.lessons[key]["delivered_at"] = h.clock.now.isoformat()
    callback(h, f"plan:{first}:edit")
    h.ai.responses.append(proposal())
    command(h, "Keep Day 1 and change the remaining sessions.")
    proposed = h.repo.state.journey.proposed_id
    callback(h, f"plan:{proposed}:approve")
    before_tasks = h.repo.state.tasks.copy()
    before_answers = h.repo.answer_keys.copy()
    callback(h, f"understand:{first}:0")
    assert h.repo.state.journey.plans[proposed].sessions[0].understood_at is not None
    assert h.repo.state.journey.plans[first].sessions[0].understood_at is None
    callback(h, f"understand:{first}:1")
    assert h.repo.state.journey.plans[proposed].sessions[1].understood_at is None
    callback(h, "understand:another-learner:0")
    assert h.repo.state.tasks == before_tasks and h.repo.answer_keys == before_answers


def test_next_week_approval_waits_for_all_prior_lesson_delivery_markers(harness):
    h = harness
    h.repo.state.journey = shared_journey(h.clock.now)
    active = h.repo.state.journey.plans["plan-test"]
    for i, day in enumerate(active.sessions):
        day.lesson_key = f"lesson:{i}"
        h.repo.state.lessons[day.lesson_key] = {
            "topic": TOPICS[day.topic_id][1],
            "date": day.date.isoformat(),
            "delivered_at": h.clock.now.isoformat() if i < 4 else None,
        }
    callback(h, "plan:plan-test:edit")
    h.ai.responses.append(proposal())
    command(h, "Prepare my next study week.")
    candidate = h.repo.state.journey.proposed_id
    assert not any(d.lesson_key for d in h.repo.state.journey.plans[candidate].sessions)
    callback(h, f"plan:{candidate}:approve")
    assert h.repo.state.journey.active_id == "plan-test"
    assert "still being delivered" in h.telegram.messages[-1][0]
    h.repo.state.lessons["lesson:4"]["delivered_at"] = h.clock.now.isoformat()
    callback(h, f"plan:{candidate}:approve")
    assert h.repo.state.journey.active_id == candidate
