from __future__ import annotations

import pytest

from app.auth.scopes import SCOPES, Scope, lower_scope, satisfies


@pytest.mark.parametrize(
    ("have", "need", "ok"),
    [
        ("read", "read", True),
        ("read", "operate", False),
        ("operate", "read", True),
        ("admin", "operate", True),
        ("operate", "admin", False),
    ],
)
def test_scope_hierarchy(have: Scope, need: Scope, ok: bool):
    assert satisfies(have, need) is ok


def test_full_scope_matrix():
    for i, have in enumerate(SCOPES):
        for j, need in enumerate(SCOPES):
            assert satisfies(have, need) is (i >= j)


def test_unknown_scope_fails_closed():
    with pytest.raises(ValueError, match="unknown scope"):
        satisfies("root", "read")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unknown scope"):
        satisfies("admin", "root")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("admin", "read", "read"),
        ("read", "admin", "read"),
        ("operate", "admin", "operate"),
        ("admin", "admin", "admin"),
    ],
)
def test_lower_scope_picks_the_weaker(a: Scope, b: Scope, expected: Scope):
    assert lower_scope(a, b) == expected
