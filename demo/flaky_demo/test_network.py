"""Mocked network scenario demonstrating intermittent network timeout / connection errors."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import httpx

_COUNTER_FILE = Path(tempfile.gettempdir()) / "flakyhunter_network_call_counter.txt"


class MockHttpClient:
    """Mock client simulating intermittent network connection drops across runs."""

    @classmethod
    def get(cls, url: str):
        counter = 0
        if _COUNTER_FILE.exists():
            try:
                counter = int(_COUNTER_FILE.read_text(encoding="utf-8").strip())
            except Exception:
                counter = 0
        _COUNTER_FILE.write_text(str(counter + 1), encoding="utf-8")

        # Intermittent network timeout: odd invocations drop packet
        if counter % 2 == 1:
            raise httpx.ConnectTimeout(f"ConnectTimeout: Failed to connect to remote host '{url}'")

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"status": "ok"}
        return response


def test_flaky_network():
    """Mocked HTTP request that intermittently encounters network connection errors."""
    client = MockHttpClient()
    response = client.get("http://localhost:8080/api/v1/health")
    assert response.status_code == 200
