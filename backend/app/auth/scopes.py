"""Scope hierarchy: ``read`` < ``operate`` < ``admin``.

A higher scope satisfies every lower one. Unknown values fail closed (``ValueError``)
instead of granting or denying silently.
"""

from __future__ import annotations

from typing import Literal, get_args

Scope = Literal["read", "operate", "admin"]

# Ordered from the weakest to the strongest scope.
SCOPES: tuple[Scope, ...] = get_args(Scope)
_RANK: dict[str, int] = {scope: rank for rank, scope in enumerate(SCOPES)}


def _rank(scope: str) -> int:
    try:
        return _RANK[scope]
    except KeyError:
        raise ValueError(f"unknown scope: {scope!r}") from None


def satisfies(have: Scope, need: Scope) -> bool:
    """Return whether a caller holding ``have`` may use something that needs ``need``."""
    return _rank(have) >= _rank(need)


def lower_scope(a: Scope, b: Scope) -> Scope:
    """Return the weaker of two scopes (e.g. token scope capped by the owner's role)."""
    return a if _rank(a) <= _rank(b) else b
