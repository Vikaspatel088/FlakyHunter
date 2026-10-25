"""Data models for FlakyHunter reports, test outcomes, and investigation records."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class TestOutcome(StrEnum):
    """Normalized outcomes for individual test executions."""

    __test__ = False
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"
    INCONCLUSIVE = "inconclusive"


class SingleTestExecution(BaseModel):
    """Result of running a single test case within a specific run."""

    node_id: str
    outcome: TestOutcome
    duration_seconds: float = 0.0
    stdout: str = ""
    stderr: str = ""
    error_message: str | None = None
    failure_repr: str | None = None


class RunRecord(BaseModel):
    """Record of a complete test suite execution with a specific order."""

    run_index: int
    seed: int
    order: list[str]
    results: dict[str, SingleTestExecution]
    exit_code: int = 0
    duration_seconds: float = 0.0


class ConfidenceInterval(BaseModel):
    """Confidence interval for failure probability."""

    lower: float = Field(ge=0.0, le=1.0)
    upper: float = Field(ge=0.0, le=1.0)
    confidence_level: float = 0.95


CauseCategory = Literal["time", "randomness", "network", "shared state", "unknown"]


class CauseClassification(BaseModel):
    """Heuristic classification of root cause for a flaky test."""

    category: CauseCategory = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


class PolluterInvestigation(BaseModel):
    """Results from delta debugging investigation for an order-dependent failure."""

    victim_node_id: str
    baseline_outcome: TestOutcome
    reproduction_outcome: TestOutcome
    original_candidate_set: list[str]
    minimized_polluter_set: list[str]
    execution_count: int
    budget_exhausted: bool = False
    verified: bool = False
    status: str
    message: str


class TestSummary(BaseModel):
    """Statistical summary and diagnosis for a single test across all runs."""

    __test__ = False
    node_id: str
    eligible_runs: int
    passes: int
    failures: int
    skips: int = 0
    inconclusive: int = 0
    failure_probability: float = Field(ge=0.0, le=1.0)
    confidence_interval: ConfidenceInterval
    is_flaky: bool
    cause: CauseClassification = Field(default_factory=CauseClassification)
    polluter_investigation: PolluterInvestigation | None = None


class Report(BaseModel):
    """Complete machine-readable JSON report for FlakyHunter execution."""

    schema_version: str = "1.0.0"
    flakyhunter_version: str = "0.1.0"
    python_version: str
    pytest_version: str
    target_path: str
    seed: int
    requested_runs: int
    actual_runs: int
    run_orders: list[list[str]]
    tests: dict[str, TestSummary]
    total_test_executions: int
    investigation_execution_count: int = 0
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)
