from __future__ import annotations

import pytest

from app.entrypoint import validate_forwarded_allow_ips


@pytest.mark.parametrize("value", [None, "", "*", "10.0.0.0/24", "a,b"])
def test_forwarded_allow_ips_rejects_non_single_address(value: str | None):
    with pytest.raises(SystemExit):
        validate_forwarded_allow_ips(value)


def test_forwarded_allow_ips_accepts_ipv4_and_ipv6():
    assert validate_forwarded_allow_ips("10.1.2.3") == "10.1.2.3"
    assert validate_forwarded_allow_ips("fd00::1") == "fd00::1"
