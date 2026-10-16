"""Static checks for the OCI container image (Docker cannot run on every developer machine)."""

import re
from pathlib import Path

DOCKERFILE = Path("deploy-oci/docker/Dockerfile")


def instructions():
    text = DOCKERFILE.read_text(encoding="utf-8").replace("\\\n", " ")
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def test_image_installs_only_pinned_requirements():
    installs = [line for line in instructions() if "pip install" in line]
    assert installs == ["RUN pip install -r requirements.txt"]
    pins = Path("requirements.txt").read_text().splitlines()
    assert "gunicorn==23.0.0" in pins
    assert all(re.fullmatch(r"[A-Za-z0-9_.\-\[\]]+==[0-9][A-Za-z0-9.]*", pin) for pin in pins)


def test_dependencies_are_cached_before_the_code_and_owned_by_a_non_root_user():
    lines = instructions()
    order = [i for i, line in enumerate(lines) if line.startswith(("COPY requirements.txt", "RUN pip", "COPY "))]
    assert lines[order[0]].startswith("COPY requirements.txt") and lines[order[1]].startswith("RUN pip")
    assert "COPY --chown=appuser:appuser . ." in lines
    assert not any("chown -R" in line for line in lines)
    assert lines.index("USER appuser") > lines.index("COPY --chown=appuser:appuser . .")
    assert not any(line.startswith("USER") and "root" in line for line in lines)


def test_default_command_serves_the_existing_wsgi_app():
    cmd = next(line for line in instructions() if line.startswith("CMD"))
    assert "gunicorn api.webhook:app" in cmd
    assert "app = create_app()" in Path("api/webhook.py").read_text()


def test_build_context_never_ships_secrets_or_private_notes():
    ignored = set(Path(".dockerignore").read_text().splitlines())
    assert {".env", ".env.*", ".git/", ".claude/", "CLAUDE.md", "tests/", ".venv/"} <= ignored
