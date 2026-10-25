"""Script to generate authentic visual evidence for FlakyHunter using headless Chrome and Pillow."""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
SCREENSHOTS_DIR = WORKSPACE_DIR / "assets" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATH = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
if not CHROME_PATH.is_file():
    CHROME_PATH = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")

PORT = 8899
SERVER_URL = f"http://127.0.0.1:{PORT}"


def wait_for_server(timeout_sec: float = 10.0) -> bool:
    start = time.time()
    while time.time() - start < timeout_sec:
        try:
            with urllib.request.urlopen(f"{SERVER_URL}/health", timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def take_screenshot(url: str, output_path: Path, width: int = 1280, height: int = 900) -> None:
    cmd = [
        str(CHROME_PATH),
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        f"--window-size={width},{height}",
        f"--screenshot={output_path.resolve()}",
        url,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if not output_path.is_file():
        raise RuntimeError(f"Screenshot failed for {url}. Output: {res.stderr}")
    print(f"[+] Screenshot captured: {output_path.name} ({output_path.stat().st_size // 1024} KB)")


def create_terminal_run_screenshot(output_path: Path) -> None:
    """Capture real CLI output and render a high-contrast developer terminal screenshot."""
    cli_cmd = [
        sys.executable,
        "-m",
        "flakyhunter.cli",
        "run",
        "demo/flaky_demo",
        "--runs",
        "15",
        "--seed",
        "7777",
    ]
    print("[*] Running actual CLI command against demo/flaky_demo...")
    res = subprocess.run(
        cli_cmd, cwd=str(WORKSPACE_DIR), capture_output=True, text=True, check=False
    )
    raw_output = res.stdout

    # Create HTML terminal card
    escaped_output = (
        raw_output.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("[Run", '<span style="color:#60a5fa">[Run</span>')
        .replace("failures observed", '<span style="color:#f87171">failures observed</span>')
        .replace(
            "FLAKYHUNTER INVESTIGATION SUMMARY",
            '<span style="color:#a78bfa; font-weight:bold">FLAKYHUNTER INVESTIGATION SUMMARY</span>',
        )
        .replace("YES", '<span style="color:#f87171; font-weight:bold">YES</span>')
        .replace("NO", '<span style="color:#34d399; font-weight:bold">NO</span>')
        .replace(
            "shared state", '<span style="color:#f472b6; font-weight:bold">shared state</span>'
        )
        .replace("network", '<span style="color:#60a5fa; font-weight:bold">network</span>')
        .replace("randomness", '<span style="color:#c084fc; font-weight:bold">randomness</span>')
        .replace(
            "Verified Order-Dependent Findings:",
            '<span style="color:#fbbf24; font-weight:bold">Verified Order-Dependent Findings:</span>',
        )
    )

    terminal_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{
    background: #0f172a;
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
    margin: 0;
    padding: 24px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  }}
  .window {{
    width: 100%;
    max-width: 1100px;
    background: #1e293b;
    border-radius: 10px;
    box-shadow: 0 20px 50px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.1);
    overflow: hidden;
  }}
  .titlebar {{
    background: #0f172a;
    padding: 12px 16px;
    display: flex;
    align-items: center;
    gap: 8px;
    border-bottom: 1px solid #334155;
  }}
  .dot {{ width: 12px; height: 12px; border-radius: 50%; display: inline-block; }}
  .dot-red {{ background: #ef4444; }}
  .dot-yellow {{ background: #f59e0b; }}
  .dot-green {{ background: #10b981; }}
  .title {{
    color: #94a3b8;
    font-size: 13px;
    margin-left: 12px;
    font-family: system-ui, sans-serif;
  }}
  pre {{
    color: #e2e8f0;
    font-size: 13px;
    line-height: 1.5;
    padding: 20px;
    margin: 0;
    overflow-x: auto;
    white-space: pre-wrap;
  }}
</style>
</head>
<body>
<div class="window">
  <div class="titlebar">
    <span class="dot dot-red"></span>
    <span class="dot dot-yellow"></span>
    <span class="dot dot-green"></span>
    <span class="title">terminal &mdash; flakyhunter run demo/flaky_demo --runs 15 --seed 7777</span>
  </div>
  <pre><code>$ flakyhunter run demo/flaky_demo --runs 15 --seed 7777\n{escaped_output}</code></pre>
</div>
</body>
</html>
"""
    tmp_html = WORKSPACE_DIR / "scripts" / "_terminal_render.html"
    tmp_html.write_text(terminal_html, encoding="utf-8")
    try:
        take_screenshot(f"file:///{tmp_html.resolve()}", output_path, width=1200, height=920)
    finally:
        tmp_html.unlink(missing_ok=True)


def main():
    print(f"[*] Starting FlakyHunter dashboard server on {SERVER_URL}...")
    server_process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"from flakyhunter.web import create_app; import uvicorn; app=create_app('sample_results'); uvicorn.run(app, host='127.0.0.1', port={PORT}, log_level='warning')",
        ],
        cwd=str(WORKSPACE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        if not wait_for_server():
            raise RuntimeError("FastAPI server failed to start within timeout.")
        print("[+] Server ready.")

        # 1. Dashboard screenshot
        take_screenshot(f"{SERVER_URL}/", SCREENSHOTS_DIR / "dashboard.png", width=1280, height=880)

        # 2. Report Detail screenshot
        take_screenshot(
            f"{SERVER_URL}/reports/demo_report",
            SCREENSHOTS_DIR / "report-detail.png",
            width=1280,
            height=1000,
        )

        # 3. Upload Success screenshot
        take_screenshot(
            f"{SERVER_URL}/?success_id=report_7777_demo",
            SCREENSHOTS_DIR / "upload-success.png",
            width=1280,
            height=880,
        )

        # 4. Upload Validation Error screenshot
        take_screenshot(
            f"{SERVER_URL}/?error=Report+schema+validation+failed%3A+Field+%27tests%27+is+required+in+schema+version+1.0.0",
            SCREENSHOTS_DIR / "upload-validation.png",
            width=1280,
            height=880,
        )

        # 5. Terminal Run screenshot
        create_terminal_run_screenshot(SCREENSHOTS_DIR / "terminal-run.png")

        # 6. Generate authentic animated GIF
        gif_path = WORKSPACE_DIR / "assets" / "flakyhunter-demo.gif"
        print("[*] Generating workflow GIF from captured visual frames...")
        frames = [
            Image.open(SCREENSHOTS_DIR / "terminal-run.png").resize((960, 600)),
            Image.open(SCREENSHOTS_DIR / "dashboard.png").resize((960, 600)),
            Image.open(SCREENSHOTS_DIR / "upload-success.png").resize((960, 600)),
            Image.open(SCREENSHOTS_DIR / "report-detail.png").resize((960, 600)),
        ]
        # Frame durations in milliseconds
        durations = [2500, 2500, 2500, 3500]
        frames[0].save(
            gif_path,
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            optimize=True,
        )
        print(f"[+] Demo GIF generated: {gif_path.name} ({gif_path.stat().st_size // 1024} KB)")

        print("[+] All visual evidence generated successfully.")

    finally:
        server_process.terminate()
        try:
            server_process.wait(timeout=2.0)
        except Exception:
            server_process.kill()


if __name__ == "__main__":
    main()
