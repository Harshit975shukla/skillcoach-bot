import json
from datetime import date, datetime, timedelta

import pytest

from skillcoach.clients import Budget, ExternalError
from skillcoach.models import Profile, Task
from skillcoach.service import Service
from skillcoach.timeutil import IST

PROFILE = {
    "name": "Private Learner",
    "current_role": "Developer",
    "target_role": "Platform engineer",
    "level": "intermediate",
    "years_experience": 3,
    "skills": ["AWS", "Python"],
}
READINESS = {
    "readiness_score": 61,
    "strong_skills": ["Python"],
    "gap_skills": ["IAM"],
    "summary": "Needs policy evaluation practice.",
    "skill_ratings": {"Python": 4, "IAM": 2},
}
RESUME = "Actual resume with experience and skills. " * 5


def question_set(count):
    return {
        "questions": [
            {
                "question": f"Question {i}?",
                "topic": "IAM",
                "options": {"A": "One", "B": "Two", "C": "Three", "D": "Four"},
                "answer": "B",
                "explanation": f"Explanation {i}.",
            }
            for i in range(count)
        ]
    }


def command(h, text, *, drain=True):
    key = f"telegram:{len(h.repo.jobs) + 1}"
    h.repo.enqueue(key, {"type": "telegram", "text": text})
    if drain:
        h.runtime.recover(media=False)
    return key


def test_onboarding_cancel_failed_analysis_retry_and_diagnostic(harness):
    h = harness
    old = Profile(**PROFILE)
    h.repo.state.profile = old
    command(h, "/setup")
    assert h.repo.state.profile == old
    command(h, "/cancel")
    assert h.repo.state.profile == old and h.repo.state.draft is None
    command(h, "/profile setup")
    h.ai.responses.append(ExternalError("ai_unavailable"))
    failed = command(h, RESUME)
    assert h.repo.state.draft.stage == "resume"
    assert h.repo.state.profile == old
    h.ai.responses.append(PROFILE)
    command(h, "/retry")
    assert h.repo.jobs[failed]["status"] == "done"
    assert h.repo.state.draft.stage == "jd"
    h.ai.responses.append(
        {"questions": [{"skill": "IAM", "question": f"Explain policy {i}"} for i in range(5)]}
    )
    command(h, "/skip")
    for i in range(4):
        command(h, f"Diagnostic answer {i}")
    h.ai.responses.append(READINESS)
    command(h, "Fifth actual answer")
    assert h.repo.state.profile.readiness.readiness_score == 61
    assert h.repo.state.profile.readiness_basis == "diagnostic"
    assert h.repo.state.draft is None
    assert len(h.repo.answer_keys) == 5
    assert h.repo.state.legacy_archive["diagnostics"]


def test_jd_setup_and_actual_resume_feedback(harness):
    h = harness
    command(h, "/profile")
    h.ai.responses.append(PROFILE)
    command(h, RESUME)
    h.ai.responses.append({**READINESS, "target_role": "Actual JD role"})
    command(h, "Job description requires IAM and infrastructure experience. " * 3)
    assert h.repo.state.profile.target_role == "Actual JD role"
    assert h.repo.state.profile.readiness_basis == "resume-jd"
    h.ai.responses.append(
        {
            "score": 73,
            "issues": ["Quantify supported outcomes"],
            "wins": ["Specific skills"],
            "summary": "Review of the actual document",
        }
    )
    command(h, "/resume")
    assert h.repo.state.resume_feedback.score == 73
    assert RESUME.strip() in h.ai.calls[-1][0]
    assert "Actual JD role" in h.ai.calls[-1][0]


def test_question_first_interview_and_retry_without_regrading(harness):
    h = harness
    h.ai.responses.append({"skill": "IAM", "question": "Explain policy evaluation."})
    command(h, "/interview IAM")
    assert not any("model answer:" in m[0].lower() for m in h.telegram.messages)
    h.ai.responses.append(
        {
            "score": 7,
            "accuracy": 8,
            "reasoning": 7,
            "communication": 6,
            "feedback": "Discuss explicit denies.",
            "model_answer": "Hypothetically, evaluate policies.",
        }
    )
    h.telegram.fail = True
    command(h, "My actual answer")
    assert next(iter(h.repo.state.interviews.values())).status == "completed"
    calls = len(h.ai.calls)
    h.telegram.fail = False
    command(h, "/retry")
    assert len(h.ai.calls) == calls
    assert any("Hypothetical model answer" in m[0] for m in h.telegram.messages)


