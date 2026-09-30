import json
import re
from datetime import date
from urllib.parse import urlsplit

import pytest
from test_flows import command
from test_journey import callback

from skillcoach.catalog import MODULES, TOPICS
from skillcoach.commands import help_text
from skillcoach.dashboard import learner_view
from skillcoach.lab_flow import lab_view
from skillcoach.labs import LABS
from skillcoach.lesson_delivery import page
from skillcoach.models import Draft, LabAssignment
from skillcoach.resources import (
    ACCOUNTS,
    GROUPS,
    NOTICE,
    RESOURCE_VERSION,
    RESOURCES,
    for_topic,
    library_view,
    resources_text,
    search_resources,
)


def test_catalog_is_bounded_attributed_and_uses_only_direct_public_https_links():
    assert len(RESOURCES) == 30
    assert len({r.id for r in RESOURCES}) == len(RESOURCES)
    assert len({r.url for r in RESOURCES}) == len(RESOURCES)
    assert date.fromisoformat(RESOURCE_VERSION) == date(2026, 9, 30)
    modules = {m.id for m in MODULES}
    assert {m for r in RESOURCES for m in r.modules} == modules
    for resource in RESOURCES:
        assert re.fullmatch(r"[a-z0-9-]+", resource.id)
        assert resource.group in GROUPS and resource.account in ACCOUNTS
        assert set(resource.modules) <= modules
        parsed = urlsplit(resource.url)
        assert parsed.scheme == "https" and parsed.hostname and "." in parsed.hostname
        assert not (parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment)
        assert all(
            (resource.provider, resource.summary, resource.start, resource.cost_note, resource.rights_note)
        )
    encoded = json.dumps(library_view()).lower()
    assert "unlimited" not in encoded and "no aws bill risk" not in encoded
    assert "cc by-nc-sa" in encoded and "cc by-nc-nd" in encoded
    assert "does not record completion" in NOTICE
    assert "/resources" in help_text(admin=False)
    assert len(help_text()) <= 3480


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("cloud", "aws-educate"),
        ("DevOps", "kubernetes-basics"),
        ("Linux", "ubuntu-command-line"),
        ("terraform", "terraform-docker"),
        ("s3", "aws-s3-guide"),
        ("aws", "aws-educate"),
        ("gcp", "google-cloud-overview"),
        ("azure", "azure-cloud-concepts"),
        ("github actions", "github-actions"),
        ("shell", "bash-manual"),
        ("systemd-manual", "systemd-manual"),
        ("iac", "ansible-start"),
    ],
)
def test_resource_search(query, expected):
    assert expected in {r.id for r in search_resources(query)}


def test_related_links_use_known_topics_and_rank_specific_guides_first():
    for key, expected in (
        ("aws-s3", "aws-s3-guide"),
        ("aws-iam", "aws-iam-guide"),
        ("aws-lambda", "aws-lambda-guide"),
        ("linux-processes", "systemd-manual"),
        ("terraform-providers", "terraform-docker"),
    ):
        ident = next(k for k in TOPICS if k.split("/", 1)[1].startswith(key))
        assert for_topic(ident)[0].id == expected
        assert for_topic(TOPICS[ident][1]) == for_topic(ident)
    assert for_topic("EC2")
    assert for_topic("") == [] and for_topic("no-matching-secret-resume-text") == []
    assert search_resources("!!!") == []
    for ident in TOPICS:
        assert len(for_topic(ident)) <= 3


def test_pagination_covers_every_link_once_and_messages_stay_under_telegram_limit():
    pages = []
    for number in range(1, 9):
        text = resources_text(f"all --page {number}")
        assert len(text) < 4000
        assert f"page {number}/8" in text and "Optional" in text
        pages.append(text)
    for r in RESOURCES:
        assert sum(r.url in text for text in pages) == 1
    assert "Next:" not in pages[-1]
    for query in ("all --page 0", "linux --page 99"):
        assert "Page unavailable" in resources_text(query)
    for query in ("cloud --page -1", "linux --page nope", "cloud --page 99999", "x" * 241):
        assert resources_text(query).startswith("Use /resources")
    assert "No curated resources match" in resources_text("not-a-real-course")
    assert "30 curated links" in resources_text()


def test_resource_browsing_needs_no_profile_or_ai_and_preserves_active_flow(harness):
    h = harness
    h.repo.state.paused = True
    h.repo.state.draft = Draft(id="private-setup", resume_text="PRIVATE DOCUMENT")
    h.repo.state.focus = "draft"
    h.repo.state.labs["pending-lab"] = LabAssignment(
        id="pending-lab",
        lab_id="s3-private-presigned",
        token="SC-TEST-TOKN",
        assigned_date=h.clock.now.date(),
        required=True,
    )
    before = h.repo.state.model_dump(mode="json")
    answer_keys = set(h.repo.answer_keys)
    for text in ("/resources", "/resources linux", "/resources linux --page 2", "/resources no-such-course"):
        command(h, text)
    assert h.repo.state.model_dump(mode="json") == before
    assert h.repo.answer_keys == answer_keys and not h.ai.calls
    assert all("PRIVATE DOCUMENT" not in text for text, _ in h.telegram.messages)
    assert all(row["payload"]["type"] == "telegram" for row in h.repo.jobs.values())


def test_dashboard_library_is_static_and_does_not_expose_profile_or_change_state(harness, monkeypatch):
    h = harness
    before = h.repo.state.model_dump(mode="json")
    monkeypatch.setattr("skillcoach.dashboard.authorize_learner", lambda *a: ("owner", h.repo.state))
    body = learner_view(h.repo, 42, 1, h.clock.now, "synthetic", config=h.runtime.config)
    assert body["resources"] == library_view()
    assert h.repo.state.model_dump(mode="json") == before
    assert "answer" not in body["resources"]["items"][0]
    assert not h.ai.calls


def test_lesson_page_and_full_reference_include_optional_resources_without_mutation(harness):
    h = harness
    command(h, "/learn EC2")
    record = next(iter(h.repo.state.lessons.values()))
    before = h.repo.state.model_dump(mode="json")
    body = page(h.repo, h.repo.state, record["id"], h.clock.now)
    assert body["resources"][0]["id"] == "aws-educate"
    job = callback(h, f"lr:{record['id']}")
    text = "\n".join(row["body"].get("text", "") for row in h.repo.outbox.values() if row["job_id"] == job)
    assert "Optional free learning" in text and "https://aws.amazon.com/education/awseducate/" in text
    assert h.repo.state.model_dump(mode="json") == before


def test_lab_resources_cover_every_catalog_lab_and_do_not_verify_it(harness):
    h = harness
    for lab in LABS.values():
        assert for_topic(lab.topics[0])
    command(h, "/lab s3-private-presigned")
    before = h.repo.state.model_dump(mode="json")
    view = lab_view(h.repo.state, h.runtime.config, h.clock.now)
    assert view["items"][0]["resources"][0]["id"] == "aws-s3-guide"
    assert view["items"][0]["status"] != "verified"
    assert h.repo.state.model_dump(mode="json") == before
