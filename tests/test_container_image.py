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


MEDIA = Path("deploy-oci/docker/Dockerfile.media")


def media_lines():
    text = MEDIA.read_text(encoding="utf-8").replace("\\\n", " ")
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def test_media_image_is_multi_stage_and_keeps_npm_out_of_the_runtime():
    lines = media_lines()
    stages = [line for line in lines if line.startswith("FROM ")]
    assert stages == ["FROM node:22-bookworm-slim AS node-deps", "FROM python:3.12-slim"]
    runtime = lines[lines.index("FROM python:3.12-slim") :]
    assert "RUN npm ci --no-audit --no-fund" in lines
    assert not any("npm" in line for line in runtime if line.startswith("RUN"))
    assert "COPY --from=node-deps /deps/node_modules ./node_modules" in runtime
    assert "COPY --from=node-deps /usr/local/bin/node /usr/local/bin/node" in runtime


def test_media_image_has_every_renderer_the_app_looks_for():
    import re

    text = " ".join(media_lines())
    packages = re.search(r"apt-get install -y --no-install-recommends ([a-z0-9 -]+?) &&", text).group(1)
    assert {"chromium", "ffmpeg", "fonts-dejavu-core", "espeak-ng"} <= set(packages.split())
    # Google ships no Chrome for Linux ARM64: puppeteer must use Debian's Chromium.
    assert "PUPPETEER_SKIP_DOWNLOAD=1" in text and "PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium" in text
    assert 'PATH="/app/node_modules/.bin:${PATH}"' in text  # where shutil.which("mmdc") finds it
    assert '"node_modules/@mermaid-js/mermaid-cli"' in Path("package-lock.json").read_text()


def test_media_image_runs_as_the_same_non_root_user_as_the_app_image():
    lines = media_lines()
    assert "RUN useradd --create-home --uid 10001 appuser" in lines
    assert "COPY --chown=appuser:appuser . ." in lines and lines[-2] == "USER appuser"
    assert [line for line in lines if "pip install" in line] == ["RUN pip install -r requirements.txt"]
