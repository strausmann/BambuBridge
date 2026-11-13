"""Relative timing guards that do not go red without a defect.

The cost at n and at 4n is measured in five interleaved rounds (n, 4n, n, 4n ...), the
minimum of each size counts. Linear work gives a ratio of about 4, quadratic work about 16;
the threshold is 8. A ratio over the threshold is measured once more before the test fails,
so one burst of load on the machine cannot fail it. Tests that use this are marked
``timing`` and are skipped under ``pytest -n`` (parallel workers compete for the CPU).
"""

from __future__ import annotations

import time
from collections.abc import Callable

THRESHOLD = 8.0
ROUNDS = 5


def ratio(run: Callable[[str], object], small: str, large: str) -> tuple[float, float, float]:
    """``(ratio, seconds at small, seconds at large)``, minimum of ``ROUNDS`` rounds each."""
    best_small = best_large = float("inf")
    for _ in range(ROUNDS):
        for text, which in ((small, 0), (large, 1)):
            started = time.perf_counter()
            run(text)
            elapsed = time.perf_counter() - started
            if which:
                best_large = min(best_large, elapsed)
            else:
                best_small = min(best_small, elapsed)
    return best_large / max(best_small, 1e-4), best_small, best_large


def assert_linear(run: Callable[[str], object], small: str, large: str) -> None:
    """Fail only if the large input costs more than ``THRESHOLD`` times the small one,
    twice in a row. ``large`` should be four times ``small``."""
    measured = ratio(run, small, large)
    if measured[0] >= THRESHOLD:
        measured = ratio(run, small, large)
    assert measured[0] < THRESHOLD, measured
