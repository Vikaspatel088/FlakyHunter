"""Subprocess-isolated test execution engine enforcing reproducible orders."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from flakyhunter.collection import collect_tests
from flakyhunter.models import RunRecord, SingleTestExecution, TestOutcome
from flakyhunter.shuffle import generate_suite_orders


class ExecutionError(Exception):
    """Raised when test execution runner encounters an unrecoverable failure."""


def execute_order_subprocess(
    target_path: Path | str,
    order: list[str],
    run_index: int,
    seed: int,
    temp_dir: Path,
    python_exe: str | None = None,
    timeout_seconds: int = 120,
) -> RunRecord:
    """Execute a sequence of tests in a single subprocess in exact order.

    Preserves process-level shared state across the tests in this sequence,
    allowing order-dependent pollution effects to be accurately observed.

    Args:
        target_path: Test path or directory.
        order: Exact ordered list of test node IDs to execute.
        run_index: 0-based index of this run.
        seed: Seed used for this run.
        temp_dir: Working temporary directory for inter-process communication.
        python_exe: Python interpreter path.
        timeout_seconds: Max seconds to wait for execution.

    Returns:
        RunRecord containing outcomes for all executed tests.
    """
    python_cmd = python_exe or sys.executable
    resolved_target = str(Path(target_path).resolve())

    order_file = temp_dir / f"order_run_{run_index}_{seed}.json"
    output_file = temp_dir / f"output_run_{run_index}_{seed}.json"

    with open(order_file, "w", encoding="utf-8") as f:
        json.dump(order, f)

    cmd = [
        python_cmd,
        "-m",
        "pytest",
        "-p",
        "flakyhunter",
        f"--flakyhunter-order-file={order_file.resolve()}",
        f"--flakyhunter-output-file={output_file.resolve()}",
        "--no-header",
        "-q",
        resolved_target,
    ]

    start_time = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        duration = time.monotonic() - start_time
    except subprocess.TimeoutExpired:
        duration = time.monotonic() - start_time
        results = {
            nid: SingleTestExecution(
                node_id=nid,
                outcome=TestOutcome.INCONCLUSIVE,
                duration_seconds=0.0,
                error_message=f"Run timed out after {timeout_seconds} seconds",
            )
            for nid in order
        }
        return RunRecord(
            run_index=run_index,
            seed=seed,
            order=order,
            results=results,
            exit_code=124,
            duration_seconds=round(duration, 4),
        )

    # Read captured outcomes
    results_map: dict[str, SingleTestExecution] = {}
    if output_file.exists():
        try:
            with open(output_file, encoding="utf-8") as f:
                raw_data = json.load(f)
            for nid, data in raw_data.items():
                results_map[nid] = SingleTestExecution(
                    node_id=data.get("node_id", nid),
                    outcome=TestOutcome(data.get("outcome", "inconclusive")),
                    duration_seconds=round(data.get("duration_seconds", 0.0), 4),
                    stdout=data.get("stdout", ""),
                    stderr=data.get("stderr", ""),
                    error_message=data.get("error_message"),
                    failure_repr=data.get("failure_repr"),
                )
        except Exception as exc:
            print(f"Warning: Failed to parse test output file: {exc}")

    # Ensure all requested tests have an entry in results
    for nid in order:
        if nid not in results_map:
            # Fallback by matching suffix
            matched = False
            for k, v in results_map.items():
                if k.endswith(nid) or nid.endswith(k):
                    results_map[nid] = v
                    matched = True
                    break
            if not matched:
                results_map[nid] = SingleTestExecution(
                    node_id=nid,
                    outcome=TestOutcome.INCONCLUSIVE,
                    error_message="Test was not reported in session output",
                )

    return RunRecord(
        run_index=run_index,
        seed=seed,
        order=order,
        results=results_map,
        exit_code=proc.returncode,
        duration_seconds=round(duration, 4),
    )


def run_suite(
    target_path: Path | str,
    runs: int,
    seed: int,
    python_exe: str | None = None,
    progress_callback: Callable[[int, int, RunRecord], None] | None = None,
) -> tuple[list[str], list[RunRecord]]:
    """Execute the full suite across N runs with deterministic shuffled orders.

    Args:
        target_path: Test file or directory.
        runs: Number of runs (must be >= 1).
        seed: Base seed for reproducible ordering.
        python_exe: Optional custom Python binary path.
        progress_callback: Optional callback invoked after each run completes.

    Returns:
        Tuple of (collected_node_ids, list_of_run_records).
    """
    if runs < 1:
        raise ValueError(f"Runs must be a positive integer, got: {runs}")

    node_ids = collect_tests(target_path, python_exe=python_exe)
    orders = generate_suite_orders(node_ids, seed, runs)

    run_records: list[RunRecord] = []
    with tempfile.TemporaryDirectory(prefix="flakyhunter_") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        for i, (run_seed, order) in enumerate(orders):
            record = execute_order_subprocess(
                target_path=target_path,
                order=order,
                run_index=i,
                seed=run_seed,
                temp_dir=temp_dir,
                python_exe=python_exe,
            )
            run_records.append(record)
            if progress_callback:
                progress_callback(i + 1, runs, record)

    return node_ids, run_records
