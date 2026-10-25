"""Command-line interface for FlakyHunter."""

from __future__ import annotations

import argparse
import datetime
import random
import sys
from pathlib import Path

import pytest

from flakyhunter import __version__
from flakyhunter.collection import CollectionError
from flakyhunter.heuristics import classify_cause
from flakyhunter.models import Report, TestOutcome
from flakyhunter.polluter import investigate_polluter
from flakyhunter.probability import compute_test_summary
from flakyhunter.reporting import print_terminal_summary
from flakyhunter.runner import run_suite
from flakyhunter.storage import save_report_atomic


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="flakyhunter",
        description="FlakyHunter: Detect flaky tests, estimate failure probability, and isolate polluters.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"flakyhunter {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: run
    run_parser = subparsers.add_parser(
        "run", help="Run test suite across shuffled orders to detect flakiness."
    )
    run_parser.add_argument(
        "path",
        type=str,
        help="Path to pytest test file or directory.",
    )
    run_parser.add_argument(
        "--runs",
        type=int,
        default=10,
        help="Number of shuffled runs to execute (positive integer, default: 10).",
    )
    run_parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Integer seed for reproducible shuffling (default: randomly selected).",
    )
    run_parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Destination path for structured JSON report (default: flakyhunter_report.json).",
    )
    run_parser.add_argument(
        "--max-investigation-budget",
        type=int,
        default=30,
        help="Maximum test executions allowed per polluter investigation (default: 30).",
    )

    # Subcommand: serve
    serve_parser = subparsers.add_parser("serve", help="Start the FlakyHunter web dashboard.")
    serve_parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind server to (default: 0.0.0.0).",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind server to (default: 8000).",
    )
    serve_parser.add_argument(
        "--reports-dir",
        type=str,
        default="sample_results",
        help="Directory where JSON reports are stored (default: sample_results).",
    )

    return parser


def handle_run(args: argparse.Namespace) -> int:
    """Execute the 'run' command."""
    target_path = Path(args.path)
    if not target_path.exists():
        print(f"Error: Target path does not exist: {target_path}", file=sys.stderr)
        return 2

    if args.runs < 1:
        print(f"Error: --runs must be a positive integer (got {args.runs})", file=sys.stderr)
        return 2

    seed = args.seed if args.seed is not None else random.randint(1000, 999999)

    print(f"[*] FlakyHunter v{__version__} starting investigation")
    print(f"[*] Target: {target_path.resolve()}")
    print(f"[*] Requested runs: {args.runs} | Master seed: {seed}")

    try:

        def on_progress(current: int, total: int, rec) -> None:
            failed_count = sum(
                1
                for r in rec.results.values()
                if r.outcome in (TestOutcome.FAILED, TestOutcome.ERROR)
            )
            print(
                f"    [Run {current:02d}/{total:02d}] Seed {rec.seed}: {failed_count} failures observed"
            )

        node_ids, run_records = run_suite(
            target_path=target_path,
            runs=args.runs,
            seed=seed,
            progress_callback=on_progress,
        )
    except CollectionError as exc:
        print(f"Error collecting tests: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Operational error during test execution: {exc}", file=sys.stderr)
        return 1

    # Aggregate test summaries
    test_summaries = {}
    failing_runs_by_test: dict[str, list[list[str]]] = {}
    last_error_by_test: dict[str, str | None] = {}

    for nid in node_ids:
        outcomes: list[TestOutcome] = []
        for rec in run_records:
            test_res = rec.results.get(nid)
            outcome = test_res.outcome if test_res else TestOutcome.INCONCLUSIVE
            outcomes.append(outcome)
            if outcome in (TestOutcome.FAILED, TestOutcome.ERROR):
                if nid not in failing_runs_by_test:
                    failing_runs_by_test[nid] = []
                failing_runs_by_test[nid].append(rec.order)
                if test_res and test_res.error_message:
                    last_error_by_test[nid] = test_res.error_message

        summary = compute_test_summary(nid, outcomes)
        test_summaries[nid] = summary

    # Investigate flaky tests for order dependence via ddmin
    total_investigation_execs = 0
    for nid, summary in test_summaries.items():
        if summary.is_flaky and nid in failing_runs_by_test:
            failing_order = failing_runs_by_test[nid][0]
            print(f"[*] Investigating order dependency for flaky test: {nid}")
            inv = investigate_polluter(
                target_path=target_path,
                victim_node_id=nid,
                failing_order=failing_order,
                max_executions=args.max_investigation_budget,
            )
            summary.polluter_investigation = inv
            total_investigation_execs += inv.execution_count

        # Classify cause
        summary.cause = classify_cause(
            node_id=nid,
            error_message=last_error_by_test.get(nid),
            polluter_investigation=summary.polluter_investigation,
            source_root=target_path if target_path.is_dir() else target_path.parent,
        )

    total_test_executions = sum(len(r.results) for r in run_records)
    run_orders = [r.order for r in run_records]

    report = Report(
        schema_version="1.0.0",
        flakyhunter_version=__version__,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        pytest_version=pytest.__version__,
        target_path=str(target_path.resolve()),
        seed=seed,
        requested_runs=args.runs,
        actual_runs=len(run_records),
        run_orders=run_orders,
        tests=test_summaries,
        total_test_executions=total_test_executions,
        investigation_execution_count=total_investigation_execs,
        created_at=datetime.datetime.now(datetime.UTC).isoformat(),
    )

    # Persist report
    output_dest = Path(args.output) if args.output else Path("flakyhunter_report.json")
    save_report_atomic(report, output_dest)
    print(f"[+] Structured report saved atomically to: {output_dest.resolve()}")

    # Display console summary
    print_terminal_summary(report)
    return 0


def handle_serve(args: argparse.Namespace) -> int:
    """Execute the 'serve' command."""
    import uvicorn

    from flakyhunter.web import create_app

    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    app = create_app(reports_dir=reports_dir)

    print(f"[*] Starting FlakyHunter Web Server on http://{args.host}:{args.port}")
    print(f"[*] Serving reports from: {reports_dir.resolve()}")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        return handle_run(args)
    elif args.command == "serve":
        return handle_serve(args)
    else:
        parser.print_help()
        return 2


if __name__ == "__main__":
    sys.exit(main())
