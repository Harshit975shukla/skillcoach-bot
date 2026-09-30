import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
import requests
from test_flows import PROFILE, command, question_set
from test_journey import callback, core_guide, proposal, shared_journey

from skillcoach.catalog import TOPICS
from skillcoach.clients import Budget, ExternalError
from skillcoach.lab_checks import LabChecker
from skillcoach.lab_flow import admin_counts, canonical_link, lab_view, pending_required
from skillcoach.labs import (
    CODE_LABS,
    LAB_TEST_BLOBS,
    LABS,
    SHARED_BLOBS,
    SHARED_PROTECTED,
    TEMPLATE_BLOBS,
    WORKFLOW_PATH,
    blob_sha,
    required_quota,
    token_blob_shas,
    url_digest,
)
from skillcoach.models import LabAssignment, Profile
from skillcoach.module_labs import MODULE_OF
from skillcoach.timeutil import IST

REAL_SEND = requests.adapters.HTTPAdapter.send
REAL_REQUEST = requests.Session.request

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "labs_template"
EXPECTED = {
    "s3-private-presigned": 12,
    "lambda-function-url": 8,
    "iam-least-privilege": 10,
    "dynamodb-idempotent-write": 8,
    "sqs-idempotent-consumer": 3,
    "vpc-subnet-routing": 10,
}
S3 = next(key for key, (_, title) in TOPICS.items() if title == LABS["s3-private-presigned"].topics[0])
TOKEN = "SC-ABCD-EFGH"
SIGNED = (
    "https://skillcoach-lab.s3.ap-south-1.amazonaws.com/skillcoach-token.txt"
    "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Expires=3600&X-Amz-Signature=abc123"
)


def lf_sha(path):
    return blob_sha(path.read_bytes().replace(b"\r\n", b"\n"))


def texts(h):
    return [text for text, _ in h.telegram.messages]


def queued(h):
    """Every outbox text in order, delivered or still waiting behind a lesson video."""
    return [row["body"]["text"] for row in h.repo.outbox.values() if row["body"].get("kind") == "text"]


# Template, catalog and pinned protected files ------------------------------------------------


def test_catalog_topics_routes_and_protected_template_pins():
    titles = {title for _, title in TOPICS.values()}
    for lab in LABS.values():
        assert set(lab.topics) <= titles, lab.id
        assert lab.routes[0] == "scenario" and len(lab.scenario) == 4
        for step in lab.scenario:
            assert len(set(step.options)) == 4 and step.explanation and step.prompt
        if lab.id not in MODULE_OF:  # Per-module labs cite their own official docs (test_module_labs.py).
            assert lab.references and all(
                r.startswith("https://docs.aws.amazon.com/") for r in lab.references
            )
        if lab.aws:
            assert lab.aws.cleanup and any("{token}" in step for step in lab.aws.steps)
    assert set(CODE_LABS) == {lab.id for lab in LABS.values() if lab.code} == set(EXPECTED)
    for path in SHARED_PROTECTED:
        assert SHARED_BLOBS[path] == lf_sha(TEMPLATE / path), path
    workflow = (TEMPLATE / WORKFLOW_PATH).read_text()
    for lab in CODE_LABS:
        assert LAB_TEST_BLOBS[lab] == lf_sha(TEMPLATE / "labs" / lab / "test_lab.py")
        assert TEMPLATE_BLOBS[lab] == {**SHARED_BLOBS, f"labs/{lab}/test_lab.py": LAB_TEST_BLOBS[lab]}
        assert f"\n  lab-{lab}:\n" in workflow.replace("\r\n", "\n")
        assert f"check_report.py .skillcoach-report.xml {EXPECTED[lab]}" in workflow
        assert f"hashFiles('.skillcoach/{lab}.token')" in workflow
        assert "raise NotImplementedError" in (TEMPLATE / "labs" / lab / "solution.py").read_text()
    for forbidden in ("pull_request_target", "secrets.", "permissions: write", "contents: write"):
        assert forbidden not in workflow
    assert "persist-credentials: false" in workflow and "--noconftest" in workflow


