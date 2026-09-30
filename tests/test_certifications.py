import pytest
from test_flows import command, question_set
from test_journey import callback

from skillcoach.catalog import TOPICS
from skillcoach.cert_flow import CertFlow
from skillcoach.certifications import TRACKS, cert_view, readiness
from skillcoach.labs import LABS
from skillcoach.progress import summary


def texts(h):
    return [text for text, _ in h.telegram.messages]


def test_tracks_match_verified_official_structure_and_map_to_real_content():
    expected = {
        "aws-ccp": ("CLF-C02", [24, 30, 34, 12]),
        "aws-saa": ("SAA-C03", [30, 26, 24, 20]),
        "cka": ("CKA (curriculum v1.35)", [10, 30, 15, 25, 20]),
        "ckad": ("CKAD (curriculum v1.35)", [20, 20, 15, 25, 20]),
        "terraform": ("004 (tests Terraform 1.12)", [None] * 8),
        "lfcs": ("LFCS", [25, 25, 20, 20, 10]),
    }
    assert set(TRACKS) == set(expected)
    for ident, (code, weights) in expected.items():
        track = TRACKS[ident]
        assert track.code == code and [d.weight for d in track.domains] == weights
        if weights[0] is not None:
            assert sum(weights) == 100
        assert track.source.startswith("https://")
        assert all(lab in LABS for lab in track.labs)
        for domain in track.domains:
            assert domain.topics and all(topic in TOPICS for topic in domain.topics), domain.name
    assert [d.name for d in TRACKS["cka"].domains] == [
        "Storage",
        "Troubleshooting",
        "Workloads & Scheduling",
        "Cluster Architecture, Installation & Configuration",
        "Services & Networking",
    ]


def test_choose_track_practice_set_and_evidence_based_readiness(harness):
    h = harness
    command(h, "/cert")
    text, buttons = h.telegram.messages[-1]
    assert "Certification prep" in text and len(buttons) == len(TRACKS)
    callback(h, "cert:track:aws-ccp")
    text, buttons = h.telegram.messages[-1]
    assert h.repo.state.cert_track == "aws-ccp"
    assert "Security and Compliance · 30%: Not started" in text and "not predict your exam result" in text
    assert buttons[1] == [
        {"text": "📝 Practise: Security and Compliance", "callback_data": "cert:p:aws-ccp:1"}
    ]
    h.ai.responses.append(question_set(4))
    job = callback(h, "cert:p:aws-ccp:1")
    assert h.repo.jobs[job]["status"] == "failed" and h.repo.state.active_assessment is None
    h.ai.responses.append(question_set(5))
    callback(h, "cert:p:aws-ccp:1")
    session = h.repo.state.assessments[h.repo.state.active_assessment]
    assert session.kind == "cert" and session.source == "aws-ccp:1" and "Original exam-style" in texts(h)[-1]
    assert "never reproduce" in h.ai.calls[-1][0].lower()
    for choice in "BBBBA":
        command(h, f"/q {choice}")
    final, buttons = h.telegram.messages[-1]
    assert "Practice set complete: 4/5" in final and "not a predicted exam result" in final
    assert buttons[0] == [{"text": "📝 Another set on this domain", "callback_data": "cert:p:aws-ccp:1"}]
    domain = readiness(h.repo.state, TRACKS["aws-ccp"], h.clock.now)["domains"][1]
    assert (
        domain["practice_answers"] == 5
        and domain["practice_accuracy"] == 80
        and domain["label"] == "Building"
    )
    # Certification practice never changes quiz evidence, but its misses come back in review.
    assert summary(h.repo.state, h.clock.now)["questions_answered"] == 0
    assert [c.box for c in h.repo.state.review.values()] == [0]
    view = cert_view(h.repo.state, h.clock.now)
    assert view["selected"] == "aws-ccp" and view["track"]["overall"] == 80
    assert view["track"]["domains"][0]["label"] == "Not started"


def test_certification_goal_reaches_plan_and_quiz_prompts(harness):
    h = harness
    h.repo.state.cert_track = "cka"
    h.ai.responses.append({"text": "Answer."})
    command(h, "/ask how do I prepare?")
    assert "Certified Kubernetes Administrator (CKA (curriculum v1.35))" in h.ai.calls[-1][0]
    assert "weakest_domains" in h.ai.calls[-1][0]


def test_deep_links_invalid_buttons_and_leaving_a_track(harness):
    h = harness
    command(h, "/start cert_lfcs")
    assert h.repo.state.cert_track == "lfcs" and "hands-on" in texts(h)[-1]
    h.ai.responses.append(question_set(5))
    command(h, "/start cert_terraform_2")
    session = h.repo.state.assessments[h.repo.state.active_assessment]
    assert session.source == "terraform:2"
    callback(h, "cert:p:aws-ccp:1")
    assert "Finish your current cert questions first" in texts(h)[-1]
    for bad in ("cert:p:aws-ccp:9", "cert:p:nope:0", "cert:track:nope", "cert:bogus"):
        callback(h, bad)
    assert "no longer valid" in texts(h)[-4] and "Unknown track" in texts(h)[-2]
    assert "Unsupported" in texts(h)[-1]
    command(h, "/cert off")
    assert h.repo.state.cert_track is None and "practice history is kept" in texts(h)[-1]


@pytest.mark.parametrize("track", sorted(TRACKS))
def test_every_track_overview_renders_all_domains(harness, track):
    h = harness
    callback(h, f"cert:track:{track}")
    text, buttons = h.telegram.messages[-1]
    assert TRACKS[track].name in text and len(buttons) == len(TRACKS[track].domains) + 1
    assert all(domain.name in text for domain in TRACKS[track].domains)
    assert len(text) < 4000 and CertFlow  # One message, within Telegram's limit.
