from __future__ import annotations

import pytest

from app.api.routes.auth_continue import safe_next


@pytest.mark.parametrize(
    "value",
    ["/", "/printers", "/printers/1?tab=2#top", "/a%20b", "/search?q=%2Fx", "/caf%C3%A9"],
)
def test_relative_paths_are_kept(value: str):
    assert safe_next(value) == value


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "https://evil.example",
        "http://evil.example/x",
        "//evil.example",
        "///evil.example",
        "/\\evil.example",
        "\\\\evil.example",
        "javascript:alert(1)",
        "evil.example",
        "/%2F%2Fevil.example",
        "/%2f/evil.example",
        "%2F%2Fevil.example",
        "/%5Cevil.example",
        "/%252F%252Fevil.example",
        "/\t/evil.example",
        "/\n/evil.example",
        "/%09/evil.example",
        "/%0A/evil.example",
        "/ /x",
        "/café",
        "/%00",
        "/" + "a" * 2048,
        "/%25252525252F%25252525252Fevil",
    ],
)
def test_everything_else_becomes_root(value: str | None):
    assert safe_next(value) == "/"
