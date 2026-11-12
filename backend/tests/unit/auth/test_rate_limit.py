from __future__ import annotations

import pytest

from app.auth.rate_limit import SlidingWindowRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_allows_up_to_limit_then_blocks_with_retry_after():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(clock=clock)
    for _ in range(3):
        assert limiter.hit("k", limit=3) == (True, 0)
    allowed, retry_after = limiter.hit("k", limit=3)
    assert allowed is False
    assert retry_after == 60


def test_window_slides():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(clock=clock)
    assert limiter.hit("k", limit=2)[0]
    clock.now += 30
    assert limiter.hit("k", limit=2)[0]
    clock.now += 10
    allowed, retry_after = limiter.hit("k", limit=2)
    assert allowed is False
    assert retry_after == 20  # oldest hit leaves the window in 20 s
    clock.now += 20
    assert limiter.hit("k", limit=2)[0]


def test_rejected_hits_are_not_counted():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(clock=clock)
    assert limiter.hit("k", limit=1)[0]
    for _ in range(5):
        assert not limiter.hit("k", limit=1)[0]
    clock.now += 60
    assert limiter.hit("k", limit=1)[0]


def test_keys_are_independent():
    limiter = SlidingWindowRateLimiter(clock=FakeClock())
    assert limiter.hit("a", limit=1)[0]
    assert limiter.hit("b", limit=1)[0]
    assert not limiter.hit("a", limit=1)[0]


def test_retry_after_is_at_least_one_second():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(clock=clock)
    assert limiter.hit("k", limit=1)[0]
    clock.now += 59.9
    allowed, retry_after = limiter.hit("k", limit=1)
    assert allowed is False
    assert retry_after == 1


def test_number_of_tracked_keys_is_bounded():
    limiter = SlidingWindowRateLimiter(clock=FakeClock(), max_keys=3)
    for key in ("a", "b", "c", "d"):
        limiter.hit(key, limit=1)
    assert limiter.tracked_keys() == 3
    assert limiter.hit("a", limit=1)[0]  # "a" was evicted as least recently used


def test_reset_forgets_a_key():
    limiter = SlidingWindowRateLimiter(clock=FakeClock())
    assert limiter.hit("k", limit=1)[0]
    limiter.reset("k")
    assert limiter.hit("k", limit=1)[0]
    limiter.reset("unknown")  # no error


def test_limit_must_be_positive():
    limiter = SlidingWindowRateLimiter(clock=FakeClock())
    with pytest.raises(ValueError, match="limit"):
        limiter.hit("k", limit=0)


def test_retry_after_peeks_without_recording():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(clock=clock)
    assert limiter.retry_after("k", limit=2) == 0
    limiter.hit("k", limit=2)
    clock.now += 10
    limiter.hit("k", limit=2)
    assert limiter.retry_after("k", limit=2) == 50
    assert limiter.retry_after("k", limit=2) == 50  # peeking records nothing
    assert limiter.retry_after("k", limit=1) == 60  # the newest hit decides for limit 1
    assert limiter.retry_after("k", limit=3) == 0
    clock.now += 50
    assert limiter.retry_after("k", limit=2) == 0
    with pytest.raises(ValueError, match="limit"):
        limiter.retry_after("k", limit=0)
