"""Guards for backend/Dockerfile.

Text scan on purpose: the properties are the literal lines of the file (pins, user, healthcheck).
It cannot tell a real instruction from a comment; the real build is exercised by the `docker`
job of ci.yml (build only) and by docker-publish.yml.
"""

from __future__ import annotations

import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[3] / "backend" / "Dockerfile"


def _text() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def _instructions() -> list[str]:
    """Instruction lines without comments."""
    return [
        line.strip()
        for line in _text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_dockerfile_runtime_user_1000_and_healthcheck():
    lines = _instructions()
    text = "\n".join(lines)
    assert "--uid 1000" in text
    assert "--gid 1000" in text
    assert any(
        line.startswith("USER 1000") or line.startswith("USER bambubridge") for line in lines
    )
    assert "HEALTHCHECK" in text
    assert "curl -fsS http://localhost:8000/healthz" in text
    assert 'ENTRYPOINT ["tini", "--"]' in text
    assert 'CMD ["python", "-m", "app.entrypoint"]' in text


def test_dockerfile_base_images_pinned_exact():
    text = "\n".join(_instructions())
    froms = [line.split()[1] for line in _instructions() if line.startswith("FROM ")]
    # Every base image is an exact pin: node for the web build, python twice.
    assert froms == [
        "node:26.13.1-trixie-slim",
        "python:3.14.10-slim-trixie",
        "python:3.14.10-slim-trixie",
    ]
    assert "COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /uvx /bin/" in text
    copied = re.findall(r"COPY --from=(\S+)", text)
    external = [ref for ref in copied if "/" in ref or ":" in ref]
    assert external == ["ghcr.io/astral-sh/uv:0.13.7"]


def test_dockerfile_installs_pnpm_without_corepack():
    text = "\n".join(_instructions())
    assert "npm install -g pnpm@12.18.0" in text
    assert "corepack" not in text


def test_dockerfile_has_three_stages():
    stages = re.findall(r"^FROM .* AS (\S+)", "\n".join(_instructions()), flags=re.M)
    assert stages == ["web-builder", "builder", "runtime"]


def test_dockerfile_oci_labels_and_licence():
    text = _text()
    for key in ("title", "description", "source", "licenses", "version", "revision", "created"):
        assert f"org.opencontainers.image.{key}=" in text
    assert 'org.opencontainers.image.licenses="AGPL-3.0-or-later"' in text


def test_dockerfile_uses_frozen_lockfiles():
    text = "\n".join(_instructions())
    assert "uv sync --frozen --no-dev" in text
    assert "pnpm install --frozen-lockfile" in text


def _stage(name: str) -> str:
    """Instructions of one build stage (from its FROM up to the next FROM)."""
    text = "\n".join(_instructions())
    match = re.search(rf"^FROM .* AS {name}\n(.*?)(?=^FROM |\Z)", text, flags=re.M | re.S)
    assert match, name
    return match.group(1)


def test_web_build_carries_the_same_version_and_build_id_as_the_runtime():
    # The bundle embeds `<version>+<build id>` and the API reports the same pair in
    # X-BambuBridge-Version; a mismatch makes every page show a permanent update banner.
    web, runtime = _stage("web-builder"), _stage("runtime")
    for stage in (web, runtime):
        assert "ARG VERSION=0.0.0-dev" in stage
        assert "ARG REVISION=unknown" in stage
    assert 'BAMBUBRIDGE_BUILD_VERSION="${VERSION}"' in web
    assert 'BAMBUBRIDGE_BUILD_ID="${REVISION}"' in web
    assert 'BAMBUBRIDGE_BUILD_VERSION="${VERSION}"' in runtime
    assert 'BAMBUBRIDGE_BUILD_ID="${REVISION}"' in runtime
    # Set before the build, but after the dependency install so a new version keeps that layer.
    assert (
        web.index("pnpm install") < web.index("BAMBUBRIDGE_BUILD_VERSION") < web.index("pnpm build")
    )
