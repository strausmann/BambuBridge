"""Guards for the release and publish workflows.

Text scan on purpose: the properties are the literal lines of the files. Comments, strings and
identically named identifiers elsewhere are indistinguishable from real keys, so each check names
the exact expression it looks for.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github" / "workflows"


def _wf(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _on_block(text: str) -> str:
    match = re.search(r"^on:\n((?:[ \t].*\n|\n)+)", text, flags=re.M)
    assert match, "no top-level on: block"
    return match.group(1)


def test_release_is_manual_only():
    on = _on_block(_wf("release.yml"))
    assert "workflow_dispatch" in on
    assert "schedule" not in on
    assert "push:" not in on
    assert "pull_request" not in on


def test_release_calls_publish_with_the_tag():
    text = _wf("release.yml")
    assert "uses: ./.github/workflows/docker-publish.yml" in text
    assert "npm ci --ignore-scripts" in text
    assert "SEMANTIC_RELEASE_SSH_KEY" in text
    assert "secrets: inherit" not in text


def test_release_runs_only_from_main_or_rc():
    text = _wf("release.yml")
    assert "refs/heads/main" in text
    assert "refs/heads/rc" in text


def test_publish_signs_with_project_key():
    text = _wf("docker-publish.yml")
    assert "cosign sign" in text
    assert "--key env://COSIGN_PRIVATE_KEY" in text
    assert "COSIGN_PASSWORD: ${{ secrets.COSIGN_PASSWORD }}" in text
    assert "COSIGN_PRIVATE_KEY: ${{ secrets.COSIGN_PRIVATE_KEY }}" in text
    assert "--key cosign.pub" in text  # signature is verified right after signing
    assert "@${DIGEST}" in text  # signed by digest, never by a movable tag


def test_publish_has_provenance_and_sbom():
    text = _wf("docker-publish.yml")
    assert "provenance: mode=max" in text
    assert "sbom: true" in text


def test_publish_is_multi_arch_on_native_runners():
    text = _wf("docker-publish.yml")
    assert "ubuntu-24.04-arm" in text
    assert "linux/arm64" in text
    assert "linux/amd64" in text
    assert "push-by-digest=true" in text
    assert "imagetools create" in text


def test_publish_image_names_and_tags():
    text = _wf("docker-publish.yml")
    assert "ghcr.io/strausmann/bambubridge" in text
    assert "docker.io/strausmann/bambubridge" in text
    assert "type=raw,value=edge" in text
    assert "type=sha,prefix=sha-,format=short" in text
    for pattern in ("{{version}}", "{{major}}.{{minor}}", "type=raw,value=latest"):
        assert pattern in text


def test_publish_docker_hub_only_when_public_and_configured():
    text = _wf("docker-publish.yml")
    assert "VISIBILITY: ${{ github.event.repository.visibility }}" in text
    assert '[ "$VISIBILITY" = "public" ]' in text
    assert "DOCKERHUB_USERNAME" in text
    assert "DOCKERHUB_TOKEN" in text


def test_codeql_and_licence_gate_only_when_public():
    for name in ("codeql.yml", "licence-gate.yml"):
        text = _wf(name)
        jobs = re.split(r"^jobs:\n", text, flags=re.M)[1]
        job_ids = re.findall(r"^  ([\w-]+):\n", jobs, flags=re.M)
        assert job_ids, name
        for job_id in job_ids:
            block = re.search(rf"^  {job_id}:\n((?:    .*\n|\n)+)", jobs, flags=re.M)
            assert block
            assert "if: github.event.repository.visibility == 'public'" in block.group(1), (
                f"{name}:{job_id}"
            )
    assert "python" in _wf("codeql.yml")
    assert "javascript-typescript" in _wf("codeql.yml")


def test_release_tools_versions_match_plan():
    package = json.loads((ROOT / ".github" / "release-tools" / "package.json").read_text())
    assert package["dependencies"] == {
        "@semantic-release/changelog": "7.0.0",
        "@semantic-release/exec": "7.1.0",
        "@semantic-release/git": "11.0.1",
        "conventional-changelog-conventionalcommits": "10.4.1",
        "semantic-release": "25.0.9",
    }
    assert (ROOT / ".github" / "release-tools" / "package-lock.json").is_file()


def test_releaserc_branches_and_repository():
    config = json.loads((ROOT / ".releaserc.json").read_text())
    assert config["repositoryUrl"] == "git@github.com:strausmann/BambuBridge.git"
    assert config["branches"] == ["main", {"name": "rc", "prerelease": True}]
    plugins = [p if isinstance(p, str) else p[0] for p in config["plugins"]]
    assert plugins[0] == "@semantic-release/commit-analyzer"
    notes = next(
        p for p in config["plugins"] if p[0] == "@semantic-release/release-notes-generator"
    )
    sections = {t["type"]: t["section"] for t in notes[1]["presetConfig"]["types"]}
    assert sections["feat"].startswith("✨")
    assert sections["fix"].startswith("\U0001f41b")


def test_cosign_public_key_is_committed_and_private_is_not():
    text = (ROOT / "cosign.pub").read_text()
    assert text.startswith("-----BEGIN PUBLIC KEY-----")
    assert "PRIVATE" not in text
    for path in (ROOT / ".github").rglob("*"):
        if path.is_file() and path.suffix in {".yml", ".json"}:
            assert "ENCRYPTED SIGSTORE PRIVATE KEY" not in path.read_text(errors="ignore")


def test_dependabot_auto_merge_pins_actions():
    text = _wf("dependabot-auto-merge.yml")
    assert "github.actor == 'dependabot[bot]'" in text


GUARD = "if: github.ref == 'refs/heads/main' || inputs.tag != ''"


def test_publish_edge_only_from_main_or_with_release_tag():
    # A manual run without a tag from another branch must not move edge or sha-<7>.
    text = _wf("docker-publish.yml")
    jobs = re.split(r"^jobs:\n", text, flags=re.M)[1]
    for job_id in ("build", "merge"):
        block = re.search(rf"^  {job_id}:\n((?:    .*\n|\n)+)", jobs, flags=re.M)
        assert block, job_id
        header = block.group(1).split("    steps:")[0]
        assert GUARD in header, f"{job_id} lacks the dispatch guard"


def test_dependabot_auto_merge_passes_dependency_names_via_env():
    text = _wf("dependabot-auto-merge.yml")
    assert "DEP_NAMES: ${{ steps.meta.outputs.dependency-names }}" in text
    assert "$DEP_NAMES" in text
    run_lines = [ln for ln in text.splitlines() if "gh pr comment" in ln]
    assert run_lines
    assert all("${{" not in ln for ln in run_lines)


def test_ci_builds_the_image_without_pushing():
    text = _wf("ci.yml")
    assert re.search(r"^  docker:\n", text, flags=re.M)
    block = re.search(r"^  docker:\n((?:    .*\n|\n)+)", text, flags=re.M)
    assert block
    job = block.group(1)
    assert "runs-on: ubuntu-24.04\n" in job
    assert "docker build -f backend/Dockerfile ." in job
    assert "push" not in job.replace("persist-credentials", "")
    assert "cosign" not in job
    assert "login" not in job


def test_examples_readme_requires_cosign_3():
    text = (ROOT / "examples" / "README.md").read_text(encoding="utf-8")
    assert "cosign 3 or newer" in text
    assert "cosign verify --key cosign.pub" in text


def test_dependabot_auto_merge_can_read_checks():
    # The wait-on-check action lists check runs of the head commit; in a private repository that
    # needs checks: read.
    text = _wf("dependabot-auto-merge.yml")
    block = re.search(r"^permissions:\n((?:  .*\n)+)", text, flags=re.M)
    assert block
    assert "  checks: read\n" in block.group(1)
    assert "  contents: write\n" in block.group(1)
    assert "  pull-requests: write\n" in block.group(1)
