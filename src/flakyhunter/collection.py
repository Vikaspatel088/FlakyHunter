"""Test discovery and node ID collection via pytest subprocess."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class CollectionError(Exception):
    """Raised when pytest fails to collect tests from target path."""


def collect_tests(target_path: Path | str, python_exe: str | None = None) -> list[str]:
    """Collect stable pytest test node IDs from a path.

    Args:
        target_path: File or directory path to inspect.
        python_exe: Python executable to run pytest with (defaults to sys.executable).

    Returns:
        List of unique, ordered test node IDs.

    Raises:
        CollectionError: If test collection fails.
    """
    python_cmd = python_exe or sys.executable
    path_str = str(Path(target_path).resolve())

    cmd = [
        python_cmd,
        "-m",
        "pytest",
        "--collect-only",
        path_str,
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise CollectionError(f"Test collection timed out for {path_str}") from exc
    except Exception as exc:
        raise CollectionError(f"Failed to execute pytest collector: {exc}") from exc

    if proc.returncode != 0 and not proc.stdout:
        raise CollectionError(
            f"Pytest collection failed with code {proc.returncode}:\n{proc.stderr}"
        )

    node_ids: list[str] = []
    for line in proc.stdout.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        # Check if line looks like a pytest node ID
        if "::" in cleaned and not cleaned.startswith("no tests collected"):
            node_ids.append(cleaned)

    if not node_ids:
        # Check if pytest reported an error or empty collection
        if "ERROR" in proc.stdout or "ERROR" in proc.stderr:
            raise CollectionError(f"Collection encountered errors:\n{proc.stdout}\n{proc.stderr}")
        raise CollectionError(f"No test items collected from path: {path_str}")

    return node_ids
