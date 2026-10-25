"""Polluter test: mutates shared session state, causing subsequent victim tests to fail."""

try:
    from demo.flaky_demo.conftest import SHARED_APP_STATE
except ImportError:
    from conftest import SHARED_APP_STATE


def test_user_login():
    """Polluter test: sets authenticated user and leaves cart locked as shared side-effect."""
    SHARED_APP_STATE["authenticated_user"] = "admin"
    SHARED_APP_STATE["cart_locked"] = True
    assert SHARED_APP_STATE["authenticated_user"] == "admin"
