# SPDX-FileCopyrightText: 2026 Björn Strausmann and BambuBridge contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

# =============================================================================
# BambuBridge - one container
#
# Multi-stage build:
#   1) web-builder - builds the web app from frontend/ (pnpm + Vite)
#   2) builder     - installs the locked Python dependencies into /opt/venv with uv
#                    and checks their licences against licence-policy.yml
#   3) runtime     - copies the venv and the built web app onto a slim base and
#                    runs as UID/GID 1000
#
# One process serves the API and the web UI.
#
# Build context: the REPOSITORY ROOT (the web app lives in frontend/ and uses the
# brand assets in docs/brand/):
#   docker build -f backend/Dockerfile -t bambubridge:local .
#
# Start variables (the only five): BAMBUBRIDGE_DATABASE_URL, BAMBUBRIDGE_SECRET_KEY,
# BAMBUBRIDGE_PUBLIC_URL, BAMBUBRIDGE_BOOTSTRAP_ADMIN_KEY, FORWARDED_ALLOW_IPS.
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: web-builder - the Vite build of the web app
# -----------------------------------------------------------------------------
FROM node:26.13.1-trixie-slim AS web-builder
# Node 26 no longer ships Corepack, so pnpm is installed explicitly at the pinned version.
RUN npm install -g pnpm@12.18.0
WORKDIR /src/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
# The icon step copies the logo from docs/brand/ (frontend/scripts/icons.ts).
COPY docs/brand/ /src/docs/brand/
COPY frontend/ ./
RUN pnpm build

# -----------------------------------------------------------------------------
# Stage 2: builder - the Python environment
# -----------------------------------------------------------------------------
FROM python:3.14.10-slim-trixie AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /build

# Dependencies first: this layer is reused until pyproject.toml or uv.lock change.
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Then the application, installed non-editable so the venv is self-contained.
COPY backend/app/ ./app/
RUN uv sync --frozen --no-dev --no-editable

# Licence check of what the image actually ships. A violation fails the build. The policy is
# the repository's single licence-policy.yml; the script imports nothing from `app`. The tool
# venv holds pip-licenses (build time only) and never reaches the runtime stage.
COPY licence-policy.yml /opt/licence/licence-policy.yml
COPY backend/scripts/licence_report.py /opt/licence/licence_report.py
RUN uv venv /opt/licence-tool \
    && uv pip install --python /opt/licence-tool/bin/python pip-licenses==5.5.5 \
    && mkdir -p /opt/app/licences \
    && /opt/licence-tool/bin/python /opt/licence/licence_report.py \
        --python /opt/venv/bin/python \
        --policy /opt/licence/licence-policy.yml \
        --own-project /build/pyproject.toml \
        --output /opt/app/licences/backend.json

# -----------------------------------------------------------------------------
# Stage 3: runtime
# -----------------------------------------------------------------------------
FROM python:3.14.10-slim-trixie AS runtime

# Set by the CI workflow (or locally with --build-arg); the defaults are placeholders.
ARG VERSION=0.0.0-dev
ARG REVISION=unknown
ARG BUILD_DATE=1970-01-01T00:00:00Z

LABEL org.opencontainers.image.title="BambuBridge" \
      org.opencontainers.image.description="BambuBridge - a self-hosted bridge between Bambu Lab printers and your workshop tools. Not a product of Bambu Lab." \
      org.opencontainers.image.source="https://github.com/strausmann/BambuBridge" \
      org.opencontainers.image.authors="Björn Strausmann <projects@strausmann.ch>" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${BUILD_DATE}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    BAMBUBRIDGE_BUILD_VERSION="${VERSION}" \
    BAMBUBRIDGE_BUILD_ID="${REVISION}"

# tini: PID 1 signal handling so uvicorn shuts down cleanly on SIGTERM.
# curl: the HEALTHCHECK. ca-certificates: outbound HTTPS to the cloud API.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 bambubridge \
    && useradd --system --uid 1000 --gid 1000 --home-dir /home/bambubridge --create-home bambubridge

COPY --from=builder --chown=1000:1000 /opt/venv /opt/venv
# The built web app; app.main serves it from this path.
COPY --from=web-builder --chown=1000:1000 /src/frontend/dist /opt/app/web
COPY --from=builder --chown=1000:1000 /opt/app/licences /opt/app/licences
COPY --chown=1000:1000 LICENSE /opt/app/LICENSE

WORKDIR /home/bambubridge
USER 1000:1000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "app.entrypoint"]
