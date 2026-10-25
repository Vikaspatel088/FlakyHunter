"""Unit tests for the DeadlineChecker injectable-clock scenario in demo/flaky_demo/test_time.py.

These tests verify that:
1. DeadlineChecker correctly reports pass when elapsed time is within the deadline.
2. DeadlineChecker correctly reports failure when elapsed time exceeds the deadline.
3. The injectable ``clock`` parameter makes the behavior fully deterministic in tests.
"""

from __future__ import annotations


def test_deadline_checker_passes_within_deadline() -> None:
    """Verify DeadlineChecker reports success when operation completes under deadline."""
    from demo.flaky_demo.test_time import DeadlineChecker

    tick = 0.0

    def fast_clock() -> float:
        nonlocal tick
        # Returns 0.0 on first call, 0.001 on second call (1ms elapsed)
        result = tick
        tick += 0.001
        return result

    checker = DeadlineChecker(deadline_ms=4.0, clock=fast_clock)
    ok, elapsed_ms = checker.is_within_deadline()
    assert ok is True
    assert elapsed_ms < 4.0


def test_deadline_checker_fails_above_deadline() -> None:
    """Verify DeadlineChecker reports failure when operation exceeds the deadline."""
    from demo.flaky_demo.test_time import DeadlineChecker

    tick = 0.0

    def slow_clock() -> float:
        nonlocal tick
        # Simulates 10ms elapsed (0.01 seconds)
        result = tick
        tick += 0.010
        return result

    checker = DeadlineChecker(deadline_ms=4.0, clock=slow_clock)
    ok, elapsed_ms = checker.is_within_deadline()
    assert ok is False
    assert elapsed_ms > 4.0


def test_deadline_checker_boundary_condition() -> None:
    """Verify DeadlineChecker passes when elapsed exactly equals deadline (inclusive)."""
    from demo.flaky_demo.test_time import DeadlineChecker

    tick = 0.0

    def exact_clock() -> float:
        nonlocal tick
        # Exactly 2ms elapsed (0.002 seconds) to match the default deadline
        result = tick
        tick += 0.002
        return result

    checker = DeadlineChecker(deadline_ms=2.0, clock=exact_clock)
    ok, elapsed_ms = checker.is_within_deadline()
    assert ok is True  # boundary is inclusive (<=)
    assert abs(elapsed_ms - 2.0) < 0.001


def test_deadline_checker_custom_deadline() -> None:
    """Verify deadline_ms parameter controls the threshold independently of clock speed."""
    from demo.flaky_demo.test_time import DeadlineChecker

    tick = 0.0

    def clock_5ms() -> float:
        nonlocal tick
        result = tick
        tick += 0.005  # 5ms elapsed
        return result

    # 5ms operation is ok under 10ms deadline
    checker_loose = DeadlineChecker(deadline_ms=10.0, clock=clock_5ms)
    ok, _ = checker_loose.is_within_deadline()
    assert ok is True

    tick = 0.0  # reset for reuse

    # 5ms operation fails under 3ms deadline
    checker_tight = DeadlineChecker(deadline_ms=3.0, clock=clock_5ms)
    ok, _ = checker_tight.is_within_deadline()
    assert ok is False
