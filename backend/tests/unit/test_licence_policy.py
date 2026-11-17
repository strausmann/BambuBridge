"""Guards for ``licence-policy.yml``, the one policy file every licence gate reads."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from scripts.licence_report import expression_allowed, normalise_purl

REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = REPO_ROOT / "licence-policy.yml"


def _policy() -> dict[str, Any]:
    data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_policy_is_json():
    # JSON is valid YAML: dependency-review reads it as YAML, the scripts read it as JSON.
    assert isinstance(_policy(), dict)


def test_policy_contents():
    policy = _policy()
    allowed = policy["allow-licenses"]
    assert "AGPL-3.0-or-later" in allowed
    assert allowed == sorted(allowed, key=str.casefold)
    assert "GPL-2.0-only" not in allowed
    assert "LGPL-2.0-only" not in allowed
    assert policy["fail-on-scopes"] == ["runtime", "unknown"]
    assert policy["license-check"] is True
    assert policy["vulnerability-check"] is False


def test_every_allowed_purl_has_reason():
    policy = _policy()
    exceptions = {normalise_purl(e["purl"]): e for e in policy["x-licence-exceptions"]}
    for purl in policy["allow-dependencies-licenses"]:
        assert exceptions[normalise_purl(purl)]["reason"].strip()


def test_exception_entries_are_complete():
    seen: set[str] = set()
    for entry in _policy()["x-licence-exceptions"]:
        assert {"purl", "licence", "reason"} <= set(entry)
        assert set(entry) <= {
            "purl",
            "licence",
            "reason",
            "reviewed_expression",
            "licence-text-sha256",
        }
        if "licence-text-sha256" in entry:
            assert re.fullmatch(r"[0-9a-f]{64}", entry["licence-text-sha256"])
        assert entry["purl"].startswith("pkg:")
        assert entry["reason"].strip()
        key = normalise_purl(entry["purl"])
        assert key not in seen, f"duplicate exception {key}"
        seen.add(key)


def test_exception_licences_are_allowed_unless_build_time_only():
    policy = _policy()
    allowed = frozenset(policy["allow-licenses"])
    build_time = set(policy["allow-dependencies-licenses"])
    for entry in policy["x-licence-exceptions"]:
        if entry["purl"] in build_time and entry["purl"].startswith("pkg:npm/spdx-"):
            assert not expression_allowed(entry["licence"], allowed), entry
            continue
        assert expression_allowed(entry["licence"], allowed), entry


def test_no_leftover_project_specific_python_exceptions():
    # Exceptions of the policy's origin name packages BambuBridge does not ship.
    purls = {e["purl"] for e in _policy()["x-licence-exceptions"]}
    assert not {p for p in purls if p.startswith("pkg:pypi/")} & {
        "pkg:pypi/pysnmp",
        "pkg:pypi/qrcode",
        "pkg:pypi/pyusb",
        "pkg:pypi/reportlab",
        "pkg:pypi/ptouch",
    }
