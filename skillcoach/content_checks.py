"""Deterministic content checks for generated and reviewed lessons.

The checks are deliberately narrow and high-precision: each one catches something that is known to
be broken or unsafe (retired action majors, invented IAM services, credentials configured after the
cloud command, triggers nested in a job, OIDC without an ID token, invalid JSON). A failure message is
returned to the AI provider as its single repair hint, so each message says how to fix the problem.
"""

import json
import re
from urllib.parse import urlsplit

# Oldest major that still runs and is not retired. Reviewed lessons use the current Node 24 majors.
ACTION_MINIMUMS = {
    "actions/checkout": 4,
    "actions/upload-artifact": 4,
    "actions/download-artifact": 4,
    "actions/cache": 4,
    "actions/setup-python": 5,
    "actions/setup-node": 4,
    "actions/setup-go": 5,
    "actions/setup-java": 4,
    "actions/github-script": 7,
    "actions/attest-build-provenance": 1,
    "hashicorp/setup-terraform": 3,
    "aws-actions/configure-aws-credentials": 4,
    "docker/build-push-action": 5,
    "docker/login-action": 3,
    "docker/setup-buildx-action": 3,
    "docker/setup-qemu-action": 3,
    "docker/metadata-action": 5,
    "github/codeql-action": 3,
    "azure/login": 2,
    "google-github-actions/auth": 2,
}
CURRENT_ACTIONS = (
    "actions/checkout@v5+, actions/setup-node@v5+, actions/setup-python@v6+, actions/cache@v5+, "
    "actions/upload-artifact@v6+, actions/download-artifact@v7+, hashicorp/setup-terraform@v4, "
    "aws-actions/configure-aws-credentials@v6, docker/build-push-action@v7"
)
# Latest majors checked on 2026-09-28; retired references in generated text are upgraded to these.
LATEST_MAJORS = {
    "actions/checkout": 7,
    "actions/upload-artifact": 7,
    "actions/download-artifact": 8,
    "actions/cache": 6,
    "actions/setup-python": 7,
    "actions/setup-node": 7,
    "actions/setup-go": 7,
    "actions/setup-java": 6,
    "actions/github-script": 9,
    "actions/attest-build-provenance": 4,
    "hashicorp/setup-terraform": 4,
    "aws-actions/configure-aws-credentials": 6,
    "docker/build-push-action": 7,
    "docker/login-action": 4,
    "docker/setup-buildx-action": 4,
    "docker/setup-qemu-action": 4,
    "docker/metadata-action": 6,
    "github/codeql-action": 4,
    "azure/login": 3,
    "google-github-actions/auth": 3,
}
# Tools that are not AWS services and therefore have no IAM actions.
FAKE_IAM = re.compile(
    r"""(?<![\w/.:-])["']?(terraform|github|gitlab|jenkins|kubernetes|k8s|docker|helm|argocd|actions)"""
    r""":(\*|[A-Z][A-Za-z]+\*?)["']?"""
)
USES = re.compile(r"\b([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)((?:/[A-Za-z0-9_.-]+)*)@([A-Za-z0-9_.-]+)")
FENCED = re.compile(r"```([A-Za-z0-9_+-]*)[^\n]*\n(.*?)```", re.S)
CLOUD_COMMAND = re.compile(
    r"^\s*(?:-\s*)?(?:run:\s*)?(?:terraform\s+(?:init|plan|apply|destroy)\b|aws\s+[a-z0-9-]+\s+[a-z])", re.M
)
JOB_TRIGGER = re.compile(r"^\s+on:\s*(\[|\{|$|push|pull_request|workflow_dispatch|schedule)", re.M)
URL = re.compile(r"https://[^\s<>\"')\]]+")


def code_blocks(text: str) -> list[tuple[str, str]]:
    return [(lang.lower(), body) for lang, body in FENCED.findall(text or "")]


def upgrade_actions(text: str) -> str:
    """Replace retired or branch-pinned references to well-known actions with their latest major."""

    def replace(match):
        name, path, ref = match.group(1), match.group(2), match.group(3)
        minimum = ACTION_MINIMUMS.get(name.lower())
        major = re.fullmatch(r"v(\d+)(?:\.\d+){0,2}", ref)
        if minimum and (ref in ("main", "master") or (major and int(major.group(1)) < minimum)):
            return f"{name}{path}@v{LATEST_MAJORS[name.lower()]}"
        return match.group(0)

    return USES.sub(replace, text or "")


