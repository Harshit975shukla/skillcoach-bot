"""Capstone projects verified from the learner's public GitHub repository, and an opt-in public portfolio.

A capstone check confirms the project structure, a token file and a passing CI run on the latest commit.
It is a learning check, not a code review. The portfolio shows verified evidence only.
"""

import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Literal

from pydantic import Field

from skillcoach.models_base import Model

WORKFLOW = ("A GitHub Actions workflow", re.compile(r"^\.github/workflows/[^/]+\.ya?ml$"))
README = ("A README.md explaining how to run it", re.compile(r"^README\.md$", re.IGNORECASE))
TESTS = (
    "Automated tests",
    re.compile(r"(^|/)(tests?/.+|test_[^/]+\.py|[^/]+_test\.(py|go)|[^/]+\.test\.[jt]s)$"),
)
GITHUB_REPO = re.compile(
    r"https://github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9_.-]{1,100}?)(?:\.git)?/?"
)


@dataclass(frozen=True)
class Capstone:
    id: str
    title: str
    modules: tuple[str, ...]
    hours: str
    goal: str
    brief: tuple[str, ...]
    required: tuple[tuple[str, re.Pattern], ...]
    references: tuple[str, ...]


CAPSTONES = {
    c.id: c
    for c in (
        Capstone(
            id="container-ci",
            title="Ship a containerized service with CI",
            modules=("containers", "delivery", "automation"),
            hours="4-6 hours",
            goal="Package a small HTTP service in a multi-stage image and prove every push builds and tests it.",
            brief=(
                "Write a small HTTP service in any language with a /health endpoint and unit tests.",
                "Add a multi-stage Dockerfile that runs as a non-root user.",
                "Add a GitHub Actions workflow that runs the tests and builds the image on every push, "
                "with permissions: contents: read.",
                "Document how to build and run it locally in README.md.",
            ),
            required=(
                ("A Dockerfile", re.compile(r"(^|/)Dockerfile$")),
                WORKFLOW,
                TESTS,
                README,
            ),
            references=(
                "https://docs.docker.com/build/building/multi-stage/",
                "https://docs.github.com/en/actions/writing-workflows/workflow-syntax-for-github-actions",
            ),
        ),
        Capstone(
            id="k8s-release",
            title="Deploy to Kubernetes with probes and a validated manifest set",
            modules=("kubernetes", "gitops", "containers"),
            hours="5-8 hours",
            goal="Run an app on a local kind cluster with readiness, liveness and resource limits, validated in CI.",
            brief=(
                "Write Deployment and Service manifests (or a Helm chart) in k8s/, manifests/, deploy/ or charts/.",
                "Add readiness and liveness probes, resource requests and limits, and a non-root securityContext.",
                "In CI, validate the manifests (for example kubeconform, or helm lint and helm template) on every push.",
                "In README.md, show how to deploy to kind and how you checked rollout status.",
            ),
            required=(
                (
                    "Kubernetes manifests or a Helm chart",
                    re.compile(r"^(k8s|manifests|deploy|charts)/.+\.ya?ml$"),
                ),
                WORKFLOW,
                README,
            ),
            references=(
                "https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/",
                "https://kind.sigs.k8s.io/docs/user/quick-start/",
            ),
        ),
        Capstone(
            id="iac-module",
            title="Publish a tested Terraform or OpenTofu module",
            modules=("iac", "delivery", "security"),
            hours="4-6 hours",
            goal="Build a reusable module with variables, outputs and CI checks, with no cloud credentials in the repo.",
            brief=(
                "Create a module with variables (with descriptions and validation), outputs and a README.",
                "Add an example that uses only local-safe providers, or plans without applying.",
                "In CI run fmt -check and validate (and tofu test or terraform test if you add tests).",
                "Never commit state files, credentials or .tfvars with secrets.",
            ),
            required=(
                ("Terraform or OpenTofu files", re.compile(r"\.(tf|tofu)$")),
                WORKFLOW,
                README,
            ),
            references=(
                "https://developer.hashicorp.com/terraform/language/modules/develop",
                "https://opentofu.org/docs/language/modules/",
            ),
        ),
        Capstone(
            id="observability-stack",
            title="Instrument a service and alert on an SLO",
            modules=("observability", "sre"),
            hours="5-8 hours",
            goal="Expose metrics, scrape them with Prometheus and define alert rules tied to an SLO.",
            brief=(
                "Expose Prometheus metrics from a small service (request count, errors, latency).",
                "Add a prometheus.yml scrape config and an alert rules file for an error-budget burn.",
                "In CI, validate the config and rules (for example promtool check config and check rules).",
                "In README.md, state the SLO, the alert thresholds and why you chose them.",
            ),
            required=(
                ("A Prometheus configuration", re.compile(r"(^|/)prometheus\.ya?ml$")),
                ("Alerting or recording rules", re.compile(r"(^|/)[^/]*(rules|alerts)[^/]*\.ya?ml$")),
                WORKFLOW,
                README,
            ),
            references=(
                "https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/",
                "https://sre.google/workbook/alerting-on-slos/",
            ),
        ),
        Capstone(
            id="linux-automation",
            title="Automate a Linux operations task safely",
            modules=("linux", "automation", "git"),
            hours="3-5 hours",
            goal="Write an idempotent script with tests, safe error handling and CI linting.",
            brief=(
                "Automate a real task (log rotation check, disk-usage report, user audit) in Bash or Python.",
                "Make it idempotent, handle errors explicitly and support a dry-run flag.",
                "Add automated tests and run them plus a linter (shellcheck or ruff) in CI.",
                "In README.md, show usage, exit codes and what the dry run prints.",
            ),
            required=(
                ("A Bash or Python script", re.compile(r"\.(sh|py)$")),
                TESTS,
                WORKFLOW,
                README,
            ),
            references=(
                "https://www.gnu.org/software/bash/manual/bash.html",
                "https://docs.python.org/3/library/argparse.html",
            ),
        ),
    )
}


