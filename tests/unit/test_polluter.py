"""Unit tests for delta debugging (ddmin) algorithm and polluter isolation."""

from flakyhunter.models import TestOutcome
from flakyhunter.polluter import run_ddmin, split_into_n_chunks


def test_split_into_n_chunks():
    """Verify list chunk partitioning."""
    items = ["a", "b", "c", "d", "e", "f"]
    chunks_2 = split_into_n_chunks(items, 2)
    assert len(chunks_2) == 2
    assert chunks_2[0] == ["a", "b", "c"]
    assert chunks_2[1] == ["d", "e", "f"]

    chunks_3 = split_into_n_chunks(items, 3)
    assert len(chunks_3) == 3


def test_ddmin_known_single_polluter():
    """Verify ddmin isolates a single true polluter from among distractors."""
    candidates = ["t1", "t2", "polluter_test", "t3", "t4", "t5", "t6"]

    # Fails if and only if 'polluter_test' is present
    def evaluator(subset: list[str]) -> TestOutcome:
        return TestOutcome.FAILED if "polluter_test" in subset else TestOutcome.PASSED

    minimized, executions, budget_exhausted = run_ddmin(candidates, evaluator)

    assert not budget_exhausted
    assert minimized == ["polluter_test"]
    assert executions < len(candidates) * 4


def test_ddmin_removes_irrelevant_tests():
    """Verify ddmin eliminates all irrelevant noise tests."""
    candidates = [f"noise_{i}" for i in range(12)] + ["critical_polluter"]

    def evaluator(subset: list[str]) -> TestOutcome:
        return TestOutcome.FAILED if "critical_polluter" in subset else TestOutcome.PASSED

    minimized, executions, budget_exhausted = run_ddmin(candidates, evaluator)

    assert not budget_exhausted
    assert minimized == ["critical_polluter"]


def test_ddmin_multi_test_polluter():
    """Verify ddmin correctly identifies a 2-test interacting polluter set."""
    candidates = ["noise_1", "part_A", "noise_2", "noise_3", "part_B", "noise_4"]

    # Fails if and only if BOTH part_A and part_B are present
    def evaluator(subset: list[str]) -> TestOutcome:
        if "part_A" in subset and "part_B" in subset:
            return TestOutcome.FAILED
        return TestOutcome.PASSED

    minimized, executions, budget_exhausted = run_ddmin(candidates, evaluator, max_executions=100)

    assert not budget_exhausted
    assert set(minimized) == {"part_A", "part_B"}


def test_ddmin_budget_exhaustion():
    """Verify ddmin terminates and reports budget exhaustion when limit is reached."""
    candidates = [f"candidate_{i}" for i in range(20)] + ["target"]

    def evaluator(subset: list[str]) -> TestOutcome:
        return TestOutcome.FAILED if "target" in subset else TestOutcome.PASSED

    # Very small budget of 2 executions
    minimized, executions, budget_exhausted = run_ddmin(candidates, evaluator, max_executions=2)

    assert budget_exhausted is True
    assert executions == 2


def test_investigate_polluter_baseline_failed(monkeypatch):
    """Verify that if victim fails in isolation, baseline_failed is reported."""
    from flakyhunter.models import RunRecord, SingleTestExecution
    from flakyhunter.polluter import investigate_polluter

    # Mock execute_order_subprocess so victim fails in isolation
    def mock_exec(*args, **kwargs):
        return RunRecord(
            run_index=0,
            seed=0,
            order=["victim"],
            results={"victim": SingleTestExecution(node_id="victim", outcome=TestOutcome.FAILED)},
        )

    monkeypatch.setattr("flakyhunter.polluter.execute_order_subprocess", mock_exec)

    inv = investigate_polluter(
        target_path="dummy",
        victim_node_id="victim",
        failing_order=["p1", "victim"],
    )

    assert inv.status == "baseline_failed"
    assert inv.verified is False
    assert inv.execution_count == 1


def test_investigate_polluter_non_reproducible(monkeypatch):
    """Verify that if failure does not reproduce under candidates, non_reproducible is reported."""
    from flakyhunter.models import RunRecord, SingleTestExecution
    from flakyhunter.polluter import investigate_polluter

    call_count = 0

    def mock_exec(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Call 1: baseline (victim alone) -> PASSED
        # Call 2: reproduction (candidates + victim) -> PASSED (fails to reproduce!)
        return RunRecord(
            run_index=call_count,
            seed=call_count,
            order=kwargs.get("order", []),
            results={"victim": SingleTestExecution(node_id="victim", outcome=TestOutcome.PASSED)},
        )

    monkeypatch.setattr("flakyhunter.polluter.execute_order_subprocess", mock_exec)

    inv = investigate_polluter(
        target_path="dummy",
        victim_node_id="victim",
        failing_order=["p1", "p2", "victim"],
    )

    assert inv.status == "non_reproducible"
    assert inv.verified is False
    assert inv.execution_count == 2


def test_investigate_polluter_verified_minimality(monkeypatch):
    """Verify end-to-end investigate_polluter finds and verifies a 1-minimal polluter."""
    from flakyhunter.models import RunRecord, SingleTestExecution
    from flakyhunter.polluter import investigate_polluter

    call_count = 0

    def mock_exec(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        order = kwargs.get("order", [])
        # Fails if and only if 'polluter' is in the order
        outcome = TestOutcome.FAILED if "polluter" in order else TestOutcome.PASSED
        return RunRecord(
            run_index=call_count,
            seed=call_count,
            order=order,
            results={"victim": SingleTestExecution(node_id="victim", outcome=outcome)},
        )

    monkeypatch.setattr("flakyhunter.polluter.execute_order_subprocess", mock_exec)

    inv = investigate_polluter(
        target_path="dummy",
        victim_node_id="victim",
        failing_order=["noise1", "polluter", "noise2", "victim"],
    )

    assert inv.status == "reproduced_and_minimized"
    assert inv.verified is True
    assert inv.minimized_polluter_set == ["polluter"]
    assert inv.baseline_outcome == TestOutcome.PASSED
    assert inv.reproduction_outcome == TestOutcome.FAILED
