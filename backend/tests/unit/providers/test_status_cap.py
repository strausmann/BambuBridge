"""Capping status messages: bounded length, never half a mask."""

from __future__ import annotations

import pytest

from app.providers.manager import MAX_STATUS_MESSAGE_LENGTH, _cap


def test_short_messages_stay():
    assert _cap("all fine") == "all fine"


def test_long_messages_are_cut_with_an_ellipsis():
    capped = _cap("x" * (MAX_STATUS_MESSAGE_LENGTH + 10))
    assert len(capped) == MAX_STATUS_MESSAGE_LENGTH
    assert capped.endswith("…")


@pytest.mark.parametrize("offset", [1, 2])
def test_a_mask_across_the_cut_is_dropped_whole(offset: int):
    cut = MAX_STATUS_MESSAGE_LENGTH - 1
    message = "x" * (cut - offset) + "***" + "y" * 50
    capped = _cap(message)
    assert capped == "x" * (cut - offset) + "…"
