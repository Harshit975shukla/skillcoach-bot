import re
from dataclasses import replace

import pytest
from test_flows import command

from skillcoach.capstones import CAPSTONES, portfolio_data, portfolio_html
from skillcoach.clients import Budget
from skillcoach.config import Config
from skillcoach.lab_checks import LabChecker
from skillcoach.labs import blob_sha


def texts(h):
    return [text for text, _ in h.telegram.messages]


class FakeChecker:
    def __init__(self, result):
        self.result, self.calls = result, []

    def capstone(self, capstone, url, token, budget):
        self.calls.append((capstone.id, url, token))
        return self.result


def test_capstone_brief_token_submission_and_retry_without_rechecking(harness):
    h = harness
    command(h, "/capstone")
    assert all(c.title in texts(h)[-1] for c in CAPSTONES.values())
    command(h, "/capstone container-ci")
    record = h.repo.state.capstones["container-ci"]
    assert record.token in texts(h)[-1] and ".skillcoach/capstone-container-ci.token" in texts(h)[-1]
    h.runtime.labs = FakeChecker({"code": "capstone_files_missing", "missing": ["A Dockerfile"]})
    command(h, "/submitcapstone container-ci https://github.com/learner/service")
    assert h.repo.state.capstones["container-ci"].status == "needs_fix"
    assert "Missing: A Dockerfile" in texts(h)[-1]
    h.runtime.labs = FakeChecker({"code": "verified", "checks": ["public-repo", "ci-success"]})
    command(h, "/submitcapstone container-ci https://github.com/learner/service")
    record = h.repo.state.capstones["container-ci"]
    assert record.status == "verified" and record.repo == "learner/service"
    assert "Capstone verified" in texts(h)[-1] and h.clock.now.date() in h.repo.state.activity
    command(h, "/submitcapstone container-ci https://github.com/learner/service")
    assert "already verified" in texts(h)[-1] and len(h.runtime.labs.calls) == 1
    command(h, "/submitcapstone k8s-release https://github.com/learner/cluster")
    assert "Open the capstone first" in texts(h)[-1]
    command(h, "/submitcapstone container-ci not-a-link")
    assert "already verified" in texts(h)[-1]


def test_capstone_checks_respect_the_labs_kill_switch(harness):
    h = harness
    command(h, "/capstone container-ci")
    h.runtime.config = replace(h.runtime.config, labs_enabled=False)
    h.runtime.labs = FakeChecker({"code": "verified", "checks": ["public-repo"]})
    command(h, "/submitcapstone container-ci https://github.com/learner/service")
    assert "temporarily turned off" in texts(h)[-1] and not h.runtime.labs.calls
    assert h.repo.state.capstones["container-ci"].status == "started" and not h.repo.state.lab_checks
    command(h, "/capstone container-ci")  # Briefs stay readable; only checks stop.
    assert ".skillcoach/capstone-container-ci.token" in texts(h)[-1]


def test_portfolio_is_opt_in_escaped_revocable_and_evidence_only(harness):
    h = harness
    h.runtime.config = replace(h.runtime.config, private_dashboard_url="https://x.test/app")
    command(h, "/portfolio")
    assert "OFF" in texts(h)[-1]
    command(h, "/portfolio name <script>alert(1)</script>")
    assert "without < or >" in texts(h)[-1]
    command(h, "/portfolio name Asha K")
    command(h, "/portfolio on")
    slug = h.repo.state.portfolio.slug
    assert re.fullmatch(r"[A-Za-z0-9_-]{16}", slug) and f"https://x.test/portfolio/{slug}" in texts(h)[-1]
    command(h, "/capstone iac-module")
    h.runtime.labs = FakeChecker({"code": "verified", "checks": ["ci-success"]})
    command(h, "/submitcapstone iac-module https://github.com/asha/tf-module")
    h.repo.state.profile = None
    data = portfolio_data(h.repo.state, h.clock.now)
    assert data["name"] == "Asha K" and data["capstones"][0]["repo"] == "asha/tf-module"
    assert set(data) == {"name", "capstones", "labs", "lessons", "study_days", "solid_topics"}
    page = portfolio_html({**data, "name": "<img src=x>"})
    assert (
        "<img src=x>" not in page
        and "&lt;img src=x&gt;" in page
        and 'name="robots" content="noindex"' in page
    )
    command(h, "/portfolio repos off")
    assert portfolio_data(h.repo.state, h.clock.now)["capstones"][0]["repo"] is None
    command(h, "/portfolio off")
    assert not h.repo.state.portfolio.enabled and h.repo.state.portfolio.slug is None
    command(h, "/portfolio on")
    assert h.repo.state.portfolio.slug != slug  # An old shared link never comes back.


