"""Delta debugging (ddmin) algorithm for isolating minimal polluting test sets."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path

from flakyhunter.models import PolluterInvestigation, TestOutcome
from flakyhunter.runner import execute_order_subprocess


def split_into_n_chunks(items: list[str], n: int) -> list[list[str]]:
    """Partition a list into n roughly equal consecutive subsets."""
    k, m = divmod(len(items), n)
    chunks = []
    start = 0
    for i in range(n):
        end = start + k + (1 if i < m else 0)
        chunks.append(items[start:end])
        start = end
    return [c for c in chunks if c]


def run_ddmin(
    initial_candidates: list[str],
    test_evaluator: Callable[[list[str]], TestOutcome],
    max_executions: int = 50,
) -> tuple[list[str], int, bool]:
    """Execute Andreas Zeller's ddmin algorithm to find a minimal subset causing failure.

    Args:
        initial_candidates: Starting list of candidates.
        test_evaluator: Function that evaluates candidate subset and returns TestOutcome.
        max_executions: Execution budget limit.

    Returns:
        Tuple of (minimized_candidates, total_executions_used, budget_exhausted).
    """
    candidates = list(initial_candidates)
    executions = 0
    budget_exhausted = False
    n = 2

    while len(candidates) > 1:
        if executions >= max_executions:
            budget_exhausted = True
            break

        chunks = split_into_n_chunks(candidates, min(n, len(candidates)))

        # 1. Test each subset
        found_smaller = False
        for chunk in chunks:
            if executions >= max_executions:
                budget_exhausted = True
                break
            executions += 1
            outcome = test_evaluator(chunk)
            if outcome in (TestOutcome.FAILED, TestOutcome.ERROR):
                candidates = chunk
                n = max(n - 1, 2)
                found_smaller = True
                break

        if found_smaller or budget_exhausted:
            continue

        # 2. Test each complement
        for chunk in chunks:
            if executions >= max_executions:
                budget_exhausted = True
                break
            complement = [c for c in candidates if c not in chunk]
            if not complement:
                continue
            executions += 1
            outcome = test_evaluator(complement)
            if outcome in (TestOutcome.FAILED, TestOutcome.ERROR):
                candidates = complement
                n = max(n - 1, 2)
                found_smaller = True
                break

        if found_smaller or budget_exhausted:
            continue

        # 3. Increase granularity
        if n < len(candidates):
            n = min(len(candidates), 2 * n)
        else:
            # Cannot partition further; candidates are 1-minimal
            break

    return candidates, executions, budget_exhausted


def investigate_polluter(
    target_path: Path | str,
    victim_node_id: str,
    failing_order: list[str],
    max_executions: int = 50,
    python_exe: str | None = None,
) -> PolluterInvestigation:
    """Investigate an order-dependent test failure and isolate minimal polluters via ddmin.

    Args:
        target_path: Test suite target directory or file.
        victim_node_id: The test that failed in the failing order.
        failing_order: Complete executed order in which the victim failed.
        max_executions: Maximum test suite executions allowed for search.
        python_exe: Python interpreter path.

    Returns:
        PolluterInvestigation containing verified results, execution counts, and status.
    """
    # Extract tests that ran before the victim
    try:
        victim_index = failing_order.index(victim_node_id)
        candidates = failing_order[:victim_index]
    except ValueError:
        # If victim is not in order, try suffix matching
        victim_index = -1
        for idx, item in enumerate(failing_order):
            if item.endswith(victim_node_id) or victim_node_id.endswith(item):
                victim_index = idx
                victim_node_id = item
                break
        if victim_index == -1:
            return PolluterInvestigation(
                victim_node_id=victim_node_id,
                baseline_outcome=TestOutcome.INCONCLUSIVE,
                reproduction_outcome=TestOutcome.INCONCLUSIVE,
                original_candidate_set=[],
                minimized_polluter_set=[],
                execution_count=0,
                status="victim_not_in_failing_order",
                message=f"Victim {victim_node_id} was not present in the failing order.",
            )
        candidates = failing_order[:victim_index]

    if not candidates:
        return PolluterInvestigation(
            victim_node_id=victim_node_id,
            baseline_outcome=TestOutcome.INCONCLUSIVE,
            reproduction_outcome=TestOutcome.INCONCLUSIVE,
            original_candidate_set=[],
            minimized_polluter_set=[],
            execution_count=0,
            status="no_prior_candidates",
            message="Victim ran first with no prior candidate tests to investigate.",
        )

    executions_used = 0

    with tempfile.TemporaryDirectory(prefix="flakyhunter_polluter_") as tmp_dir:
        temp_path = Path(tmp_dir)

        def evaluate_sequence(subset: list[str]) -> TestOutcome:
            nonlocal executions_used
            order_to_run = subset + [victim_node_id]
            run_rec = execute_order_subprocess(
                target_path=target_path,
                order=order_to_run,
                run_index=executions_used,
                seed=9999 + executions_used,
                temp_dir=temp_path,
                python_exe=python_exe,
            )
            # Find victim result
            victim_res = run_rec.results.get(victim_node_id)
            if not victim_res:
                for k, v in run_rec.results.items():
                    if k.endswith(victim_node_id) or victim_node_id.endswith(k):
                        victim_res = v
                        break
            return victim_res.outcome if victim_res else TestOutcome.INCONCLUSIVE

        # Step 1: Check baseline (victim alone)
        executions_used += 1
        baseline_outcome = evaluate_sequence([])
        if baseline_outcome in (TestOutcome.FAILED, TestOutcome.ERROR):
            return PolluterInvestigation(
                victim_node_id=victim_node_id,
                baseline_outcome=baseline_outcome,
                reproduction_outcome=baseline_outcome,
                original_candidate_set=candidates,
                minimized_polluter_set=[],
                execution_count=executions_used,
                verified=False,
                status="baseline_failed",
                message="Victim test failed in isolation. Failure is not order-dependent.",
            )

        # Step 2: Check reproduction (all candidates + victim)
        executions_used += 1
        reproduction_outcome = evaluate_sequence(candidates)
        if reproduction_outcome not in (TestOutcome.FAILED, TestOutcome.ERROR):
            return PolluterInvestigation(
                victim_node_id=victim_node_id,
                baseline_outcome=baseline_outcome,
                reproduction_outcome=reproduction_outcome,
                original_candidate_set=candidates,
                minimized_polluter_set=[],
                execution_count=executions_used,
                verified=False,
                status="non_reproducible",
                message="Failure could not be reproduced when running candidates before victim.",
            )

        # Step 3: Run ddmin
        remaining_budget = max(0, max_executions - executions_used)
        minimized, ddmin_runs, budget_exhausted = run_ddmin(
            initial_candidates=candidates,
            test_evaluator=evaluate_sequence,
            max_executions=remaining_budget,
        )
        executions_used += ddmin_runs

        # Step 4: Verification of 1-minimality and repeatability
        verified = False
        if not budget_exhausted and minimized:
            # 1. Polluter set alone + victim must fail
            executions_used += 1
            polluter_outcome = evaluate_sequence(minimized)

            # Repeat to verify reproducible failure under candidate sequence
            executions_used += 1
            repeat_outcome = evaluate_sequence(minimized)

            if polluter_outcome in (TestOutcome.FAILED, TestOutcome.ERROR) and repeat_outcome in (
                TestOutcome.FAILED,
                TestOutcome.ERROR,
            ):
                # Verify baseline victim still consistently passes in isolation
                executions_used += 1
                baseline_repeat = evaluate_sequence([])

                if baseline_repeat == TestOutcome.PASSED:
                    # 2. Removing any single element from minimized must pass (1-minimality)
                    is_1_minimal = True
                    for element in minimized:
                        subset_without = [c for c in minimized if c != element]
                        executions_used += 1
                        sub_outcome = evaluate_sequence(subset_without)
                        if sub_outcome in (TestOutcome.FAILED, TestOutcome.ERROR):
                            is_1_minimal = False
                            break
                    if is_1_minimal:
                        verified = True

        status = (
            "reproduced_and_minimized"
            if verified
            else ("budget_exhausted" if budget_exhausted else "unverified_reduction")
        )
        msg = (
            f"Successfully isolated minimal polluter set of size {len(minimized)}"
            if verified
            else (
                "Search budget exhausted before 1-minimal polluter set was verified."
                if budget_exhausted
                else "Reduction completed but failed 1-minimality verification."
            )
        )

        return PolluterInvestigation(
            victim_node_id=victim_node_id,
            baseline_outcome=baseline_outcome,
            reproduction_outcome=reproduction_outcome,
            original_candidate_set=candidates,
            minimized_polluter_set=minimized,
            execution_count=executions_used,
            budget_exhausted=budget_exhausted,
            verified=verified,
            status=status,
            message=msg,
        )
