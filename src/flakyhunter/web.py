"""FastAPI dashboard application for viewing and securely uploading FlakyHunter reports."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from flakyhunter import __version__
from flakyhunter.models import Report
from flakyhunter.reporting import format_wow_line
from flakyhunter.storage import (
    StorageError,
    get_report_path,
    load_report,
    sanitize_report_id,
    save_report_atomic,
)

MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024  # 5 Megabytes


def create_app(reports_dir: Path | str = "sample_results") -> FastAPI:
    """Create and configure the FastAPI web dashboard application.

    Args:
        reports_dir: Directory containing stored JSON reports.

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(
        title="FlakyHunter Dashboard",
        description="Recruiter-ready dashboard for test flakiness analysis and polluter isolation.",
        version=__version__,
    )

    storage_path = Path(reports_dir).resolve()
    storage_path.mkdir(parents=True, exist_ok=True)

    templates_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        """Health check endpoint for deployment monitoring."""
        return {"status": "ok", "version": __version__}

    @app.get("/", response_class=HTMLResponse)
    async def index(
        request: Request, error: str | None = None, success_id: str | None = None
    ) -> HTMLResponse:
        """Dashboard home displaying list of available reports and upload form."""
        reports_meta = []
        # Sort by modification time descending so newest reports appear first
        json_files = sorted(
            storage_path.glob("*.json"),
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        )

        for json_file in json_files:
            try:
                rep_id = json_file.stem
                sanitize_report_id(rep_id)
                data = json.loads(json_file.read_text(encoding="utf-8"))
                tests_data = data.get("tests", {})
                flaky_count = sum(1 for t in tests_data.values() if t.get("is_flaky"))
                is_sample = rep_id == "demo_report"
                reports_meta.append(
                    {
                        "id": rep_id,
                        "is_sample": is_sample,
                        "target_path": data.get("target_path", "unknown"),
                        "actual_runs": data.get("actual_runs", 0),
                        "requested_runs": data.get("requested_runs", 0),
                        "flaky_count": flaky_count,
                        "total_tests": len(tests_data),
                        "total_executions": data.get("total_test_executions", 0),
                        "investigation_executions": data.get("investigation_execution_count", 0),
                        "created_at": data.get("created_at", ""),
                    }
                )
            except Exception:
                continue

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "reports": reports_meta,
                "version": __version__,
                "error": error,
                "success_id": success_id,
            },
        )

    @app.get("/reports/{report_id}", response_class=HTMLResponse)
    async def view_report(request: Request, report_id: str) -> HTMLResponse:
        """Display detailed diagnostic view of a specific report."""
        try:
            target_path = get_report_path(storage_path, report_id)
            report = load_report(target_path)
        except StorageError as exc:
            raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found.") from exc

        flaky_count = sum(1 for t in report.tests.values() if t.is_flaky)
        wow_lines = [line for line in (format_wow_line(t) for t in report.tests.values()) if line]
        is_sample = report_id == "demo_report"

        return templates.TemplateResponse(
            request=request,
            name="report.html",
            context={
                "report_id": report_id,
                "report": report,
                "flaky_count": flaky_count,
                "wow_lines": wow_lines,
                "is_sample": is_sample,
                "version": __version__,
            },
        )

    @app.get("/api/reports/{report_id}")
    async def get_report_json(report_id: str) -> dict:
        """Retrieve raw report JSON."""
        try:
            target_path = get_report_path(storage_path, report_id)
            report = load_report(target_path)
            return report.model_dump(mode="json")
        except StorageError as exc:
            raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found.") from exc

    @app.post("/api/upload")
    async def upload_report(request: Request, file: UploadFile = File(...)) -> Response:
        """Securely receive, validate against schema, and store an uploaded JSON report.

        Never executes uploaded code or invokes subprocesses. Supports both browser
        redirects and structured JSON responses for API/fetch clients.
        """
        if not file.filename or not file.filename.lower().endswith(".json"):
            raise HTTPException(status_code=400, detail="Only .json files are accepted.")

        # Enforce upload limit during reading to prevent unbounded memory allocation
        chunks: list[bytes] = []
        total_bytes = 0
        chunk_size = 64 * 1024  # 64 KB chunks
        while chunk := await file.read(chunk_size):
            total_bytes += len(chunk)
            if total_bytes > MAX_UPLOAD_SIZE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds maximum allowed upload size ({MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB).",
                )
            chunks.append(chunk)

        content_bytes = b"".join(chunks)

        try:
            content_str = content_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="File is not valid UTF-8 text.") from exc

        try:
            report = Report.model_validate_json(content_str)
        except Exception as exc:
            err_msg = str(exc).split("\n")[0] if "\n" in str(exc) else str(exc)
            raise HTTPException(
                status_code=400, detail=f"Report schema validation failed: {err_msg}"
            ) from exc

        # Store using a safe unique ID
        report_id = f"report_{uuid.uuid4().hex[:12]}"
        dest = get_report_path(storage_path, report_id)
        try:
            save_report_atomic(report, dest)
        except StorageError as exc:
            raise HTTPException(
                status_code=500, detail="Failed to persist report to storage."
            ) from exc

        # If client requested JSON (e.g. AJAX/fetch or API client), return structured JSON
        accept_header = request.headers.get("accept", "").lower()
        is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
        if "application/json" in accept_header or is_ajax:
            return JSONResponse(
                status_code=201,
                content={
                    "status": "success",
                    "report_id": report_id,
                    "url": f"/reports/{report_id}",
                    "message": "Report uploaded and validated successfully.",
                },
                headers={"Location": f"/reports/{report_id}"},
            )

        return RedirectResponse(url=f"/reports/{report_id}", status_code=303)

    return app
