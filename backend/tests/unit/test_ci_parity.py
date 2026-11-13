"""``make ci`` must run what CI runs.

The workflows in ``.github/workflows`` are the single source of the tool versions; the
repository ``Makefile`` reads them through ``scripts/ci-versions.sh`` (sed and awk, no
YAML parser). These tests are the safety net for that text extraction: every field must
come out non-empty and equal to what a YAML parser reads from the same file, and a
workflow whose layout changed must make the script fail and name the field instead of
handing ``make`` an empty or wrong value. The commands of ``make ci`` are compared with
the ``run:`` steps of job ``backend`` as well.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
SCRIPT = REPO_ROOT / "scripts" / "ci-versions.sh"
MAKEFILE = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
SH = shutil.which("sh") or "/bin/sh"


def _extract(field: str, workflows: Path = WORKFLOWS) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [SH, str(SCRIPT), field, str(workflows)], capture_output=True, text=True, check=False
    )


def _load(name: str) -> Any:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _step(job: Any, action: str) -> Any:
    steps = [s for s in job["steps"] if str(s.get("uses", "")).startswith(f"{action}@")]
    assert len(steps) == 1, f"expected exactly one {action} step"
    return steps[0]


def _from_yaml(field: str) -> str:
    backend = _load("ci.yml")["jobs"]["backend"]
    if field == "python":
        return str(_step(backend, "astral-sh/setup-uv")["with"]["python-version"])
    if field == "uv":
        return str(_step(backend, "astral-sh/setup-uv")["with"]["version"])
    if field == "postgres-image":
        return str(backend["services"]["postgres"]["image"])
    commitlint = _load("commitlint.yml")["jobs"]["commitlint"]
    return str(_step(commitlint, "actions/setup-node")["with"]["node-version"])


# field -> (workflow file, key as the workflow spells it, the key renamed)
FIELDS = {
    "python": ("ci.yml", "python-version", "python_version"),
    "uv": ("ci.yml", "version", "uv-version"),
    "postgres-image": ("ci.yml", "image", "container"),
    "node": ("commitlint.yml", "node-version", "node_version"),
}


@pytest.mark.parametrize("field", sorted(FIELDS))
def test_extracted_version_equals_what_a_yaml_parser_reads(field: str):
    result = _extract(field)
    assert result.returncode == 0, f"{field}: {result.stderr}"
    assert result.stdout.strip() != "", field
    assert result.stdout.strip() == _from_yaml(field), field


@pytest.mark.parametrize("field", sorted(FIELDS))
def test_extraction_fails_and_names_the_field_when_the_key_is_renamed(field: str, tmp_path: Path):
    file_name, key, renamed = FIELDS[field]
    for source in WORKFLOWS.glob("*.yml"):
        text = source.read_text(encoding="utf-8")
        if source.name == file_name:
            # Every line whose key is exactly ``key``, whatever its indentation.
            text, renamed_lines = re.subn(rf"(?m)^(\s*){key}:", rf"\g<1>{renamed}:", text)
            assert renamed_lines >= 1, f"no '{key}:' line in {file_name}"
        (tmp_path / source.name).write_text(text, encoding="utf-8")

    result = _extract(field, tmp_path)
    assert result.returncode == 1
    assert result.stdout == ""
    # The message names the key and the file, e.g. "cannot read the version of the … in ci.yml".
    assert f"cannot read the {key} of the " in result.stderr
    assert f" in {file_name}" in result.stderr


# field -> one value as a job of ci.yml spells it, and a different one
DISAGREEING = {
    "python": ('python-version: "{v}"', "3.0.0"),
    "uv": ('          version: "{v}"', "0.0.1"),
    "postgres-image": ("image: {v}", "postgres:1.0"),
}


@pytest.mark.parametrize("field", sorted(DISAGREEING))
def test_extraction_fails_when_two_jobs_disagree_on_a_version(field: str, tmp_path: Path):
    """backend and web name the same tools; one value changed in one job only must fail."""
    line, other = DISAGREEING[field]
    current = _from_yaml(field)
    for source in WORKFLOWS.glob("*.yml"):
        text = source.read_text(encoding="utf-8")
        if source.name == "ci.yml":
            spelled = line.format(v=current)
            assert text.count(spelled) >= 2, f"{field}: expected in more than one job"
            text = text.replace(spelled, line.format(v=other), 1)
        (tmp_path / source.name).write_text(text, encoding="utf-8")

    result = _extract(field, tmp_path)
    assert result.returncode == 1
    assert result.stdout == ""
    assert current in result.stderr
    assert other in result.stderr


def test_web_job_uses_the_node_version_of_the_commitlint_job():
    web = _load("ci.yml")["jobs"]["web"]
    assert str(_step(web, "actions/setup-node")["with"]["node-version"]) == _from_yaml("node")


def test_makefile_takes_every_version_from_the_script():
    for field in FIELDS:
        assert f"$(shell scripts/ci-versions.sh {field})" in MAKEFILE, field
    # No pinned copy of an image tag is left next to the extracted values.
    assert re.search(r"(python|postgres|node|uv):\d", MAKEFILE) is None


def _make_define(name: str) -> list[str]:
    blocks = re.findall(rf"(?ms)^define {name}\n(.*?)\nendef$", MAKEFILE)
    assert len(blocks) == 1, f"expected exactly one define of {name}"
    return str(blocks[0]).splitlines()


def test_make_ci_runs_the_commands_of_the_backend_job():
    """Same commands in the same order; ``make ci`` only appends optional pytest arguments."""
    in_ci = [step["run"] for step in _load("ci.yml")["jobs"]["backend"]["steps"] if "run" in step]
    lint, test = _make_define("LINT_STEPS"), _make_define("TEST_STEPS")
    assert [line.removesuffix(" $(PYTEST_ARGS)") for line in lint + test] == in_ci
    # "make lint" and "make ci" take their commands from these blocks and from nowhere else.
    assert _make_define("CI_STEPS") == ["$(LINT_STEPS)", "$(TEST_STEPS)"]
    assert MAKEFILE.count("uv run") == sum(line.startswith("uv run") for line in in_ci)


# --- job "web" -----------------------------------------------------------------------------

PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"
# CI installs the browsers in a step; "make ci-web" runs in Playwright's image, which has them.
PROVIDED_BY_THE_IMAGE = "pnpm exec playwright install --with-deps chromium webkit"


def _extract_from_package(field: str, package_json: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [SH, str(SCRIPT), field],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": os.environ["PATH"], "CI_VERSIONS_PACKAGE_JSON": str(package_json)},
    )


def _package() -> Any:
    return json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))


def test_pnpm_and_playwright_versions_equal_what_package_json_holds():
    package = _package()
    pnpm = _extract_from_package("pnpm", PACKAGE_JSON)
    playwright = _extract_from_package("playwright", PACKAGE_JSON)
    assert pnpm.returncode == 0, pnpm.stderr
    assert playwright.returncode == 0, playwright.stderr
    sha512 = _extract_from_package("pnpm-sha512", PACKAGE_JSON)
    assert sha512.returncode == 0, sha512.stderr
    assert re.fullmatch(r"[0-9a-f]{128}", sha512.stdout.strip())
    assert f"pnpm@{pnpm.stdout.strip()}+sha512.{sha512.stdout.strip()}" == package["packageManager"]
    assert playwright.stdout.strip() == package["devDependencies"]["@playwright/test"]


@pytest.mark.parametrize(
    ("field", "old", "new"),
    [
        ("pnpm", '"packageManager": "pnpm@', '"packageManager": "yarn@'),
        # A version without its hash is not accepted: pnpm is installed only after the check.
        ("pnpm", "+sha512.", "+sha256."),
        ("pnpm-sha512", "+sha512.", "+sha512.0"),
        ("pnpm-sha512", "+sha512.", "+sha1."),
        ("playwright", '"@playwright/test": "', '"@playwright/test": "^'),
    ],
)
def test_extraction_fails_when_package_json_no_longer_pins_the_version(
    field: str, old: str, new: str, tmp_path: Path
):
    text = PACKAGE_JSON.read_text(encoding="utf-8")
    assert text.count(old) == 1
    changed = tmp_path / "package.json"
    changed.write_text(text.replace(old, new), encoding="utf-8")

    result = _extract_from_package(field, changed)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "frontend/package.json" in result.stderr


def test_makefile_takes_the_web_versions_from_the_script():
    for field in ("pnpm", "pnpm-sha512", "playwright"):
        assert f"$(shell scripts/ci-versions.sh {field})" in MAKEFILE, field
    assert re.search(r"(playwright|pnpm)[:@]v?\d", MAKEFILE) is None


def test_make_ci_web_runs_the_commands_of_the_web_job():
    """Same commands in the same order; the browsers come from the image instead of a step."""
    web = _load("ci.yml")["jobs"]["web"]
    steps = [step for step in web["steps"] if "run" in step]
    in_ci = []
    for step in steps:
        prefix = "".join(f"{key}={value} " for key, value in step.get("env", {}).items())
        command = prefix + step["run"]
        if step.get("working-directory") == "backend":
            command = f"(cd ../backend && {command})"
        in_ci.append(command)
    assert web["defaults"]["run"]["working-directory"] == "frontend"
    assert PROVIDED_BY_THE_IMAGE in in_ci
    in_ci.remove(PROVIDED_BY_THE_IMAGE)

    fast, test = _make_define("WEB_FAST_STEPS"), _make_define("WEB_TEST_STEPS")
    sync = "(cd ../backend && uv sync --frozen)"
    assert _make_define("WEB_STEPS") == [sync, "$(WEB_FAST_STEPS)", "$(WEB_TEST_STEPS)"]
    assert [sync, *fast, *test] == in_ci
    # "make web-fast" is the fast steps plus the unit tests, taken from the same block.
    assert _make_define("WEB_FAST_ALL") == ["$(WEB_FAST_STEPS)", "pnpm test"]


def test_pnpm_is_installed_only_from_the_checked_tarball_and_without_scripts():
    # Every "npm install -g" of the Makefile goes through pnpm_install: pack, compare the
    # SHA-512 with the pinned one, then install that file with --ignore-scripts.
    installs = [
        line
        for line in MAKEFILE.splitlines()
        if "npm install -g" in line and not line.startswith("#")
    ]
    assert len(installs) == 1, installs
    assert "--ignore-scripts" in installs[0]
    assert '"$$d/pnpm-$(PNPM_VERSION).tgz"' in installs[0]
    recipe = MAKEFILE[MAKEFILE.index("pnpm_install =") : MAKEFILE.index(installs[0])]
    assert 'echo "$(PNPM_SHA512)  pnpm-$(PNPM_VERSION).tgz" | sha512sum -c -' in recipe
    assert MAKEFILE.count("$(call pnpm_install,") == 2
    assert "npm ci --ignore-scripts" in MAKEFILE
    commitlint_runs = [
        s["run"] for s in _load("commitlint.yml")["jobs"]["commitlint"]["steps"] if "run" in s
    ]
    assert "npm ci --ignore-scripts" in commitlint_runs
    assert "npm ci" not in commitlint_runs


def test_containers_cannot_write_git_hooks_and_share_no_host_ipc():
    run = re.search(r"(?m)^DOCKER_RUN := (.*\\\n.*)$", MAKEFILE)
    assert run is not None
    assert '-v "$(CURDIR)/.git":/w/.git:ro' in run.group(1)
    assert '-v "$(CURDIR)/.husky":/w/.husky:ro' in run.group(1)
    # Every container is started through DOCKER_RUN.
    assert MAKEFILE.count("docker run") == MAKEFILE.count(
        "DOCKER_RUN := docker run"
    ) + MAKEFILE.count("docker run -d --rm --name $(CI_DB_NAME)")
    assert "--ipc=host" not in MAKEFILE
    assert "--shm-size=1g" in MAKEFILE


@pytest.mark.parametrize(
    ("field", "file_name", "line", "bad"),
    [
        ("python", "ci.yml", 'python-version: "{v}"', "3.14; touch /tmp/x"),
        ("python", "ci.yml", 'python-version: "{v}"', "$(id)"),
        ("uv", "ci.yml", '          version: "{v}"', "0.13.7`id`"),
        ("postgres-image", "ci.yml", "image: {v}", "postgres:18&&id"),
        ("node", "commitlint.yml", 'node-version: "{v}"', "26|id"),
    ],
)
def test_a_value_with_a_character_outside_the_allowed_set_is_refused(
    field: str, file_name: str, line: str, bad: str, tmp_path: Path
):
    current = _from_yaml(field)
    for source in WORKFLOWS.glob("*.yml"):
        text = source.read_text(encoding="utf-8")
        if source.name == file_name:
            assert line.format(v=current) in text
            text = text.replace(line.format(v=current), line.format(v=bad))
        (tmp_path / source.name).write_text(text, encoding="utf-8")

    result = _extract(field, tmp_path)
    assert result.returncode == 1, result.stdout
    assert result.stdout == ""
    # One message, which names the field and never repeats the refused value.
    assert result.stderr.count("\n") == 1, result.stderr
    assert result.stderr.startswith("ci-versions.sh: refusing the ")
    assert f" in {file_name}" in result.stderr
    assert bad not in result.stderr


def test_a_refused_value_is_not_printed_when_it_stands_next_to_a_good_one(tmp_path: Path):
    bad = "3.14; touch /tmp/x"
    current = _from_yaml("python")
    spelled = f'python-version: "{current}"'
    for source in WORKFLOWS.glob("*.yml"):
        text = source.read_text(encoding="utf-8")
        if source.name == "ci.yml":
            assert text.count(spelled) >= 2
            text = text.replace(spelled, f'python-version: "{bad}"', 1)
        (tmp_path / source.name).write_text(text, encoding="utf-8")

    result = _extract("python", tmp_path)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.count("\n") == 1, result.stderr
    assert result.stderr.startswith("ci-versions.sh: refusing the ")
    assert bad not in result.stderr


def test_every_real_value_passes_the_character_check():
    for field in FIELDS:
        assert re.fullmatch(r"[0-9A-Za-z.:_/@-]+", _extract(field).stdout.strip()), field