def upgrade_model(model):
    """Return a copy of a pydantic model with every string passed through upgrade_actions."""

    def walk(value):
        if isinstance(value, str):
            return upgrade_actions(value)
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        return value

    return type(model).model_validate(walk(model.model_dump(mode="json")))


def _looks_like_steps(text: str) -> bool:
    return "uses:" in text and ("run:" in text or "steps:" in text)


def text_problems(text: str) -> list[str]:
    problems = []
    for owner_repo, _, ref in USES.findall(text or ""):
        name = owner_repo.lower()
        minimum = ACTION_MINIMUMS.get(name)
        if minimum is None:
            continue
        major = re.fullmatch(r"v(\d+)(?:\.\d+){0,2}", ref)
        if ref in ("main", "master"):
            problems.append(f"Pin {name} to a release tag or full commit SHA, not @{ref}.")
        elif major and int(major.group(1)) < minimum:
            problems.append(
                f"{name}@{ref} is retired or deprecated; use a current major such as {CURRENT_ACTIONS}."
            )
    for prefix, action in FAKE_IAM.findall(text or ""):
        problems.append(
            f'"{prefix}:{action}" is not an IAM action: {prefix} is not an AWS service. Grant only the '
            "specific AWS service actions the tool calls (for example s3:GetObject), scoped to resources."
        )
    blocks = code_blocks(text)
    candidates = [body for _, body in blocks]
    if not blocks and _looks_like_steps(text or ""):
        candidates.append(text)
    for lang, body in blocks:
        if lang == "json":
            try:
                json.loads(body)
            except ValueError:
                problems.append("A ```json block is not valid JSON; remove comments/trailing commas.")
    for body in candidates:
        credentials = body.find("configure-aws-credentials")
        if credentials != -1 and CLOUD_COMMAND.search(body[:credentials]):
            problems.append(
                "configure-aws-credentials must run before any terraform init/plan/apply or aws CLI step."
            )
        jobs = re.search(r"^jobs:\s*$", body, re.M)
        if jobs and JOB_TRIGGER.search(body, jobs.end()):
            problems.append(
                "Workflow triggers (on:) belong at the top level of the workflow, not inside a job."
            )
        if "role-to-assume" in body and not re.search(r"id-token:\s*write", body):
            problems.append("OIDC role assumption needs `permissions: id-token: write` in the same workflow.")
    return problems


def lesson_texts(lesson) -> list[str]:
    texts = [lesson.why, lesson.what, lesson.safety, *lesson.e2e, *lesson.key_terms, *lesson.cleanup]
    texts += [c.body for c in lesson.concepts]
    texts += [task_text(t) for t in lesson.tasks]
    if getattr(lesson, "interview_question", None):
        texts.append(lesson.interview_question)
    return texts


def task_text(task) -> str:
    return "\n".join([task.name, task.goal, *task.steps])


def problems_for(texts) -> list[str]:
    found = []
    for text in texts:
        for problem in text_problems(text):
            if problem not in found:
                found.append(problem)
    return found


def validate_lesson(lesson, *, require_reference=True):
    problems = problems_for(lesson_texts(lesson))
    if require_reference and not reference_urls(lesson.references):
        problems.append(
            "references must include at least one official documentation URL (https) from the vendor's docs."
        )
    if problems:
        raise ValueError(" ".join(problems[:4]))


def finalize_lesson(lesson, fallback: str | None = None):
    """Deterministic post-processing for AI lessons: current action majors and official references."""
    lesson = upgrade_model(lesson)
    references = official_references(lesson.references, fallback)
    return lesson.model_copy(update={"references": references}) if references else lesson


def lesson_validator(fallback: str | None = None):
    def validate(lesson):
        validate_lesson(upgrade_model(lesson), require_reference=not reference_urls([fallback or ""]))

    return validate


def validate_guide(guide):
    guide = upgrade_model(guide)
    problems = problems_for([guide.explanation, *(task_text(t) for t in guide.tasks)])
    if problems:
        raise ValueError(" ".join(problems[:4]))


def reference_urls(references) -> list[str]:
    from skillcoach.storyboard import REFERENCE_HOSTS

    urls = []
    for item in references:
        for url in URL.findall(item or ""):
            url = url.rstrip(".,;:")
            parts = urlsplit(url)
            if parts.hostname in REFERENCE_HOSTS and not parts.username and url not in urls:
                urls.append(url)
    return urls


def official_references(references, fallback: str | None = None) -> list[str]:
    urls = reference_urls(references)
    if fallback and fallback not in urls and reference_urls([fallback]):
        urls.append(fallback)
    return urls[:15]
