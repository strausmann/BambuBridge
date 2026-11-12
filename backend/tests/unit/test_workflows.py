"""Workflow hygiene. Text scan on purpose: a YAML parser drops the version comment.

Limits: comments and strings are indistinguishable from real ``uses:`` lines. A
behavioural test is impossible because the property is the file text itself.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"
PINNED = re.compile(r"uses:\s+[\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d")


def test_all_workflow_actions_pinned_by_sha():
    files = sorted(WORKFLOWS.glob("*.yml"))
    assert files, f"no workflows found in {WORKFLOWS}"
    offenders = []
    for path in files:
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            if "uses:" not in stripped or stripped.startswith("#"):
                continue
            if re.search(r"uses:\s+\./", stripped):
                continue
            if not PINNED.search(stripped):
                offenders.append(f"{path.name}:{number}: {stripped}")
    assert not offenders, (
        "actions must be pinned by commit SHA with a version comment:\n" + "\n".join(offenders)
    )


def test_ci_cancels_only_pull_request_runs():
    # Text scan (see module docstring): the property is the literal expression.
    text = (WORKFLOWS / "ci.yml").read_text()
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in text
    assert "cancel-in-progress: true" not in text