@pytest.mark.parametrize("count", [4, 6, 9, 11])
def test_exact_daily_question_count_failure_does_not_activate(harness, count):
    h = harness
    h.repo.state.profile = Profile(**PROFILE)
    h.repo.state.lessons["today"] = {"topic": "IAM", "date": "2026-09-25"}
    h.ai.responses.append(question_set(count))
    h.repo.enqueue("schedule:quiz", {"type": "schedule", "kind": "quiz", "date": "2026-09-25"})
    h.runtime.recover(media=False)
    assert not h.repo.state.assessments
    assert h.repo.jobs["schedule:quiz"]["status"] == "failed"


def test_daily_and_weekly_stale_buttons_concurrent_answers(harness):
    h = harness
    h.repo.state.profile = Profile(**PROFILE)
    h.repo.state.lessons["today"] = {"topic": "IAM", "date": "2026-09-25"}
    h.ai.responses.append(question_set(5))
    h.repo.enqueue("schedule:quiz", {"type": "schedule", "kind": "quiz", "date": "2026-09-25"})
    h.runtime.recover(media=False)
    daily = h.repo.state.active_assessment
    stale = h.repo.state.target()
    first = command(h, "/q B", drain=False)
    command(h, "/q B", drain=False)
    h.runtime.recover(media=False)
    assert len(h.repo.state.assessments[daily].answers) == 1
    assert h.repo.enqueue(first, {"type": "telegram", "text": "/q B"}) is False
    h.clock.now = datetime(2026, 9, 26, 9, tzinfo=IST)
    h.ai.responses.append(question_set(10))
    h.repo.enqueue("schedule:weekly", {"type": "schedule", "kind": "weekly", "date": "2026-09-26"})
    h.runtime.recover(media=False)
    weekly = h.repo.state.active_assessment
    assert h.repo.state.assessments[daily].status == "expired"
    assert weekly != daily
    h.repo.enqueue(
        "stale-button", {"type": "telegram", "callback": f"q:{stale['session']}:{stale['question']}:B"}
    )
    h.runtime.recover(media=False)
    assert not h.repo.state.assessments[weekly].answers
    for _ in range(10):
        command(h, "/q B")
    assert h.repo.state.assessments[weekly].status == "completed"
    assert len(h.repo.state.assessments[weekly].answers) == 10
    assert len(h.repo.answer_keys) == 11


def test_full_authored_lesson_tasks_media_and_completion(harness):
    h = harness
    command(h, "/learn EC2")
    assert len(h.repo.state.tasks) == 3
    bodies = [o["body"] for o in h.repo.outbox.values()]
    media = [b for b in bodies if b["kind"] == "media"]
    assert len(media) == 5 and all(b["mode"] == "video" for b in media)
    text = "\n".join(b.get("text", "") for b in bodies)
    assert "Concept 4" in text and "CLEANUP" in text and "REFERENCES" in text
    assert len(text) > 5000
    command(h, "/learn EC2")
    assert len(h.repo.state.tasks) == 3
    ident = next(iter(h.repo.state.tasks))
    command(h, f"/complete {ident} 17")
    command(h, f"/complete {ident} 99")
    assert h.repo.state.tasks[ident].actual_minutes == 17
    assert h.repo.state.activity == [date(2026, 9, 25)]
    command(h, "/media static")
    command(h, "/learn S3")
    assert len(h.repo.state.tasks) == 6
    assert all(
        o["body"]["mode"] == "static"
        for o in list(h.repo.outbox.values())[-20:]
        if o["body"]["kind"] == "media"
    )


def test_pause_unpause_does_not_replay_queued_scheduled_messages(harness):
    h = harness
    h.repo.enqueue("scheduled", {"type": "schedule", "kind": "lesson", "date": "2026-09-25"})
    h.runtime.process_one(Budget())
    command(h, "/pause", drain=False)
    command(h, "/unpause", drain=False)
    h.runtime.recover(media=False)
    assert h.repo.state.paused is False
    assert all(o["status"] == "suppressed" for o in h.repo.outbox.values() if o["job_id"] == "scheduled")


