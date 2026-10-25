"""Unit tests for heuristic cause classification."""

import tempfile
from pathlib import Path

from flakyhunter.heuristics import classify_cause
from flakyhunter.models import PolluterInvestigation, TestOutcome


def test_classify_time_cause():
    """Verify time-related flake classification from source AST and error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "test_example.py"
        src.write_text(
            "import time\ndef test_sleepy():\n    time.sleep(0.01)\n    assert True\n",
            encoding="utf-8",
        )
        res = classify_cause(
            node_id=f"{src}::test_sleepy",
            error_message="TimeoutError: operation timed out after 100ms",
        )
        assert res.category == "time"
        assert res.confidence > 0.5
        assert len(res.evidence) >= 2


def test_classify_randomness_cause():
    """Verify randomness-related flake classification from random call and assertion error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "test_rnd.py"
        src.write_text(
            "import random\n"
            "def test_stochastic():\n"
            "    val = random.random()\n"
            "    assert val > 0.5\n",
            encoding="utf-8",
        )
        res = classify_cause(
            node_id=f"{src}::test_stochastic",
            error_message="AssertionError: random assert 0.12 == 0.5",
        )
        assert res.category == "randomness"
        assert res.confidence > 0.5


def test_classify_network_cause():
    """Verify network-related flake classification from HTTP client import and error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "test_net.py"
        src.write_text(
            "import httpx\n"
            "def test_api():\n"
            "    resp = httpx.get('http://localhost:8080')\n"
            "    assert resp.status_code == 200\n",
            encoding="utf-8",
        )
        res = classify_cause(
            node_id=f"{src}::test_api",
            error_message="httpx.ConnectError: ConnectionRefused to localhost",
        )
        assert res.category == "network"
        assert res.confidence > 0.5


def test_classify_shared_state_from_polluter():
    """Verify verified polluter from ddmin yields shared state classification with high confidence."""
    inv = PolluterInvestigation(
        victim_node_id="tests/test_cart.py::test_cart_total",
        baseline_outcome=TestOutcome.PASSED,
        reproduction_outcome=TestOutcome.FAILED,
        original_candidate_set=["tests/test_auth.py::test_login"],
        minimized_polluter_set=["tests/test_auth.py::test_login"],
        execution_count=6,
        verified=True,
        status="reproduced_and_minimized",
        message="Isolated 1 polluter",
    )
    res = classify_cause(
        node_id="tests/test_cart.py::test_cart_total",
        polluter_investigation=inv,
    )
    assert res.category == "shared state"
    assert res.confidence == 0.95


def test_classify_unknown_fallback():
    """Verify code without indicators cleanly falls back to 'unknown' with 0.0 confidence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "test_plain.py"
        src.write_text(
            "def test_simple_math():\n    a = 2 + 2\n    assert a == 4\n",
            encoding="utf-8",
        )
        res = classify_cause(
            node_id=f"{src}::test_simple_math",
            error_message="AssertionError: assert 4 == 5",
        )
        assert res.category == "unknown"
        assert res.confidence == 0.0


def test_precedence_shared_state_over_time():
    """Verify deterministic precedence rule: shared state takes precedence over time indicators."""
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "test_mixed.py"
        src.write_text(
            "import time\n"
            "x = 0\n"
            "def test_conflict():\n"
            "    global x\n"
            "    time.sleep(0.001)\n"
            "    x += 1\n",
            encoding="utf-8",
        )
        # Even if both time and shared state match with equal count, shared state takes precedence
        res = classify_cause(
            node_id=f"{src}::test_conflict",
            error_message="KeyError: state already exists conflict",
        )
        assert res.category == "shared state"
