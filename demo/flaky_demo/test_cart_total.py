"""Victim test: expects a clean unpolluted state; fails if executed after test_user_login."""

try:
    from demo.flaky_demo.conftest import SHARED_APP_STATE
except ImportError:
    from conftest import SHARED_APP_STATE


def test_cart_total():
    """Victim test: verifies cart calculation, failing if cart was locked by earlier test."""
    assert not SHARED_APP_STATE["cart_locked"], (
        "Cart state was polluted by an earlier test execution! Expected unlocked cart."
    )
    items = [15.0, 25.0, 10.0]
    assert sum(items) == 50.0