def test_sunday_missing_score_plan_dates_and_repeat(harness):
    h = harness
    h.clock.now = datetime(2026, 9, 27, 10, tzinfo=IST)
    h.repo.state.profile = Profile(**PROFILE)
    start = date(2026, 9, 28)
    plan = {
        "days": {(start + timedelta(days=i)).isoformat(): "IAM revision" for i in range(6)},
        "rationale": "Revise actual IAM gaps.",
    }
    h.ai.responses.append(plan)
    h.repo.enqueue("sunday", {"type": "schedule", "kind": "review", "date": "2026-09-27"})
    h.runtime.recover(media=False)
    assert "unavailable" in h.telegram.messages[-1][0]
    assert len(h.repo.state.plans) == 1
    h.repo.enqueue("sunday-repeat", {"type": "schedule", "kind": "review", "date": "2026-09-27"})
    h.runtime.recover(media=False)
    assert len(h.repo.state.plans) == 1 and len(h.ai.calls) == 1
    assert "Private Learner" in h.ai.calls[0][0]


def test_personalized_context_includes_errors_and_actual_tasks(harness):
    h = harness
    h.repo.state.profile = Profile(**PROFILE)
    h.repo.state.tasks["task"] = Task(
        id="task",
        origin="unique",
        title="Policy exercise",
        skill="IAM",
        detail="Private",
        assigned_date=date(2026, 9, 25),
    )
    h.repo.state.lessons["today"] = {"topic": "IAM", "date": "2026-09-25"}
    h.ai.responses.append(question_set(5))
    h.repo.enqueue("quiz", {"type": "schedule", "kind": "quiz", "date": "2026-09-25"})
    h.runtime.recover(media=False)
    command(h, "/q A")
    service = Service(h.repo, h.ai, h.runtime.config, lambda: h.clock.now)
    service.state = h.repo.state
    context = json.loads(service.context())
    assert context["recent_errors"][0]["misconception"] == "Explanation 0."
    assert context["tasks"][0]["title"] == "Policy exercise"


def test_failed_export_notice_is_visible_but_success_is_not(harness):
    h = harness
    h.publisher.fail = True
    command(h, "/publish")
    assert any("failed" in text for text, _ in h.telegram.messages)
    assert not any("summary published" in text for text, _ in h.telegram.messages)
    command(h, "/help")
    assert any("SkillCoach" in text for text, _ in h.telegram.messages)
    h.publisher.fail = False
    command(h, "/retry")
    assert len(h.publisher.documents) == 1
    assert any("summary published" in text for text, _ in h.telegram.messages)


def test_private_skills_preserve_labels_public_export_redacts(harness):
    from skillcoach.export import public_export

    h = harness
    for index, skill in enumerate(("Kubernetes networking", "PostgreSQL tuning")):
        ident = str(index)
        h.repo.state.tasks[ident] = Task(
            id=ident, origin=ident, title="Practice", skill=skill, detail="", assigned_date=h.clock.now.date()
        )
    command(h, "/skills")
    text = h.telegram.messages[-1][0]
    assert "Kubernetes networking" in text and "PostgreSQL tuning" in text
    public = public_export(h.repo.state, h.clock.now)
    assert public["skills"] == [{"skill": "General practice", "done": 0, "total": 2}]


def test_cancel_failed_export_cancels_its_success_message_too(harness):
    h = harness
    h.publisher.fail = True
    publish = command(h, "/publish")
    command(h, "/cancel")
    h.publisher.fail = False
    command(h, "/retry")
    assert not h.publisher.documents
    assert not any("summary published" in text for text, _ in h.telegram.messages)
    assert all(
        row["status"] in ("sent", "suppressed") for row in h.repo.outbox.values() if row["job_id"] == publish
    )


def test_cutover_owner_notification_is_release_idempotent(harness, monkeypatch):
    from skillcoach.cli import main

    h = harness
    monkeypatch.setattr("skillcoach.cli.Runtime.from_env", lambda: h.runtime)
    assert main(["announce-ready", "--release", "a" * 40]) == 0
    assert main(["announce-ready", "--release", "a" * 40]) == 0
    assert len(h.repo.jobs) == 1
    assert len(h.telegram.messages) == 1
    assert h.repo.state.profile is None and not h.repo.state.assessments