class CapstoneRecord(Model):
    id: str
    token: str
    status: Literal["started", "needs_fix", "verified"] = "started"
    started_at: datetime
    verified_at: datetime | None = None
    repo: str | None = None
    result_code: str | None = None
    checks: list[str] = Field(default_factory=list, max_length=8)


class Portfolio(Model):
    enabled: bool = False
    slug: str | None = None
    name: str = "SkillCoach learner"
    show_repos: bool = True


def repo_name(url):
    match = GITHUB_REPO.fullmatch(url or "")
    return f"{match.group(1)}/{match.group(2)}" if match else None


class CapstoneFlow:
    def __init__(self, service):
        self.s = service

    def list(self):
        records = self.s.state.capstones
        lines = [
            "🏗 Capstone projects: bigger, portfolio-worthy builds verified from your public GitHub repo."
        ]
        for c in CAPSTONES.values():
            record = records.get(c.id)
            status = {"verified": "✅ verified", "needs_fix": "🔧 needs a fix", "started": "▶️ started"}.get(
                record.status if record else "", "not started"
            )
            lines.append(f"• {c.title} ({c.hours}) · {status} · /capstone {c.id}")
        lines.append("\nVerified capstones and labs can appear on your opt-in public portfolio: /portfolio")
        self.s.say("\n".join(lines))

    def show(self, capstone_id):
        from skillcoach.labs import new_token

        capstone = CAPSTONES.get(capstone_id.strip().lower())
        if capstone is None:
            self.list()
            return
        record = self.s.state.capstones.get(capstone.id)
        if record is None:
            record = CapstoneRecord(id=capstone.id, token=new_token(), started_at=self.s.now)
            self.s.state.capstones[capstone.id] = record
        lines = [
            f"🏗 {capstone.title} ({capstone.hours})",
            f"Goal: {capstone.goal}",
            "\nBuild:",
            *[f"{i}. {step}" for i, step in enumerate(capstone.brief, 1)],
            "\nTo verify, your public repository needs:",
            *[f"- {label}" for label, _ in capstone.required],
            f"- A file .skillcoach/capstone-{capstone.id}.token containing only: {record.token}",
            "- A passing GitHub Actions run on the latest commit",
            f"\nThen send: /submitcapstone {capstone.id} https://github.com/<you>/<repository>",
            "The check confirms structure and a green pipeline; it is not a code review.",
            "\nReferences:\n" + "\n".join(capstone.references),
        ]
        if record.status == "verified":
            lines.insert(1, f"✅ Verified on {record.verified_at:%d %b %Y} from {record.repo}.")
        self.s.say("\n".join(lines))

    def submit(self, capstone_id, url):
        from skillcoach.lab_checks import message
        from skillcoach.lab_flow import LabFlow

        if not self.s.config.labs_enabled:
            # The LABS_ENABLED kill switch stops every GitHub check, capstones included.
            self.s.say(
                "Capstone and lab checks are temporarily turned off. Lessons, quizzes and plans continue."
            )
            return
        capstone = CAPSTONES.get(capstone_id.lower())
        record = self.s.state.capstones.get(capstone.id) if capstone else None
        if record is None:
            self.s.say("Open the capstone first with /capstone <id> to get your token. /capstone lists them.")
            return
        if record.status == "verified":
            self.s.say(f"{capstone.title} is already verified. No new check was run.")
            return
        if repo_name(url) is None:
            self.s.say("Submit the public repository link, like https://github.com/<you>/<repository>.")
            return
        labs = LabFlow(self.s)
        cached = self.s.repo.cached(self.s.job["id"], "capstone-check")
        if cached is None:
            if labs.rate_limited():
                self.s.say("You reached today's limit of 12 checks. Try again tomorrow.")
                return
            result = labs.checker().capstone(capstone, url, record.token, self.s.budget)
            cached = {
                "code": str(result.get("code", "unreachable")),
                "checks": list(result.get("checks", []))[:8],
                "missing": list(result.get("missing", []))[:8],
                "at": self.s.now.isoformat(),
            }
            self.s.repo.cache(self.s.job["id"], "capstone-check", cached, self.s.token)
        self.s.state.lab_checks.append(datetime.fromisoformat(cached["at"]))
        if cached["code"] != "verified":
            record.status, record.result_code = "needs_fix", cached["code"]
            detail = ("\nMissing: " + "; ".join(cached["missing"])) if cached.get("missing") else ""
            self.s.say(
                f"Capstone not verified yet: {message(cached['code'])}{detail}\nFix it and submit again."
            )
            return
        record.status, record.result_code, record.checks = "verified", "verified", cached["checks"]
        record.verified_at, record.repo = self.s.now, repo_name(url)
        self.s.practice()
        self.s.say(
            f"🎉 Capstone verified: {capstone.title}. It can now appear on your public portfolio (/portfolio)."
        )

    def portfolio(self, arg):
        settings = self.s.state.portfolio or Portfolio()
        self.s.state.portfolio = settings
        arg = arg.strip()
        base = (self.s.config.private_dashboard_url or "").rsplit("/app", 1)[0]
        if arg == "on":
            settings.enabled, settings.slug = True, settings.slug or secrets.token_urlsafe(12)
        elif arg == "off":
            # A new link is created next time, so an old shared link stops working for good.
            settings.enabled, settings.slug = False, None
            self.s.say("Your public portfolio is off. The old link no longer works.")
            return
        elif arg.startswith("name "):
            name = arg[5:].strip()
            if not 1 <= len(name) <= 60 or any(ch in name for ch in "<>\n"):
                self.s.say("Use a display name of 1-60 characters without < or >.")
                return
            settings.name = name
        elif arg in ("repos on", "repos off"):
            settings.show_repos = arg.endswith("on")
        elif arg:
            self.s.say(
                "Use /portfolio on, /portfolio off, /portfolio name <display name> or /portfolio repos on|off."
            )
            return
        link = f"{base}/portfolio/{settings.slug}" if settings.enabled and settings.slug and base else None
        self.s.say(
            "🌐 Public portfolio: "
            + (
                f"ON\n{link}"
                if link
                else "ON (the link appears once the dashboard URL is configured)"
                if settings.enabled
                else "OFF"
            )
            + f"\nDisplay name: {settings.name} · repository links: {'shown' if settings.show_repos else 'hidden'}"
            "\nIt shows only verified labs and capstones, lesson and study-day counts and solid roadmap topics: "
            "never answers, documents, scores or your Telegram identity. /portfolio off disables the link."
        )


