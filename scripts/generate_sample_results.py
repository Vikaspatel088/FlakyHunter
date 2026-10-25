#!/usr/bin/env python3
"""Helper script to generate genuine sample results for deployment."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    """Run FlakyHunter against the demo suite and save results to sample_results/."""
    demo_dir = ROOT / "demo" / "flaky_demo"
    output_dir = ROOT / "sample_results"
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / "demo_report.json"

    print(f"Generating sample results from: {demo_dir}")
    print(f"Output destination: {output_file}")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "flakyhunter",
            "run",
            str(demo_dir),
            "--runs",
            "15",
            "--seed",
            "7777",
            "--output",
            str(output_file),
        ],
        check=False,
        cwd=ROOT,
    )

    if result.returncode != 0:
        print(f"FlakyHunter exited with code {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)

    print(f"\nSample report written to: {output_file}")
    print("Commit this file to include verified precomputed results in your deployment.")


if __name__ == "__main__":
    main()
