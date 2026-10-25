"""Stochastic test with flaky behavior driven by unseeded random values."""

import random


def test_flaky_random():
    """Flaky test whose pass/fail outcome depends on pseudo-random generation."""
    val = random.random()
    assert val > 0.40, f"Stochastic flake: random value {val:.4f} was below threshold 0.40"