def portfolio_data(state, now):
    from skillcoach.catalog import TOPICS
    from skillcoach.labs import LABS, ROUTE_LABELS
    from skillcoach.mastery import mastery_view

    settings = state.portfolio
    capstones = [
        {
            "title": CAPSTONES[r.id].title,
            "verified": r.verified_at.date().isoformat(),
            "repo": r.repo if settings.show_repos else None,
        }
        for r in state.capstones.values()
        if r.status == "verified" and r.id in CAPSTONES and r.verified_at
    ]
    labs = [
        {
            "title": LABS[a.lab_id].title,
            "route": ROUTE_LABELS.get(a.route, "Lab"),
            "verified": a.verified_at.date().isoformat(),
        }
        for a in state.labs.values()
        if a.status == "verified" and a.lab_id in LABS and a.verified_at
    ]
    states = mastery_view(state, now)["states"]
    return {
        "name": settings.name,
        "capstones": sorted(capstones, key=lambda c: c["verified"], reverse=True),
        "labs": sorted(labs, key=lambda c: c["verified"], reverse=True),
        "lessons": sum(bool(r.get("delivered_at")) for r in state.lessons.values()),
        "study_days": len(set(state.activity)),
        "solid_topics": sorted(
            TOPICS[t][1] for t, s in states.items() if s["state"] == "solid" and t in TOPICS
        ),
    }


