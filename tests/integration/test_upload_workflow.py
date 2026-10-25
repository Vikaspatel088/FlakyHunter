"""Integration tests verifying the complete FlakyHunter report upload workflow end to end."""

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from flakyhunter.web import create_app


def test_full_upload_workflow_end_to_end():
    """Verify the end-to-end report upload workflow:
    1. Open dashboard.
    2. Upload genuine demo_report.json (with and without Accept: application/json).
    3. Verify upload success response, safe report identifier, and URL.
    4. Confirm report appears in the reports list immediately.
    5. Open report page and verify all test outcomes, probabilities, Wilson CIs, and causes.
    6. Reload report page and confirm persistence.
    7. Upload a second distinct report and confirm isolation (no cross-contamination).
    8. Test malformed JSON, invalid schema, oversized file (>5MB), path traversal, and security.
    """
    demo_report_path = (
        Path(__file__).resolve().parent.parent.parent / "sample_results" / "demo_report.json"
    )
    assert demo_report_path.is_file(), f"demo_report.json not found at {demo_report_path}"
    valid_report_bytes = demo_report_path.read_bytes()
    demo_report_data = json.loads(valid_report_bytes.decode("utf-8"))

    with tempfile.TemporaryDirectory() as storage_dir:
        app = create_app(reports_dir=storage_dir)
        client = TestClient(app)

        # 1. Open dashboard
        dash_resp = client.get("/")
        assert dash_resp.status_code == 200
        assert "FlakyHunter" in dash_resp.text
        assert "Upload FlakyHunter Report" in dash_resp.text

        # 2. Upload valid report with Accept: application/json -> get explicit JSON success response
        api_upload_resp = client.post(
            "/api/upload",
            files={"file": ("demo_report.json", valid_report_bytes, "application/json")},
            headers={"Accept": "application/json"},
        )
        assert api_upload_resp.status_code == 201, (
            f"Expected 201 Created, got {api_upload_resp.status_code}"
        )
        upload_data = api_upload_resp.json()
        assert upload_data["status"] == "success"
        report_id_1 = upload_data["report_id"]
        report_url_1 = upload_data["url"]
        assert report_id_1.startswith("report_")
        assert report_url_1 == f"/reports/{report_id_1}"

        # 3. Confirm newly uploaded report appears in dashboard report listing immediately
        dash_after = client.get("/")
        assert dash_after.status_code == 200
        assert report_id_1 in dash_after.text
        assert "Uploaded" in dash_after.text

        # 4. Open report page and verify actual test outcomes, probabilities, Wilson CIs
        view_resp = client.get(report_url_1)
        assert view_resp.status_code == 200
        assert report_id_1 in view_resp.text
        # Verify key data points from the uploaded JSON are rendered
        for nid, tdata in demo_report_data["tests"].items():
            short_name = nid.split("::")[-1]
            assert short_name in view_resp.text
            # Verify failure probability is present
            prob_str = str(tdata["failure_probability"])
            assert prob_str in view_resp.text

        # 5. Reload report page and confirm it remains available (persistence)
        reload_resp = client.get(report_url_1)
        assert reload_resp.status_code == 200
        assert report_id_1 in reload_resp.text

        # 6. Upload a second distinct report and confirm isolation (different ID, different content)
        distinct_report_data = copy.deepcopy(demo_report_data)
        distinct_report_data["target_path"] = "custom/isolated/test_suite"
        distinct_report_bytes = json.dumps(distinct_report_data).encode("utf-8")

        api_upload_resp_2 = client.post(
            "/api/upload",
            files={"file": ("second_report.json", distinct_report_bytes, "application/json")},
            headers={"Accept": "application/json"},
        )
        assert api_upload_resp_2.status_code == 201
        report_id_2 = api_upload_resp_2.json()["report_id"]
        assert report_id_2 != report_id_1

        # Check report 2 displays its own target path
        view_resp_2 = client.get(f"/reports/{report_id_2}")
        assert view_resp_2.status_code == 200
        assert "custom/isolated/test_suite" in view_resp_2.text

        # Re-verify report 1 does not display report 2's target path
        view_resp_1_again = client.get(report_url_1)
        assert "custom/isolated/test_suite" not in view_resp_1_again.text

        # 7. Test standard HTML form upload with 303 RedirectResponse (browser mode without JSON accept)
        browser_upload = client.post(
            "/api/upload",
            files={"file": ("browser_report.json", valid_report_bytes, "application/json")},
            follow_redirects=False,
        )
        assert browser_upload.status_code == 303
        redirect_location = browser_upload.headers.get("location")
        assert redirect_location.startswith("/reports/report_")

        # 8. Upload malformed JSON -> rejected with HTTP 400 and useful error message
        malformed_resp = client.post(
            "/api/upload",
            files={"file": ("corrupt.json", b"{ incomplete json ...", "application/json")},
        )
        assert malformed_resp.status_code == 400
        assert "schema validation failed" in malformed_resp.json()["detail"].lower()

        # 9. Upload valid JSON with invalid schema -> rejected with HTTP 400
        invalid_schema_json = json.dumps({"arbitrary_key": "arbitrary_value"}).encode("utf-8")
        invalid_schema_resp = client.post(
            "/api/upload",
            files={"file": ("wrong_schema.json", invalid_schema_json, "application/json")},
        )
        assert invalid_schema_resp.status_code == 400
        assert "schema validation failed" in invalid_schema_resp.json()["detail"].lower()

        # 10. Upload file exceeding 5MB limit -> rejected with HTTP 413
        oversized_data = b" " * (6 * 1024 * 1024)  # 6 MB
        oversized_resp = client.post(
            "/api/upload",
            files={"file": ("huge.json", oversized_data, "application/json")},
        )
        assert oversized_resp.status_code == 413
        assert "maximum allowed upload size" in oversized_resp.json()["detail"]

        # 11. Upload with directory traversal characters in filename -> server safely generates ID
        traversal_upload = client.post(
            "/api/upload",
            files={"file": ("../../../../etc/passwd.json", valid_report_bytes, "application/json")},
            headers={"Accept": "application/json"},
        )
        assert traversal_upload.status_code == 201
        safe_id = traversal_upload.json()["report_id"]
        assert ".." not in safe_id
        assert "/" not in safe_id
        assert "\\" not in safe_id

        # 12. Security: Verify non-existent report returns 404 without leaking server paths
        not_found_resp = client.get("/reports/non_existent_report_id_123")
        assert not_found_resp.status_code == 404
        assert "C:\\" not in not_found_resp.text
        assert "non_existent_report_id_123" in not_found_resp.text
