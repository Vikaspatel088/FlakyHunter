"""Unit tests for probability and Wilson confidence interval calculations."""

import pytest

from flakyhunter.models import TestOutcome
from flakyhunter.probability import compute_test_summary, wilson_score_interval


def test_wilson_interval_correctness():
    """Verify Wilson interval computation for known sample values."""
    # 5 failures out of 10 runs
    ci = wilson_score_interval(failures=5, eligible_runs=10)
    assert 0.0 <= ci.lower < 0.5
    assert 0.5 < ci.upper <= 1.0
    # Center around 0.5
    assert pytest.approx(ci.lower + ci.upper, rel=0.1) == 1.0


def test_wilson_interval_zero_observations():
    """Verify Wilson interval handles n=0 without division by zero."""
    ci = wilson_score_interval(failures=0, eligible_runs=0)
    assert ci.lower == 0.0
    assert ci.upper == 1.0


def test_wilson_interval_all_passes():
    """Verify that 0 failures in 3 runs produces non-zero upper bound (rule of 3 / Wilson)."""
    ci = wilson_score_interval(failures=0, eligible_runs=3)
    assert ci.lower == 0.0
    # 0 failures in 3 trials does NOT prove non-flakiness; upper bound must be > 0.4
    assert ci.upper > 0.45


def test_wilson_interval_all_failures():
    """Verify that all failures produces lower bound > 0 and upper bound == 1.0."""
    ci = wilson_score_interval(failures=5, eligible_runs=5)
    assert ci.lower > 0.45
    assert ci.upper == 1.0


def test_wilson_interval_invalid_input():
    """Verify invalid parameters raise ValueError."""
    with pytest.raises(ValueError, match="cannot be negative"):
        wilson_score_interval(failures=-1, eligible_runs=10)

    with pytest.raises(ValueError, match="cannot be negative"):
        wilson_score_interval(failures=5, eligible_runs=-10)

    with pytest.raises(ValueError, match="cannot exceed eligible runs"):
        wilson_score_interval(failures=11, eligible_runs=10)


def test_compute_test_summary_flaky():
    """Verify test summary identifies flake when passes and failures both occur."""
    outcomes = [
        TestOutcome.PASSED,
        TestOutcome.FAILED,
        TestOutcome.PASSED,
        TestOutcome.SKIPPED,
    ]
    summary = compute_test_summary("tests/test_foo.py::test_bar", outcomes)
    assert summary.is_flaky is True
    assert summary.passes == 2
    assert summary.failures == 1
    assert summary.skips == 1
    assert summary.eligible_runs == 3
    assert summary.failure_probability == round(1 / 3, 4)


def test_compute_test_summary_stable_pass():
    """Verify test summary for consistently passing test."""
    outcomes = [TestOutcome.PASSED, TestOutcome.PASSED, TestOutcome.PASSED]
    summary = compute_test_summary("tests/test_foo.py::test_bar", outcomes)
    assert summary.is_flaky is False
    assert summary.failures == 0
    assert summary.failure_probability == 0.0


def test_compute_test_summary_skips_not_treated_as_failures():
    """Verify skips and inconclusive outcomes do not affect failure count."""
    outcomes = [TestOutcome.PASSED, TestOutcome.SKIPPED, TestOutcome.INCONCLUSIVE]
    summary = compute_test_summary("tests/test_foo.py::test_bar", outcomes)
    assert summary.is_flaky is False
    assert summary.failures == 0
    assert summary.skips == 1
    assert summary.inconclusive == 1
    assert summary.eligible_runs == 1