def portfolio_html(data):
    def items(rows, render):
        return "".join(f"<li>{render(row)}</li>" for row in rows) or '<li class="empty">None yet.</li>'

    capstones = items(
        data["capstones"],
        lambda c: f"<strong>{escape(c['title'])}</strong> · verified {escape(c['verified'])}"
        + (
            f' · <a href="https://github.com/{escape(c["repo"])}" rel="noopener noreferrer nofollow">'
            f"{escape(c['repo'])}</a>"
            if c["repo"]
            else ""
        ),
    )
    labs = items(
        data["labs"], lambda a: f"{escape(a['title'])} · {escape(a['route'])} · {escape(a['verified'])}"
    )
    topics = items(data["solid_topics"], escape)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex"><title>Learning portfolio · SkillCoach</title>'
        '<link rel="stylesheet" href="/static/dashboard.css"></head><body><main class="workspace">'
        f'<header class="header"><span class="brand">SkillCoach portfolio</span></header>'
        f'<section class="introduction"><h1>{escape(data["name"])}</h1>'
        f"<p>{data['lessons']} lessons · {data['study_days']} study days</p></section>"
        f'<section><h2>Verified capstone projects</h2><ul class="task-list">{capstones}</ul></section>'
        f'<section><h2>Verified hands-on labs</h2><ul class="task-list">{labs}</ul></section>'
        f'<section><h2>Topics remembered after spaced review</h2><ul class="skill-list">{topics}</ul></section>'
        "<footer><p>Verified by SkillCoach from public GitHub repositories, cloud-lab links and in-app scenarios. "
        "Capstone checks confirm structure and a passing pipeline, not a code review. This is not a certification.</p>"
        "</footer></main></body></html>"
    )
