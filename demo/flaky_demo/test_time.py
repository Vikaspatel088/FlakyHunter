"""Time-sensitive test scenario using an injectable clock to demonstrate deadline failures.

This scenario demonstrates timing-based flakiness where a function that performs
a time-bounded operation intermittently exceeds its deadline. The flakiness is
controlled via a configurable clock boundary — when the simulated elapsed time
is in an "even" phase of the latency budget cycle, the task completes under the
deadline; in the "odd" phase it overshoots.

The injectable ``DeadlineChecker`` class accepts a ``clock`` callable so that unit
tests can control the clock deterministically. In production the real
``time.perf_counter`` is used, which introduces genuine timing jitter.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class DeadlineChecker:
    """Checks whether an operation completes within a configurable time deadline.

    Args:
        deadline_ms: Maximum allowed elapsed time in milliseconds.
        clock: Callable returning current time in seconds (default: time.perf_counter).
    """

    def __init__(
        self,
        deadline_ms: float = 4.0,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.deadline_ms = deadline_ms
        self.clock = clock

    def measure_operation_ms(self) -> float:
        """Simulate a real operation: sleep 1ms, return elapsed time in milliseconds."""
        start = self.clock()
        time.sleep(0.001)  # 1ms nominal operation
        return (self.clock() - start) * 1000.0

    def is_within_deadline(self) -> tuple[bool, float]:
        """Return (ok, elapsed_ms) indicating whether the operation met its deadline."""
        elapsed_ms = self.measure_operation_ms()
        return elapsed_ms <= self.deadline_ms, elapsed_ms


def test_time_deadline() -> None:
    """Time-sensitive test: operation must complete within a tight wall-clock deadline.

    The test uses the real clock (time.perf_counter). The nominal 1ms sleep is
    measured against a 2ms deadline. On a normally-loaded system the sleep resolves
    in ~1ms and the test passes. Under scheduler contention, OS timer granularity
    spikes (common on Windows where the system timer fires every 10–15ms), or
    CI-runner load the sleep overruns 2ms and the test fails.

    This demonstrates genuine timing-jitter flakiness in a controlled, observable
    way. The DeadlineChecker class accepts an injectable ``clock`` so that unit
    tests can exercise the pass/fail boundary deterministically.
    """
    checker = DeadlineChecker(deadline_ms=2.0)
    ok, elapsed_ms = checker.is_within_deadline()
    assert ok, (
        f"TimeoutError: deadline exceeded! "
        f"Elapsed {elapsed_ms:.3f}ms exceeded {checker.deadline_ms:.1f}ms limit"
    )