def run_template(tmp_path, source):
    shutil.copy(TEMPLATE / "pytest.ini", tmp_path / "pytest.ini")
    for lab in CODE_LABS:
        folder = tmp_path / "labs" / lab
        folder.mkdir(parents=True)
        shutil.copy(TEMPLATE / "labs" / lab / "test_lab.py", folder / "test_lab.py")
        shutil.copy(source(lab), folder / "solution.py")
    report = tmp_path / "report.xml"
    subprocess.run(
        [sys.executable, "-I", "-m", "pytest", "-c", "pytest.ini", "--noconftest", "-q"]
        + ["-p", "no:cacheprovider", f"--junitxml={report}", "labs"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=600,
    )
    results = {}
    for case in ElementTree.parse(report).getroot().iter("testcase"):
        lab = case.get("classname").split(".")[1]
        passed = not any(child.tag in ("failure", "error", "skipped") for child in case)
        results.setdefault(lab, []).append(passed)
    return results


@pytest.mark.parametrize("variant", ["starter", "reference"])
def test_code_labs_fail_as_shipped_and_pass_with_reviewed_reference(tmp_path, variant):
    pytest.importorskip("moto")
    source = (
        (lambda lab: TEMPLATE / "labs" / lab / "solution.py")
        if variant == "starter"
        else (lambda lab: ROOT / "tests" / "lab_reference" / f"{lab}.py")
    )
    results = run_template(tmp_path, source)
    assert {lab: len(cases) for lab, cases in results.items()} == EXPECTED
    for lab, cases in results.items():
        assert all(cases) if variant == "reference" else not any(cases), lab


@pytest.mark.parametrize(
    "counts,expected,ok",
    [
        ({"tests": 3}, 3, True),
        ({"tests": 2}, 3, False),
        ({"tests": 3, "skipped": 1}, 3, False),
        ({"tests": 3, "failures": 1}, 3, False),
        ({"tests": 3, "errors": 1}, 3, False),
    ],
)
def test_protected_report_checker_requires_exact_clean_counts(tmp_path, counts, expected, ok):
    attributes = " ".join(f'{key}="{value}"' for key, value in counts.items())
    report = tmp_path / "report.xml"
    report.write_text(f'<testsuites><testsuite name="pytest" {attributes}></testsuite></testsuites>')
    result = subprocess.run(
        [sys.executable, "-I", str(TEMPLATE / ".github" / "check_report.py"), str(report), str(expected)],
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is ok


# Gate, assignment and learner commands (in-memory harness) ------------------------------------


def s3_week(
    h, *, labs_enabled=True, minutes=30, delivered=True, required=True, lab_id="s3-private-presigned"
):
    now = h.clock.now
    journey = shared_journey(now)
    plan = journey.plans["plan-test"]
    plan.labs_enabled, plan.minutes = labs_enabled, minutes
    for index, day in enumerate(plan.sessions):
        day.topic_id = S3
        day.lesson_key = f"lesson:{index}"
        h.repo.state.lessons[day.lesson_key] = {
            "topic": TOPICS[S3][1],
            "date": day.date.isoformat(),
            "delivered_at": now.isoformat() if delivered else None,
        }
    h.repo.state.journey = journey
    h.repo.state.profile = Profile(**PROFILE)
    item = LabAssignment(
        id="lab-a",
        lab_id=lab_id,
        lesson_key="lesson:0",
        plan_id=plan.id,
        required=required,
        token=TOKEN,
        assigned_date=now.date(),
    )
    h.repo.state.labs[item.id] = item
    return plan, item


def sunday_review(h):
    h.clock.now = datetime(2026, 10, 4, 10, tzinfo=IST)
    h.repo.enqueue("review:" + uuid4().hex, {"type": "schedule", "kind": "review", "date": "2026-10-04"})
    h.runtime.recover(media=False)


def pass_scenario(h, item_id, *, correct=4):
    callback(h, f"lab:{item_id}:scenario")
    attempt_id = h.repo.state.active_lab
    for step in range(4):
        order = h.repo.state.lab_attempts[attempt_id].order[step]
        choice = order.index(0) if step < correct else order.index(1)
        callback(h, f"ls:{attempt_id}:{step}:{choice}")
    return attempt_id


@pytest.mark.parametrize("grandfathered", [False, True])
def test_approved_lesson_assigns_required_lab_and_grandfathered_plans_get_none(harness, grandfathered):
    h = harness
    h.clock.now = datetime(2026, 9, 28, 8, tzinfo=IST)
    from test_flows import READINESS
    from test_journey import setup

    setup(h)
    for index in range(4):
        command(h, f"Actual diagnostic answer {index}")
    draft = proposal()
    for day in draft["sessions"]:
        day["topic_id"] = S3
    h.ai.responses.extend([READINESS, draft])
    command(h, "Fifth actual answer")
    ident = h.repo.state.journey.proposed_id
    assert h.repo.state.journey.plans[ident].labs_enabled
    assert "Hands-on labs: 1 required" in "\n".join(texts(h))
    if grandfathered:
        # Plans approved before labs existed deserialize with labs_enabled=False.
        h.repo.state.journey.plans[ident].labs_enabled = False
    callback(h, f"plan:{ident}:now")
    state = h.repo.state
    assert state.lessons
    if grandfathered:
        assert not state.labs and not any(text.startswith("HANDS-ON LAB") for text in queued(h))
        assert pending_required(state) == []
        return
    [item] = state.labs.values()
    assert item.lab_id == "s3-private-presigned" and item.required and item.plan_id == ident
    assert item.lesson_key == state.journey.plans[ident].sessions[0].lesson_key
    lab_message = next(text for text in queued(h) if text.startswith("HANDS-ON LAB"))
    assert "REQUIRED LAB" in lab_message and item.token in lab_message
    assert "Quizzes are sent whether or not you finish labs" in lab_message
    assert required_quota(15) == required_quota(30) == 1 and required_quota(45) == required_quota(60) == 2
    assert pending_required(state) == [item]


def test_sunday_review_carries_required_lab_and_prepares_next_week(harness):
    h = harness
    _, item = s3_week(h)
    h.ai.responses.append(proposal())
    sunday_review(h)
    state = h.repo.state
    j = state.journey
    # Nothing waits for the lab: it carries forward and next week's proposal is prepared.
    assert j.stage == "ready" and j.proposed_id and j.lab_gate_since is None
    assert state.labs["lab-a"].carried_at is not None and state.labs["lab-a"].status == "pending"
    assert any("Your week" in text for text in texts(h))
    assert any("carried forward: Private S3" in text for text in texts(h))
    assert any("starts automatically" in text for text in texts(h))
    view = lab_view(state, h.runtime.config, h.clock.now)
    assert not view["gate"]["blocked"] and view["gate"]["required_pending"] == 1
    assert not view["items"][0]["blocking"] and view["items"][0]["carried"]
    assert view["items"][0]["token"] == TOKEN and not view["carry_available"]
    assert admin_counts(state, True) == {"required": 1, "verified": 0, "pending": 1, "gate_blocked": False}

    calls = len(h.ai.calls)
    pass_scenario(h, item.id)
    state = h.repo.state
    assert state.labs["lab-a"].status == "verified" and state.labs["lab-a"].route == "scenario"
    assert state.focus is None and state.active_lab is None
    # Verifying a carried lab never re-plans or replaces the waiting proposal.
    assert len(h.ai.calls) == calls and state.journey.stage == "ready"
    assert h.clock.now.date() in state.activity
    assert any("Lab scenario passed: 4/4" in text for text in texts(h))
    # Four step answers are unique receipts, and an old button cannot regrade.
    assert sum(key[1].startswith("step-") for key in h.repo.answer_keys) == 4


def test_failed_scenario_attempts_stale_buttons_cancel_and_quiz_interrupts(harness):
    h = harness
    _, item = s3_week(h)
    attempt = pass_scenario(h, item.id, correct=2)
    state = h.repo.state
    assert state.labs["lab-a"].status == "needs_fix" and state.lab_attempts[attempt].status == "failed"
    assert "You need 3/4" in texts(h)[-1] and "2 attempts left today" in texts(h)[-1]
    before = set(h.repo.answer_keys)
    callback(h, f"ls:{attempt}:0:0")
    assert "stale" in texts(h)[-1] and h.repo.answer_keys == before
    pass_scenario(h, item.id, correct=0)
    pass_scenario(h, item.id, correct=1)
    callback(h, f"lab:{item.id}:scenario")
    assert "three scenario attempts" in texts(h)[-1] and h.repo.state.focus is None

    h.clock.now += timedelta(days=1)
    callback(h, f"lab:{item.id}:scenario")
    attempt = h.repo.state.active_lab
    order = h.repo.state.lab_attempts[attempt].order[0]
    command(h, "ABCD"[order.index(0)])
    assert h.repo.state.lab_attempts[attempt].answers == [True]
    command(h, "/cancel")
    assert h.repo.state.focus is None and h.repo.state.lab_attempts[attempt].status == "cancelled"

    callback(h, f"lab:{item.id}:scenario")
    attempt = h.repo.state.active_lab
    h.ai.responses.append(question_set(5))
    h.repo.state.lessons["lesson:0"]["date"] = h.clock.now.date().isoformat()
    h.repo.state.journey.plans["plan-test"].sessions[0].date = h.clock.now.date()
    h.clock.now = h.clock.now.replace(hour=18)
    h.repo.enqueue("quiz:1", {"type": "schedule", "kind": "quiz", "date": h.clock.now.date().isoformat()})
    h.runtime.recover(media=False)
    state = h.repo.state
    assert state.lab_attempts[attempt].status == "cancelled" and state.focus == "assessment"
    assert any("lab scenario was paused" in text for text in texts(h))


def test_friday_quiz_is_sent_with_lab_reminder_and_kill_switch_releases_gate(harness):
    h = harness
    h.clock.now = datetime(2026, 10, 2, 18, tzinfo=IST)
    plan, _ = s3_week(h)
    plan.sessions[4].date = h.clock.now.date()
    h.repo.state.lessons["lesson:4"]["date"] = h.clock.now.date().isoformat()
    h.ai.responses.append(question_set(5))
    h.repo.enqueue("quiz", {"type": "schedule", "kind": "quiz", "date": "2026-10-02"})
    h.runtime.recover(media=False)
    reminder = next(i for i, text in enumerate(texts(h)) if text.startswith("Reminder: Private S3"))
    assert "does not depend on it" in texts(h)[reminder]
    assert h.repo.state.focus == "assessment" and texts(h)[reminder + 1 :]

    h.runtime.config = replace(h.runtime.config, labs_enabled=False)
    h.ai.responses.append(proposal())
    sunday_review(h)
    assert h.repo.state.journey.stage == "ready"
    assert not h.repo.state.journey.plans[h.repo.state.journey.proposed_id].labs_enabled
    command(h, "/lab s3-private-presigned")
    assert "temporarily turned off" in texts(h)[-1]


def test_labcarry_explains_automatic_carry_and_carried_labs_never_block(harness):
    h = harness
    _, item = s3_week(h, delivered=False)
    command(h, "/labcarry")
    assert "carry forward automatically" in texts(h)[-1] and "/lab s3-private-presigned" in texts(h)[-1]
    for record in h.repo.state.lessons.values():
        record["delivered_at"] = h.clock.now.isoformat()
    h.ai.responses.append(proposal())
    sunday_review(h)
    state = h.repo.state
    assert state.labs["lab-a"].carried_at and state.journey.stage == "ready"
    new = state.journey.proposed_id
    callback(h, f"plan:{new}:approve")
    state = h.repo.state
    assert state.journey.active_id == new
    assert [a.id for a in pending_required(state)] == ["lab-a"]  # Carried work stays visible this week.
    carried_at = state.labs["lab-a"].carried_at
    for index, day in enumerate(state.journey.plans[new].sessions):
        day.lesson_key = f"later:{index}"
        state.lessons[day.lesson_key] = {"topic": "x", "date": "2026-10-09", "delivered_at": "2026-10-09"}
    h.ai.responses.append(proposal())
    h.clock.now = datetime(2026, 10, 11, 10, tzinfo=IST)
    h.repo.enqueue("review:second", {"type": "schedule", "kind": "review", "date": "2026-10-11"})
    h.runtime.recover(media=False)
    state = h.repo.state
    # A lab carried twice still never blocks, and its original carry time is kept.
    assert state.journey.stage == "ready" and state.labs["lab-a"].carried_at == carried_at


def test_optional_labs_list_and_unknown_or_verified_labs_do_not_run_checks(harness):
    h = harness
    command(h, "/labs")
    assert "No labs assigned yet" in texts(h)[-1] and "iam-least-privilege" in texts(h)[-1]
    command(h, "/lab iam-least-privilege")
    [item] = h.repo.state.labs.values()
    assert not item.required and "OPTIONAL LAB" in texts(h)[-1]
    command(h, "/lab not-a-lab")
    assert "Unknown lab" in texts(h)[-1]
    command(h, "/submitlab iam-least-privilege")
    assert "Use /submitlab" in texts(h)[-1]
    command(h, f"/submitlab iam-least-privilege {SIGNED}")
    assert "not an accepted URL" in texts(h)[-1]
    assert not h.repo.cache_data


class FakeChecker:
    def __init__(self, code="verified", cleanup="cleaned"):
        self.code, self.cleanup_code, self.calls = code, cleanup, []

    def aws(self, route, url, token, budget):
        self.calls.append(("aws", url, token))
        return {"code": self.code, "checks": ["https", "token"]}

    def github(self, lab, protected, url, token, budget):
        self.calls.append(("github", url, token, protected))
        return {"code": self.code, "checks": ["public-repo"]}

    def cleanup(self, route, url, token, budget):
        self.calls.append(("cleanup", url, token))
        return {"code": self.cleanup_code}


def test_telegram_submit_cleanup_rate_limit_and_link_scrub(harness):
    h = harness
    _, item = s3_week(h)
    checker = h.runtime.labs = FakeChecker(code="token_missing")
    key = command(h, f"/submitlab s3-private-presigned {SIGNED}")
    assert "did not contain your lab token" in texts(h)[-1]
    assert h.repo.state.labs["lab-a"].status == "needs_fix"
    assert h.repo.jobs[key]["payload"]["text"] == "/submitlab"
    checker.code = "verified"
    command(h, f"/submitlab s3-private-presigned {SIGNED}")
    state = h.repo.state
    assert state.labs["lab-a"].status == "verified" and state.labs["lab-a"].cleanup == "reminder"
    assert state.labs["lab-a"].url_digest == url_digest(TOKEN, canonical_link(SIGNED))
    assert SIGNED not in json.dumps(state.model_dump(mode="json"))
    assert "Delete the resources now" in texts(h)[-1]
    command(h, "/labcleanup s3-private-presigned https://other.s3.amazonaws.com/skillcoach-token.txt")
    assert "not the link you verified" in texts(h)[-1]
    other_signature = SIGNED.replace("abc123", "def456")
    command(h, f"/labcleanup s3-private-presigned {other_signature}")
    assert h.repo.state.labs["lab-a"].cleanup == "confirmed"
    assert [call[0] for call in checker.calls] == ["aws", "aws", "cleanup"]
    assert all(TOKEN == call[2] for call in checker.calls)
    for job in h.repo.jobs.values():
        assert "amazonaws" not in json.dumps(job["payload"])

    h.repo.state.labs["lab-a"].status = "needs_fix"
    h.repo.state.lab_checks = [h.clock.now] * 12
    command(h, f"/submitlab s3-private-presigned {SIGNED}")
    assert "limit of 12 lab checks" in texts(h)[-1] and len(checker.calls) == 3


def test_check_result_is_cached_so_a_retry_never_rechecks(harness, monkeypatch):
    from skillcoach import lab_flow

    h = harness
    s3_week(h)
    checker = h.runtime.labs = FakeChecker()
    original = lab_flow.LabFlow.verified
    failures = [ExternalError("fake_after_check")]

    def flaky(self, *args):
        if failures:
            raise failures.pop()
        return original(self, *args)

    monkeypatch.setattr(lab_flow.LabFlow, "verified", flaky)
    key = command(h, f"/submitlab s3-private-presigned {SIGNED}")
    assert h.repo.jobs[key]["status"] == "failed" and h.repo.state.labs["lab-a"].status == "pending"
    command(h, "/retry")
    assert h.repo.state.labs["lab-a"].status == "verified" and len(checker.calls) == 1
    assert len(h.repo.state.lab_checks) == 1


def test_unpause_after_a_paused_sunday_prepares_the_missed_week_plan(harness):
    h = harness
    s3_week(h)
    command(h, "/pause")
    sunday_review(h)
    assert h.repo.state.journey.stage == "active" and not h.repo.state.journey.proposed_id
    assert not h.ai.calls
    h.ai.responses.append(proposal())
    command(h, "/unpause")
    j = h.repo.state.journey
    assert j.stage == "ready" and j.proposed_id and j.lab_gate_since is None
    assert any("starts automatically" in text for text in texts(h))


def saturday_assessment_left_open(h):
    h.clock.now = datetime(2026, 10, 3, 9, tzinfo=IST)
    h.ai.responses.append(question_set(10))
    h.repo.enqueue("weekly:" + uuid4().hex, {"type": "schedule", "kind": "weekly", "date": "2026-10-03"})
    h.runtime.recover(media=False)
    assert h.repo.state.focus == "assessment"
    return h.repo.state.active_assessment


def test_open_assessment_never_blocks_next_week_and_monday_starts_it(harness):
    h = harness
    s3_week(h)
    assessment = saturday_assessment_left_open(h)
    h.ai.responses.append(proposal())
    sunday_review(h)
    state = h.repo.state
    assert state.journey.stage == "ready" and state.journey.proposed_id
    # The proposal waits; the unfinished assessment and its focus are untouched.
    assert state.focus == "assessment" and state.active_assessment == assessment
    assert state.assessments[assessment].status == "active"
    callback(h, f"plan:{state.journey.proposed_id}:approve")
    assert "Finish or /cancel the current question" in texts(h)[-1]
    proposed = h.repo.state.journey.proposed_id
    h.ai.responses.append(core_guide())
    h.clock.now = datetime(2026, 10, 5, 9, tzinfo=IST)
    h.repo.enqueue("lesson:monday", {"type": "schedule", "kind": "lesson", "date": "2026-10-05"})
    h.runtime.recover(media=False)
    j = h.repo.state.journey
    assert j.active_id == proposed and j.stage == "active" and j.plans[proposed].auto_started_at
    assert j.plans[proposed].sessions[0].date.isoformat() == "2026-10-05"


def test_kill_switch_plans_the_next_week_without_labs(harness):
    h = harness
    s3_week(h)
    h.runtime.config = replace(h.runtime.config, labs_enabled=False)
    h.ai.responses.append(proposal())
    sunday_review(h)
    j = h.repo.state.journey
    assert j.lab_gate_since is None and j.stage == "ready" and j.proposed_id
    assert not j.plans[j.proposed_id].labs_enabled
    assert h.repo.state.labs["lab-a"].carried_at is None


def test_scenario_finishing_after_code_verification_keeps_the_verified_evidence(harness):
    h = harness
    _, item = s3_week(h)
    callback(h, f"lab:{item.id}:scenario")
    attempt = h.repo.state.active_lab
    h.runtime.labs = FakeChecker()
    command(h, f"/submitlab s3-private-presigned {SIGNED}")
    verified = h.repo.state.labs["lab-a"].model_dump()
    assert (
        verified["status"] == "verified" and verified["route"] == "aws" and verified["cleanup"] == "reminder"
    )
    assert h.repo.state.focus == "lab"
    for step in range(4):
        order = h.repo.state.lab_attempts[attempt].order[step]
        callback(h, f"ls:{attempt}:{step}:{order.index(1)}")
    state = h.repo.state
    assert state.lab_attempts[attempt].status == "failed" and state.focus is None
    assert state.labs["lab-a"].model_dump() == verified
    assert "was already verified" in texts(h)[-1]


def test_worker_workflow_receives_every_labs_setting():
    import re

    keys = set(re.findall(r'"(LABS_[A-Z_]+)"', (ROOT / "skillcoach" / "config.py").read_text()))
    assert keys == {"LABS_ENABLED", "LABS_TEMPLATE_REPO", "LABS_GITHUB_TOKEN"}
    worker = (ROOT / ".github" / "workflows" / "coach-job.yml").read_text()
    example = (ROOT / ".env.example").read_text()
    for key in keys:
        assert f"          {key}: ${{{{ " in worker, key
        assert f"{key}=" in example, key
    assert "LABS_ENABLED: ${{ vars.LABS_ENABLED || 'true' }}" in worker
    assert "LABS_GITHUB_TOKEN: ${{ secrets.LABS_GITHUB_TOKEN }}" in worker


# Evidence checker with fake HTTP/DNS --------------------------------------------------------


class Raw:
    def __init__(self, body, size=4096, clock=None, step=0):
        self.body, self.size, self.clock, self.step, self.reads = body, size, clock, step, 0

    def read1(self, amt, decode_content=False):
        assert decode_content is False
        self.reads += 1
        if self.clock is not None:
            self.clock[0] += self.step
        chunk, self.body = self.body[: min(amt, self.size)], self.body[min(amt, self.size) :]
        return chunk


class Response:
    def __init__(self, status=200, body=b"", headers=None, raw=None):
        self.status_code, self.body, self.headers = status, body, headers or {}
        self.raw = raw or Raw(body)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Session:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def request(self, method, url, **kwargs):
        assert method == "GET" and kwargs["allow_redirects"] is False and kwargs["stream"] is True
        self.calls.append((url, kwargs))
        value = self.routes[url]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, (dict, list)):
            return Response(200, json.dumps(value).encode())
        return value


def public_dns(host, port, type):
    return [(2, 1, 6, "", ("52.95.1.10", 443))]


def checker(config, routes, resolver=public_dns):
    session = Session(routes)
    return LabChecker(config, session=session, resolver=resolver), session


UNSIGNED = SIGNED.split("?")[0]
S3_ROUTE = LABS["s3-private-presigned"].aws


def test_aws_link_checks_signed_access_unsigned_denial_and_rejections(config):
    ok, session = checker(config, {SIGNED: Response(200, TOKEN.encode()), UNSIGNED: Response(403, b"")})
    assert ok.aws(S3_ROUTE, SIGNED, TOKEN, Budget(20))["code"] == "verified"
    assert session.calls[0][1]["headers"]["User-Agent"].startswith("SkillCoach")
    public, _ = checker(
        config, {SIGNED: Response(200, TOKEN.encode()), UNSIGNED: Response(200, TOKEN.encode())}
    )
    assert public.aws(S3_ROUTE, SIGNED, TOKEN, Budget(20))["code"] == "still_public"
    cases = {
        UNSIGNED: "not_signed",
        SIGNED.replace("https", "http", 1): "url_not_allowed",
        SIGNED.replace("skillcoach-lab.s3", "skillcoach-lab.s3.evil.com", 1): "url_not_allowed",
        SIGNED.replace("https://", "https://user@", 1): "url_not_allowed",
        SIGNED.replace(".com/", ".com:8443/", 1): "url_not_allowed",
        SIGNED + "#fragment": "url_not_allowed",
        SIGNED + " ": "url_not_allowed",
    }
    for url, code in cases.items():
        assert ok.aws(S3_ROUTE, url, TOKEN, Budget(20))["code"] == code, url
    private, session = checker(config, {}, lambda *a, **k: [(2, 1, 6, "", ("10.0.0.5", 443))])
    assert private.aws(S3_ROUTE, SIGNED, TOKEN, Budget(20))["code"] == "private_address"
    assert not session.calls

    def missing(*args, **kwargs):
        raise OSError("dns")

    assert checker(config, {}, missing)[0].aws(S3_ROUTE, SIGNED, TOKEN, Budget(20))["code"] == "unreachable"
    for response, code in (
        (Response(302, b"", {"Location": "https://example.com"}), "redirect_not_allowed"),
        (Response(200, b"x" * 70000), "too_large"),
        (Response(200, b"no token"), "token_missing"),
        (Response(500, b""), "http_status"),
    ):
        assert checker(config, {SIGNED: response})[0].aws(S3_ROUTE, SIGNED, TOKEN, Budget(20))["code"] == code
    import requests

    broken = checker(config, {SIGNED: requests.ConnectionError("down")})[0]
    assert broken.aws(S3_ROUTE, SIGNED, TOKEN, Budget(20))["code"] == "unreachable"


def test_cloudfront_api_and_lambda_routes_and_cleanup(config):
    front = LABS["cloudfront-private-origin"].aws
    url = "https://d1234567890abc.cloudfront.net/skillcoach-token.txt"
    hit = Response(200, TOKEN.encode(), {"X-Cache": "Hit from cloudfront"})
    assert checker(config, {url: hit})[0].aws(front, url, TOKEN, Budget(20))["code"] == "verified"
    miss = Response(200, TOKEN.encode(), {})
    assert checker(config, {url: miss})[0].aws(front, url, TOKEN, Budget(20))["code"] == "not_cloudfront"
    api = LABS["api-gateway-health"].aws
    base = "https://abcde12345.execute-api.ap-south-1.amazonaws.com/prod"
    assert checker(config, {})[0].aws(api, base + "/items", TOKEN, Budget(20))["code"] == "wrong_path"
    lam = LABS["lambda-function-url"].aws
    lam_url = "https://abcdefghijklmnopqrstuvwxyz012345.lambda-url.ap-south-1.on.aws/"
    assert checker(config, {lam_url: Response(403)})[0].cleanup(lam, lam_url, TOKEN, Budget(20)) == {
        "code": "cleaned",
        "checks": ["token-not-served"],
    }
    pending = checker(config, {lam_url: Response(200, TOKEN.encode())})[0]
    assert pending.cleanup(lam, lam_url, TOKEN, Budget(20))["code"] == "cleanup_pending"

    def gone(*args, **kwargs):
        raise OSError("NXDOMAIN")

    assert checker(config, {}, gone)[0].cleanup(lam, lam_url, TOKEN, Budget(20))["code"] == "cleaned"
    deleted = {SIGNED: Response(403), UNSIGNED: Response(404, b"<Code>NoSuchBucket</Code>")}
    assert checker(config, deleted)[0].cleanup(S3_ROUTE, SIGNED, TOKEN, Budget(20))["code"] == "cleaned"
    exists = {SIGNED: Response(403), UNSIGNED: Response(403, b"<Code>AccessDenied</Code>")}
    assert checker(config, exists)[0].cleanup(S3_ROUTE, SIGNED, TOKEN, Budget(20))["code"] == "bucket_exists"


def test_slow_drip_body_stops_at_wall_clock_deadline_not_chunk_boundaries(config):
    import urllib3

    clock = [1000.0]
    drip = Raw(TOKEN.encode() * 50, size=1, clock=clock, step=2.0)
    lab_checker = LabChecker(
        config,
        session=Session({SIGNED: Response(200, raw=drip)}),
        resolver=public_dns,
        clock=lambda: clock[0],
    )
    assert lab_checker.aws(S3_ROUTE, SIGNED, TOKEN, Budget(20))["code"] == "unreachable"
    assert drip.reads <= 6 and clock[0] - 1000.0 <= 12
    git_clock = [1000.0]
    slow = Raw(json.dumps({"private": False}).encode(), size=1, clock=git_clock, step=2.0)
    routes = github_routes(routes={API: Response(200, raw=slow)})
    git = LabChecker(config, session=Session(routes), resolver=public_dns, clock=lambda: git_clock[0])
    assert git.github(LAB, TEMPLATE_BLOBS[LAB.id], "https://github.com/learner/labs", TOKEN, Budget(20)) == {
        "code": "unreachable"
    }
    assert slow.reads <= 6

    class Broken(Raw):
        def read1(self, amt, decode_content=False):
            raise urllib3.exceptions.ReadTimeoutError(None, "x", "read timed out")

    broken = Response(200, raw=Broken(b""))
    assert (
        checker(config, {SIGNED: broken})[0].aws(S3_ROUTE, SIGNED, TOKEN, Budget(20))["code"] == "unreachable"
    )


def test_bodies_are_read_raw_then_decoded_with_a_size_cap(config):
    import gzip
    import zlib

    packed = Response(200, gzip.compress(TOKEN.encode()), {"Content-Encoding": "gzip"})
    ok, session = checker(config, {SIGNED: packed, UNSIGNED: Response(403)})
    assert ok.aws(S3_ROUTE, SIGNED, TOKEN, Budget(20))["code"] == "verified"
    assert session.calls[0][1]["headers"]["Accept-Encoding"] == "identity"
    deflated = {SIGNED: Response(200, zlib.compress(TOKEN.encode()), {"content-encoding": "deflate"})}
    deflated[UNSIGNED] = Response(403)
    assert checker(config, deflated)[0].aws(S3_ROUTE, SIGNED, TOKEN, Budget(20))["code"] == "verified"
    bomb = Response(200, gzip.compress(b"0" * 10_000_000), {"Content-Encoding": "gzip"})
    assert len(bomb.body) < 65536
    assert checker(config, {SIGNED: bomb})[0].aws(S3_ROUTE, SIGNED, TOKEN, Budget(20))["code"] == "too_large"
    for response in (
        Response(200, TOKEN.encode(), {"Content-Encoding": "br"}),
        Response(200, b"not gzip", {"Content-Encoding": "gzip"}),
        Response(200, gzip.compress(TOKEN.encode())[:-8], {"Content-Encoding": "gzip"}),
    ):
        result = checker(config, {SIGNED: response})[0].aws(S3_ROUTE, SIGNED, TOKEN, Budget(20))
        assert result["code"] == "unsupported_encoding"
    # An unsigned 200 is public even when its body cannot be read.
    hidden = {
        SIGNED: Response(200, TOKEN.encode()),
        UNSIGNED: Response(200, b"x", {"Content-Encoding": "br"}),
    }
    assert checker(config, hidden)[0].aws(S3_ROUTE, SIGNED, TOKEN, Budget(20))["code"] == "still_public"
    routes = github_routes()
    routes[API] = Response(200, gzip.compress(json.dumps(routes[API]).encode()), {"Content-Encoding": "gzip"})
    lab_checker, session = checker(config, routes)
    result = lab_checker.github(
        LAB, TEMPLATE_BLOBS[LAB.id], "https://github.com/learner/labs", TOKEN, Budget(20)
    )
    assert result["code"] == "verified"
    assert session.calls[0][1]["headers"]["Accept-Encoding"] == "identity"


@pytest.fixture
def loopback_http(monkeypatch):
    """Only the in-process loopback server below may be reached; any other host still fails."""

    def loopback_only(self, request, *args, **kwargs):
        assert urlsplit(request.url).hostname == "127.0.0.1", "Tests must not use live HTTP APIs"
        return REAL_SEND(self, request, *args, **kwargs)

    def loopback_request(self, method, url, *args, **kwargs):
        assert urlsplit(url).hostname == "127.0.0.1", "Tests must not use live HTTP APIs"
        return REAL_REQUEST(self, method, url, *args, **kwargs)

    monkeypatch.setattr("requests.adapters.HTTPAdapter.send", loopback_only)
    monkeypatch.setattr("requests.Session.request", loopback_request)


def drip_server(prefix, drip, interval=0.1):
    import socket
    import threading

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    stop = threading.Event()

    def serve():
        try:
            conn, _ = listener.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(5)
            try:
                conn.recv(65536)
                conn.sendall(prefix)
                # Bounded so a regressed watchdog fails the timing assertion instead of hanging the suite.
                for _ in range(60 if drip else 0):
                    if stop.is_set():
                        break
                    conn.sendall(drip)
                    stop.wait(interval)
            except OSError:
                pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{listener.getsockname()[1]}/token.txt", listener, stop, thread


@pytest.mark.parametrize(
    "prefix,drip",
    [
        (b"HTTP/1.1 200 OK\r\nX-Slow: ", b"a"),
        (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n", b"1"),
        (
            b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: 900000\r\n\r\n"
            + b"\x1f\x8b\x08\x08\x00\x00\x00\x00\x00\x03",
            b"a",
        ),
    ],
    ids=["headers", "chunk-size-line", "gzip-filename"],
)
def test_real_socket_slow_drip_is_cut_at_the_wall_clock_deadline(config, loopback_http, prefix, drip):
    """Per-read timeouts reset on every byte; the Deadline watchdog must end the whole request."""
    import time

    url, listener, stop, thread = drip_server(prefix, drip)
    started = time.monotonic()
    try:
        result = LabChecker(config, seconds=1).fetch(url, Budget(20))
    finally:
        stop.set()
        listener.close()
        thread.join(5)
    assert result == (0, {}, None, "unreachable")
    assert time.monotonic() - started < 3.5


def test_redirect_body_is_never_read_or_decompressed(config, loopback_http):
    """requests' redirect resolver would read and gunzip a 3xx body in full before we could reject it."""
    import gzip
    import tracemalloc

    bomb = gzip.compress(b"0" * 64_000_000)
    prefix = (
        b"HTTP/1.1 302 Found\r\nLocation: https://example.com/\r\nContent-Encoding: gzip\r\n"
        b"Content-Length: %d\r\n\r\n%s" % (len(bomb), bomb)
    )
    url, listener, stop, thread = drip_server(prefix, b"")
    tracemalloc.start()
    try:
        result = LabChecker(config, seconds=2).fetch(url, Budget(20))
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
        stop.set()
        listener.close()
        thread.join(5)
    assert result == (302, {}, None, "redirect_not_allowed")
    assert peak < 16_000_000


def test_real_socket_normal_response_is_unaffected_by_the_watchdog(config, loopback_http):
    body = TOKEN.encode()
    prefix = b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s" % (len(body), body)
    url, listener, stop, thread = drip_server(prefix, b"")
    try:
        status, _, text, problem = LabChecker(config, seconds=2).fetch(url, Budget(20))
    finally:
        stop.set()
        listener.close()
        thread.join(5)
    assert (status, text, problem) == (200, TOKEN, None)


API = "https://api.github.com/repos/learner/labs"
LAB = LABS["iam-least-privilege"]


def github_routes(**changes):
    blobs = {path: sha for path, sha in TEMPLATE_BLOBS[LAB.id].items()}
    blobs[f".skillcoach/{LAB.id}.token"] = blob_sha((TOKEN + "\n").encode())
    blobs.update(changes.pop("blobs", {}))
    run = {
        "id": 7,
        "head_sha": "c1",
        "path": WORKFLOW_PATH,
        "event": "push",
        "status": "completed",
        "run_attempt": 1,
        **changes.pop("run", {}),
    }
    routes = {
        API: {"private": False, "default_branch": "main"},
        API + "/branches/main": {"commit": {"sha": "c1", "commit": {"tree": {"sha": "t1"}}}},
        API + "/git/trees/t1?recursive=1": {
            "truncated": False,
            "tree": [{"path": p, "type": "blob", "sha": s} for p, s in blobs.items() if s],
        },
        API + "/actions/runs?head_sha=c1&per_page=30": {"workflow_runs": [run]},
        API + "/actions/runs/7/jobs?per_page=50": {
            "jobs": [{"name": f"lab-{LAB.id}", "conclusion": changes.pop("conclusion", "success")}]
        },
    }
    routes.update(changes.pop("routes", {}))
    return routes


def github(config, url="https://github.com/learner/labs", **changes):
    lab_checker, session = checker(config, github_routes(**changes))
    return lab_checker.github(LAB, TEMPLATE_BLOBS[LAB.id], url, TOKEN, Budget(20))["code"], session


def test_github_code_lab_checks_protected_files_token_run_and_limits(config):
    code, session = github(config)
    assert code == "verified" and "Authorization" not in session.calls[0][1]["headers"]
    code, session = github(replace(config, labs_github_token="read-only-token"))
    assert session.calls[0][1]["headers"]["Authorization"] == "Bearer read-only-token"
    assert github(config, url="https://github.com/learner/labs.git/")[0] == "verified"
    for url in (
        "https://github.com/learner/..",
        "https://gist.github.com/a/b",
        "https://github.com/a/b/tree/x",
    ):
        assert github(config, url=url)[0] == "url_not_allowed"
    test_file = f"labs/{LAB.id}/test_lab.py"
    assert github(config, blobs={test_file: "0" * 40})[0] == "tests_modified"
    assert github(config, blobs={"requirements-lab.txt": "0" * 40})[0] == "tests_modified"
    assert github(config, blobs={WORKFLOW_PATH: "0" * 40})[0] == "workflow_modified"
    assert (
        github(config, blobs={f".skillcoach/{LAB.id}.token": blob_sha(b"SC-OTHER")})[0]
        == "token_file_missing"
    )
    assert github(config, run={"status": "in_progress"})[0] == "run_in_progress"
    assert github(config, run={"event": "pull_request"})[0] == "run_missing"
    assert github(config, run={"path": ".github/workflows/other.yml"})[0] == "run_missing"
    assert github(config, conclusion="failure")[0] == "run_failed"
    assert github(config, routes={API: {"private": True}})[0] == "repo_not_found"
    assert github(config, routes={API: Response(404)})[0] == "repo_not_found"
    assert github(config, routes={API: Response(403)})[0] == "repo_not_found"
    busy = Response(403, b"", {"x-ratelimit-remaining": "0"})
    assert github(config, routes={API: busy})[0] == "github_busy"
    assert github(config, routes={API: Response(429)})[0] == "github_busy"
    assert github(config, routes={API + "/git/trees/t1?recursive=1": {"truncated": True}})[0] == "too_large"
    assert token_blob_shas(TOKEN) >= {blob_sha(TOKEN.encode()), blob_sha((TOKEN + "\r\n").encode())}


def test_learner_and_admin_views_never_expose_links_digests_or_other_tokens(harness):
    from skillcoach.export import public_export
    from skillcoach.journey import safe_learning_view

    h = harness
    _, item = s3_week(h)
    item.url_digest, item.status, item.route, item.cleanup = "d" * 64, "verified", "aws", "reminder"
    item.verified_at = h.clock.now
    view = json.dumps(lab_view(h.repo.state, h.runtime.config, h.clock.now))
    assert "d" * 64 not in view and TOKEN not in view  # Verified labs no longer need the token.
    h.repo.state.journey.consent_at = h.clock.now
    shared = json.dumps(safe_learning_view(h.repo.state, h.clock.now))
    exported = json.dumps(public_export(h.repo.state, h.clock.now))
    for private in (TOKEN, "d" * 64, "s3-private-presigned", "amazonaws"):
        assert private not in shared and private not in exported


# Real PostgreSQL: dashboard submission, isolation and link scrubbing ------------------------


@pytest.fixture
def lab_api(pg_repo, config):
    from test_dashboard import signed
    from test_multiuser import Bot

    from skillcoach.web import create_app

    bot = Bot(pg_repo, config)
    learners = {}
    for user in (101, 102):
        scoped = bot.join(user)

        def seed(state, user=user):
            state.profile = Profile(**PROFILE)
            state.journey = shared_journey(datetime.now(IST))
            state.labs["lab-" + str(user)] = LabAssignment(
                id="lab-" + str(user),
                lab_id="iam-least-privilege",
                required=True,
                token=f"SC-{user}A-BCDE",
                assigned_date=datetime.now(IST).date(),
            )

        bot.save(scoped, seed)
        learners[user] = scoped
    bot.runtime.clock = lambda: datetime.now(IST) + timedelta(seconds=2)
    bot.runtime.labs = FakeChecker()
    client = create_app(bot.runtime).test_client()

    def headers(user):
        raw = signed(user, config.telegram_token, int(bot.runtime.clock().timestamp()))
        response = client.post("/app/data", base_url="https://localhost", json={"init_data": raw})
        assert response.status_code == 200
        return {
            "Origin": "https://localhost",
            "X-Telegram-Init-Data": raw,
            "X-CSRF-Token": response.json["document_csrf"],
        }, response.json

    return bot, learners, client, headers


def submit(client, headers, assignment, ident=None, url="https://github.com/learner/labs"):
    return client.post(
        "/app/labs/submit",
        base_url="https://localhost",
        headers=headers,
        json={"request_id": ident or str(uuid4()), "assignment_id": assignment, "url": url},
    )


@pytest.mark.postgres
def test_dashboard_lab_submit_is_durable_idempotent_isolated_and_scrubbed(lab_api):
    bot, learners, client, headers = lab_api
    first, data = headers(101)
    assert data["labs"]["items"][0]["id"] == "lab-101" and data["labs"]["items"][0]["token"] == "SC-101A-BCDE"
    assert "SC-102A-BCDE" not in json.dumps(data)
    other_before = learners[102].read()[1]
    ident = str(uuid4())
    response = submit(client, first, "lab-101", ident)
    assert response.status_code == 200 and response.json == {"queued": True, "duplicate": False}
    state = learners[101].read()[1]
    assert state.labs["lab-101"].status == "verified" and state.labs["lab-101"].route == "code"
    assert bot.runtime.labs.calls[0][2] == "SC-101A-BCDE"
    assert submit(client, first, "lab-101", ident).json == {"queued": True, "duplicate": True}
    assert submit(client, first, "lab-other", ident).status_code == 409
    assert len(bot.runtime.labs.calls) == 1
    assert submit(client, first, "lab-102").status_code == 409  # Another learner's assignment.
    assert learners[102].read()[1] == other_before
    assert submit(client, first, "lab-101").status_code == 409  # Already verified.
    for bad in ({}, {**first, "X-CSRF-Token": "bad"}, {**first, "Origin": "https://attacker.invalid"}):
        assert submit(client, bad, "lab-101").status_code == 403
    for url in ("http://github.com/a/b", "https://github.com/a b", "https://" + "a" * 2050):
        assert submit(client, first, "lab-101", url=url).status_code == 409
    with bot.repo.connection() as conn:
        rows = conn.execute(
            "SELECT payload,status FROM jobs WHERE payload->>'type'='lab' AND learner_id=%s",
            (learners[101].learner_id,),
        ).fetchall()
        assert len(rows) == 1 and rows[0]["status"] == "done" and "url" not in rows[0]["payload"]
        outbox = conn.execute(
            "SELECT body FROM outbox WHERE job_id=%s", (f"labsubmit:{learners[101].learner_id}:{ident}",)
        ).fetchall()
        assert any("Code lab verified" in row["body"].get("text", "") for row in outbox)


@pytest.mark.postgres
def test_dashboard_lab_submit_refuses_busy_revoked_and_kill_switch(lab_api):
    bot, learners, client, headers = lab_api
    second, _ = headers(102)
    scoped = learners[102]
    with bot.repo.connection() as conn:
        conn.execute(
            "INSERT INTO jobs(id,payload,learner_id,access_generation,status,available_at) "
            "SELECT 'busy-lab',%s,id,generation,'pending',now()+interval '1 hour' FROM learners WHERE id=%s",
            (json.dumps({"type": "lab", "action": "submit", "assignment_id": "lab-102"}), scoped.learner_id),
        )
    assert "already queued" in submit(client, second, "lab-102").json["error"]
    with bot.repo.connection() as conn:
        conn.execute("DELETE FROM jobs WHERE id='busy-lab'")
    bot.runtime.config = replace(bot.runtime.config, labs_enabled=False)
    assert "turned off" in submit(client, second, "lab-102").json["error"]
    bot.runtime.config = replace(bot.runtime.config, labs_enabled=True)
    bot.input(bot.config.owner_id, "/revoke " + scoped.learner_id)
    assert submit(client, second, "lab-102").status_code == 403
    assert not bot.runtime.labs.calls


@pytest.mark.postgres
def test_postgres_telegram_submit_scrubs_link_from_job_history(lab_api):
    bot, learners, client, headers = lab_api
    bot.input(101, "/submitlab iam-least-privilege https://github.com/learner/labs")
    with bot.repo.connection() as conn:
        texts_seen = [
            row["text"]
            for row in conn.execute(
                "SELECT payload->>'text' AS text FROM jobs WHERE learner_id=%s AND payload->>'type'='telegram'",
                (learners[101].learner_id,),
            )
        ]
    assert "/submitlab" in texts_seen and not any("github.com" in (t or "") for t in texts_seen)
    assert learners[101].read()[1].labs["lab-101"].status == "verified"
    assert learners[102].read()[1].labs["lab-102"].status == "pending"
