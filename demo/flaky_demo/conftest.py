"""Shared in-memory state fixture for demonstrating order-dependent test pollution."""

# Module-level mutable state shared across tests running in the same process
SHARED_APP_STATE = {
    "authenticated_user": None,
    "cart_locked": False,
    "items": [],
}
