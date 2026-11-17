"""Guards for the compose files in examples/.

Text scan on purpose (a YAML parser would drop the comments that carry the guidance).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"
FILES = ["compose.standalone.yml", "compose.pangolin.yml", "compose.traefik.yml"]
START_VARIABLES = {
    "BAMBUBRIDGE_DATABASE_URL",
    "BAMBUBRIDGE_SECRET_KEY",
    "BAMBUBRIDGE_PUBLIC_URL",
    "BAMBUBRIDGE_BOOTSTRAP_ADMIN_KEY",
}


def _text(name: str) -> str:
    return (EXAMPLES / name).read_text(encoding="utf-8")


def _code(name: str) -> str:
    return "\n".join(line for line in _text(name).splitlines() if not line.strip().startswith("#"))


def test_examples_readme_exists():
    assert (EXAMPLES / "README.md").is_file()


@pytest.mark.parametrize("name", FILES)
def test_examples_use_exactly_five_start_variables(name: str):
    code = _code(name)
    used = set(re.findall(r"\bBAMBUBRIDGE_[A-Z_]+\b", code))
    assert used == START_VARIABLES, name
    assert "BAMBUBRIDGE_SECRET_KEY_OLD" not in code
    assert re.search(r"\bFORWARDED_ALLOW_IPS\b", code), name
    for match in re.findall(r"FORWARDED_ALLOW_IPS[=:]\s*([^\n]*)", code):
        assert "*" not in match, name


@pytest.mark.parametrize("name", FILES)
def test_examples_postgres_18_and_bind_mounts(name: str):
    code = _code(name)
    assert re.search(r"image:\s*postgres:18\.\d+", code), name
    assert "ghcr.io/strausmann/bambubridge:" in code
    assert not re.search(r"^volumes:", code, flags=re.M), "no named volumes"
    mounts = re.findall(r"^\s*-\s*(\S+):/\S+", code, flags=re.M)
    host_mounts = [m for m in mounts if m.startswith(("/", "."))]
    assert host_mounts, name
    for mount in host_mounts:
        # Data under /docker/stacks/; the only other host path is the read-only clock.
        assert mount.startswith("/docker/stacks/") or mount == "/etc/localtime", f"{name}: {mount}"
    assert any(m.startswith("/docker/stacks/") for m in host_mounts), name


@pytest.mark.parametrize("name", FILES)
def test_examples_have_healthchecks_and_no_real_hosts(name: str):
    code = _code(name)
    assert code.count("healthcheck:") >= 2, name
    assert "/healthz" in code
    assert "strausmann" not in code.replace("ghcr.io/strausmann/bambubridge", "")
    assert not re.search(r"\b(100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.|172\.16\.|hhdocker)", code)
