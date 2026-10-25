"""Pytest plugin entry point for FlakyHunter.

Enforces execution order and records per-test execution metadata.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register FlakyHunter command-line options with pytest."""
    group = parser.getgroup("flakyhunter", "FlakyHunter test runner options")
    group.addoption(
        "--flakyhunter-order-file",
        action="store",
        dest="flakyhunter_order_file",
        default=None,
        help="JSON file containing the exact ordered list of test node IDs to execute.",
    )
    group.addoption(
        "--flakyhunter-output-file",
        action="store",
        dest="flakyhunter_output_file",
        default=None,
        help="Path where FlakyHunter will write per-test execution outcomes in JSON format.",
    )


def pytest_collection_modifyitems(
    session: pytest.Session,
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Enforce the exact test execution order specified by FlakyHunter."""
    order_file = config.getoption("flakyhunter_order_file", default=None)
    if not order_file:
        return

    order_path = Path(order_file)
    if not order_path.exists():
        return

    try:
        with open(order_path, encoding="utf-8") as f:
            target_order: list[str] = json.load(f)
    except Exception:
        return

    # Map available collected items by their full node ID and base name
    item_map = {item.nodeid: item for item in items}

    ordered_items: list[pytest.Item] = []
    for nid in target_order:
        if nid in item_map:
            ordered_items.append(item_map[nid])
        else:
            # Fallback matching by suffix (e.g. test_file.py::test_name)
            for item_nid, item in item_map.items():
                if item_nid.endswith(nid) or nid.endswith(item_nid):
                    if item not in ordered_items:
                        ordered_items.append(item)
                    break

    # Strictly execute only the specified items in the specified order
    items[:] = ordered_items


_FLAKYHUNTER_RESULTS: dict[str, dict[str, Any]] = {}


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Initialize result tracking storage."""
    _FLAKYHUNTER_RESULTS.clear()


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Capture individual test outcome across setup, call, and teardown phases."""
    node_id = report.nodeid
    if node_id not in _FLAKYHUNTER_RESULTS:
        _FLAKYHUNTER_RESULTS[node_id] = {
            "node_id": node_id,
            "outcome": "inconclusive",
            "duration_seconds": 0.0,
            "stdout": "",
            "stderr": "",
            "error_message": None,
            "failure_repr": None,
        }

    rec = _FLAKYHUNTER_RESULTS[node_id]
    rec["duration_seconds"] += getattr(report, "duration", 0.0)

    # Capture stdout and stderr
    for section_name, text in getattr(report, "sections", []):
        if "stdout" in section_name:
            rec["stdout"] = (rec["stdout"] + "\n" + text).strip()
        elif "stderr" in section_name:
            rec["stderr"] = (rec["stderr"] + "\n" + text).strip()

    if report.when == "setup":
        if report.failed:
            rec["outcome"] = "error"
            rec["error_message"] = str(report.longrepr)
            rec["failure_repr"] = str(report.longrepr)
        elif report.skipped:
            rec["outcome"] = "skipped"
            rec["error_message"] = str(report.longrepr)
    elif report.when == "call":
        if report.passed:
            rec["outcome"] = "passed"
        elif report.failed:
            rec["outcome"] = "failed"
            rec["error_message"] = str(getattr(report.longrepr, "reprcrash", report.longrepr))
            rec["failure_repr"] = str(report.longrepr)
        elif report.skipped:
            rec["outcome"] = "skipped"
            rec["error_message"] = str(report.longrepr)
    elif report.when == "teardown":
        if report.failed and rec["outcome"] == "passed":
            rec["outcome"] = "error"
            rec["error_message"] = f"Teardown error: {report.longrepr}"
            rec["failure_repr"] = str(report.longrepr)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Write recorded test results to JSON file on session completion."""
    output_file = session.config.getoption("flakyhunter_output_file", default=None)
    if not output_file:
        return

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(_FLAKYHUNTER_RESULTS, f, indent=2)
    except Exception as exc:
        print(f"FlakyHunter error writing results: {exc}")
