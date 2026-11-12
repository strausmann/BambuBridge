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


@pytest.mark.parametrize(
    "value",
    [
        "/.//evil.example/x",
        "/%2e%2e//evil.example/x",
        "/%2E//evil.example",
        "/./%2F/evil.example",
        "/x/..//evil.example",
        "/../..//evil.example",
        "/.%2e//evil.example",
        "/%252e//evil.example",
    ],
)
def test_dot_segments_that_resolve_to_another_host_become_root(value: str):
    # Audit H5: browsers resolve dot segments, so these land on a path "//host/...".
    assert safe_next(value) == "/"


@pytest.mark.parametrize("value", ["/a/./b", "/a/../b", "/./printers", "/a/..", "/.well-known/x"])
def test_harmless_dot_segments_are_kept(value: str):
    assert safe_next(value) == value


@pytest.mark.parametrize(
    "value",
    [
        # A browser keeps an encoded ``?``/``#`` in the path but resolves the encoded dot
        # segments after it, so each of these has the pathname ``//evil.test/x``.
        "/a%3f/%2e%2e//evil.test/x",
        "/a%3F/%2E%2E//evil.test/x",
        "/a%23/%2e%2e//evil.test/x",
        "/a%3f/.%2e//evil.test/x",
        "/a%23/%2e.//evil.test/x",
        "/a%253f/%252e%252e//evil.test/x",
    ],
)
def test_encoded_query_or_fragment_marks_in_the_path_become_root(value: str):
    assert safe_next(value) == "/"


@pytest.mark.parametrize("value", ["/search?q=%3F", "/printers#a%23b", "/a?next=%23x"])
def test_encoded_marks_in_the_query_or_fragment_are_kept(value: str):
    assert safe_next(value) == value
