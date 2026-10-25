"""Secure report persistence and loading with atomic writes and path sanitization."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from flakyhunter.models import Report

SAFE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]+$")


class StorageError(Exception):
    """Raised when report storage or retrieval encounters an error."""


def sanitize_report_id(report_id: str) -> str:
    """Validate and sanitize a report identifier to prevent directory traversal.

    Args:
        report_id: Candidate identifier.

    Returns:
        Validated identifier string.

    Raises:
        StorageError: If report_id contains invalid or unsafe characters.
    """
    clean_id = report_id.strip()
    if not clean_id or not SAFE_ID_REGEX.match(clean_id):
        raise StorageError(
            f"Invalid report ID '{report_id}'. Must be alphanumeric with hyphens or underscores only."
        )
    return clean_id


def get_report_path(base_dir: Path | str, report_id: str) -> Path:
    """Resolve a report ID to an absolute path within the designated base directory."""
    clean_id = sanitize_report_id(report_id)
    base = Path(base_dir).resolve()
    target = (base / f"{clean_id}.json").resolve()

    # Ensure resolved path remains strictly within base directory
    if not target.is_relative_to(base):
        raise StorageError("Path traversal attempt detected.")

    return target


def save_report_atomic(report: Report, destination: Path | str) -> Path:
    """Save a Report model to disk using an atomic write.

    Writes to a temporary sibling file first and renames it atomically to prevent partial writes.

    Args:
        report: Report Pydantic model.
        destination: Target file path.

    Returns:
        The written Path.
    """
    dest = Path(destination).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    json_data = report.model_dump_json(indent=2)

    # Write to a temporary file in the same directory, then atomic rename
    tmp_fd, tmp_path_str = tempfile.mkstemp(
        dir=dest.parent,
        prefix="flaky_tmp_",
        suffix=".json",
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(json_data)
        tmp_path.replace(dest)
    except Exception as exc:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise StorageError(f"Failed to atomically write report to {dest}: {exc}") from exc

    return dest


def load_report(source: Path | str) -> Report:
    """Load and validate a Report model from a JSON file.

    Args:
        source: File path to load.

    Returns:
        Validated Report instance.

    Raises:
        StorageError: If reading or schema validation fails.
    """
    path = Path(source).resolve()
    if not path.is_file():
        raise StorageError(f"Report file not found: {path}")

    try:
        content = path.read_text(encoding="utf-8")
        return Report.model_validate_json(content)
    except Exception as exc:
        raise StorageError(f"Invalid or malformed report file {path}: {exc}") from exc
