# SkillCoach bot - container image for OKE (ARM64 / Ampere A1).
#
# IMPORTANT: build this with the REPO ROOT as the context, not deploy-oci/,
# because the image must COPY the app source (skillcoach/, api/, etc.) which
# live at the repo root:
#
#   docker build -f deploy-oci/docker/Dockerfile -t <image>:<tag> .
#
# One image serves both the Flask web app (gunicorn) and the scheduled
# CronJobs (python -m skillcoach.cli ...). Node/ffmpeg are test-only and
# intentionally excluded to keep the image small.

FROM python:3.12-slim AS base

# - PYTHONUNBUFFERED: logs stream straight to stdout for kubectl logs.
# - PYTHONDONTWRITEBYTECODE: no .pyc clutter in the layer.
# - PIP_NO_CACHE_DIR: smaller image.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

# System libs needed at runtime:
# - libpq is bundled by psycopg[binary], so no libpq-dev required.
# - ca-certificates for TLS to Postgres/Telegram/Groq/SMTP.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first so this layer caches across code-only changes.
# Path is relative to the repo-root build context.
# gunicorn is pinned in requirements.txt with every other dependency.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Create the unprivileged user before copying the code.
RUN useradd --create-home --uid 10001 appuser

# Copy the application already owned by appuser. A later `chown -R` would
# duplicate every file into a second layer and make the image bigger.
# The root .dockerignore keeps tests, venv, docs, deploy-oci and caches out.
COPY --chown=appuser:appuser . .
USER appuser

EXPOSE 8080

# Default command: the web tier. gunicorn serves the WSGI app exposed by
# api/webhook.py (which is skillcoach.web:create_app()).
# CronJobs override this command with: python -m skillcoach.cli <...>.
#   - 2 workers fits the 2 OCPU free node without oversubscribing.
#   - timeout 90s covers the app's bounded AI/PDF work.
CMD ["sh", "-c", "exec gunicorn api.webhook:app --bind 0.0.0.0:${PORT} --workers 2 --threads 2 --timeout 90 --access-logfile - --error-logfile -"]
