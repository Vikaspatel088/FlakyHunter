"""Probability and statistical calculations for test failure rates and confidence intervals."""

from __future__ import annotations

import math

from flakyhunter.models import ConfidenceInterval, TestOutcome, TestSummary

Z_95 = 1.959963984540054  # 95% normal distribution quantile (approx 1.96)


def wilson_score_interval(
    failures: int,
    eligible_runs: int,
    confidence_level: float = 0.95,
    z: float = Z_95,
) -> ConfidenceInterval:
    """Calculate the Wilson score confidence interval for a binomial proportion.

    Args:
        failures: Number of observed failures (must be >= 0).
        eligible_runs: Total number of eligible trials (must be >= failures).
        confidence_level: Stated confidence level (default 0.95).
        z: Critical standard normal value (default approx 1.96 for 95%).

    Returns:
        ConfidenceInterval with lower and upper bounds in [0.0, 1.0].

    Raises:
        ValueError: If arguments are negative or failures > eligible_runs.
    """
    if failures < 0:
        raise ValueError(f"Failures cannot be negative: {failures}")
    if eligible_runs < 0:
        raise ValueError(f"Eligible runs cannot be negative: {eligible_runs}")
    if failures > eligible_runs:
        raise ValueError(f"Failures ({failures}) cannot exceed eligible runs ({eligible_runs})")

    if eligible_runs == 0:
        return ConfidenceInterval(
            lower=0.0,
            upper=1.0,
            confidence_level=confidence_level,
        )

    n = float(eligible_runs)
    p = float(failures) / n
    z_sq = z * z

    denominator = 1.0 + z_sq / n
    center = p + z_sq / (2.0 * n)
    spread = z * math.sqrt((p * (1.0 - p) / n) + (z_sq / (4.0 * n * n)))

    lower = max(0.0, (center - spread) / denominator)
    upper = min(1.0, (center + spread) / denominator)

    return ConfidenceInterval(
        lower=round(lower, 4),
        upper=round(upper, 4),
        confidence_level=confidence_level,
    )


def compute_test_summary(
    node_id: str,
    outcomes: list[TestOutcome],
) -> TestSummary:
    """Compute statistics, failure probability, and flake status for a single test.

    A flaky test is strictly defined as a test that both passes and fails
    across runs of the same code.

    Args:
        node_id: Unique test identifier.
        outcomes: List of outcomes observed across runs.

    Returns:
        TestSummary with counts, probability, Wilson CI, and flake status.
    """
    passes = 0
    failures = 0
    skips = 0
    inconclusive = 0

    for outcome in outcomes:
        if outcome == TestOutcome.PASSED:
            passes += 1
        elif outcome in (TestOutcome.FAILED, TestOutcome.ERROR):
            failures += 1
        elif outcome == TestOutcome.SKIPPED:
            skips += 1
        elif outcome == TestOutcome.INCONCLUSIVE:
            inconclusive += 1

    eligible_runs = passes + failures
    failure_probability = round(failures / eligible_runs, 4) if eligible_runs > 0 else 0.0
    ci = wilson_score_interval(failures, eligible_runs)
    is_flaky = passes > 0 and failures > 0

    return TestSummary(
        node_id=node_id,
        eligible_runs=eligible_runs,
        passes=passes,
        failures=failures,
        skips=skips,
        inconclusive=inconclusive,
        failure_probability=failure_probability,
        confidence_interval=ci,
        is_flaky=is_flaky,
    )