def test_capstone_checker_requires_token_files_and_green_ci(config, monkeypatch):
    capstone = CAPSTONES["container-ci"]
    token = "SC-ABCD-EFGH"
    paths = {
        ".skillcoach/capstone-container-ci.token": blob_sha(token.encode() + b"\n"),
        "Dockerfile": "a",
        ".github/workflows/ci.yml": "b",
        "tests/test_app.py": "c",
        "README.md": "d",
    }
    runs = {
        "workflow_runs": [{"head_sha": "c1", "event": "push", "status": "completed", "conclusion": "success"}]
    }

    def scenario(tree, run_list):
        answers = {
            "": {"private": False, "default_branch": "main"},
            "/branches/main": {"commit": {"sha": "c1", "commit": {"tree": {"sha": "t1"}}}},
            "/git/trees/t1?recursive=1": {
                "tree": [{"type": "blob", "path": p, "sha": s} for p, s in tree.items()]
            },
            "/actions/runs?head_sha=c1&per_page=30": run_list,
        }
        checker = LabChecker(Config("postgresql://test-only", "fake-token", 42, "a" * 32))
        monkeypatch.setattr(
            checker,
            "_github_getter",
            lambda url, budget: ((lambda path: answers[path]), None),
        )
        return checker.capstone(capstone, "https://github.com/learner/service", token, Budget(20))

    assert scenario(paths, runs)["code"] == "verified"
    assert scenario({k: v for k, v in paths.items() if k != "Dockerfile"}, runs) == {
        "code": "capstone_files_missing",
        "missing": ["A Dockerfile"],
    }
    assert (
        scenario({**paths, ".skillcoach/capstone-container-ci.token": "zz"}, runs)["code"]
        == "token_file_missing"
    )
    assert scenario(paths, {"workflow_runs": []})["code"] == "ci_missing"
    failing = {"workflow_runs": [{**runs["workflow_runs"][0], "conclusion": "failure"}]}
    assert scenario(paths, failing)["code"] == "run_failed"
    running = {"workflow_runs": [{**runs["workflow_runs"][0], "status": "in_progress", "conclusion": None}]}
    assert scenario(paths, running)["code"] == "run_in_progress"
    assert LabChecker(config).capstone(capstone, "https://gitlab.com/x/y", token, Budget(20)) == {
        "code": "url_not_allowed"
    }


@pytest.mark.postgres
def test_public_portfolio_route_serves_only_enabled_learners(pg_repo, config):
    from test_multiuser import Bot

    from skillcoach.capstones import Portfolio
    from skillcoach.web import create_app

    bot = Bot(pg_repo, config)
    a, b = bot.join(101), bot.join(102)
    bot.save(a, lambda s: setattr(s, "portfolio", Portfolio(enabled=True, slug="A" * 16, name="Learner A")))
    bot.save(b, lambda s: setattr(s, "portfolio", Portfolio(enabled=False, slug="B" * 16, name="Learner B")))
    client = create_app(bot.runtime).test_client()
    page = client.get("/portfolio/" + "A" * 16)
    assert page.status_code == 200 and b"Learner A" in page.data and b"Learner B" not in page.data
    assert (
        page.headers["Cache-Control"] == "no-store, private"
        and "script-src" in page.headers["Content-Security-Policy"]
    )
    assert client.get("/portfolio/" + "B" * 16).status_code == 404
    assert client.get("/portfolio/short").status_code == 404
    bot.input(bot.config.owner_id, "/revoke " + a.learner_id)
    assert client.get("/portfolio/" + "A" * 16).status_code == 404
