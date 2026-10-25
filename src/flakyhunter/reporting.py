"""Report generation, terminal output formatting, and WOW line generation."""

from __future__ import annotations

from flakyhunter.models import Report, TestSummary


def format_wow_line(summary: TestSummary) -> str | None:
    """Format the required WOW polluter line if supported by verified investigation evidence.

    Example required style:
        test_cart_total fails only after test_user_login (p=0.83). Polluter found in 14 runs.

    Args:
        summary: TestSummary with completed investigation.

    Returns:
        Formatted WOW string if verified, or None.
    """
    inv = summary.polluter_investigation
    if not inv or not inv.verified or not inv.minimized_polluter_set:
        return None

    # Check baseline passed (meaning it didn't fail on its own)
    if inv.baseline_outcome.value != "passed":
        return None

    # Extract clean test names for human readability
    victim_clean = summary.node_id.split("::")[-1]
    polluters_clean = [p.split("::")[-1] for p in inv.minimized_polluter_set]

    p_str = f"p={summary.failure_probability:.2f}"
    runs_count = inv.execution_count

    if len(polluters_clean) == 1:
        return f"{victim_clean} fails only after {polluters_clean[0]} ({p_str}). Polluter found in {runs_count} runs."
    else:
        polluter_list_str = " + ".join(polluters_clean)
        return f"{victim_clean} fails only after [{polluter_list_str}] ({p_str}). Polluter set found in {runs_count} runs."


def print_terminal_summary(report: Report) -> None:
    """Print an informative, recruiter-quality terminal summary for the FlakyHunter run."""
    print("\n" + "=" * 70)
    print(" FLAKYHUNTER INVESTIGATION SUMMARY")
    print("=" * 70)
    print(f"Target:               {report.target_path}")
    print(f"Master Seed:          {report.seed}")
    print(f"Executed Runs:        {report.actual_runs} of {report.requested_runs}")
    print(f"Total Test Execs:     {report.total_test_executions}")
    print(f"Investigation Execs:  {report.investigation_execution_count}")
    print("-" * 70)

    flaky_count = sum(1 for t in report.tests.values() if t.is_flaky)
    total_tests = len(report.tests)
    print(f"Identified Flaky Tests: {flaky_count} / {total_tests}\n")

    # Table Header
    print(
        f"{'Test Identifier':<38} {'P(Fail)':<9} {'95% Wilson CI':<16} {'Flaky?':<7} {'Likely Cause':<12}"
    )
    print("-" * 84)

    for test in report.tests.values():
        name = test.node_id.split("::")[-1][:36]
        p_val = f"{test.failure_probability:.3f}"
        ci_str = f"[{test.confidence_interval.lower:.2f}, {test.confidence_interval.upper:.2f}]"
        flaky_str = "YES" if test.is_flaky else "NO"
        cause_str = test.cause.category if test.is_flaky else "-"

        print(f"{name:<38} {p_val:<9} {ci_str:<16} {flaky_str:<7} {cause_str:<12}")

    print("-" * 84)

    # Print verified order-dependent findings (WOW lines)
    wow_lines = []
    for test in report.tests.values():
        wow = format_wow_line(test)
        if wow:
            wow_lines.append(wow)

    if wow_lines:
        print("\n Verified Order-Dependent Findings:")
        for line in wow_lines:
            print(f"  >>> {line}")

    print("=" * 84 + "\n")
