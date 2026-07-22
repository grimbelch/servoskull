#!/usr/bin/env python3
import os
import sys
import time
import subprocess
import threading
from http.server import HTTPServer
from skull import web

def render_mobile_screenshots():
    # 1. Start web server locally on port 8888
    server_address = ('127.0.0.1', 8999)
    httpd = HTTPServer(server_address, web.WebRequestHandler)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    print("Local web server started on http://127.0.0.1:8999")
    time.sleep(1)

    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    artifact_dir = "/Users/sean/.gemini/antigravity/brain/d88509f5-5bf6-48e8-86a6-cc0849c94b61"

    viewports = [
        ("mobile_390x844.png", 390, 844),
        ("mobile_360x740.png", 360, 740),
        ("mobile_320x568.png", 320, 568),
    ]

    for filename, width, height in viewports:
        out_path = os.path.join(artifact_dir, filename)
        cmd = [
            chrome_path,
            "--headless=new",
            f"--window-size={width},{height}",
            "--hide-scrollbars",
            f"--screenshot={out_path}",
            "http://127.0.0.1:8999"
        ]
        print(f"Capturing mobile screenshot for viewport {width}x{height} -> {filename}...")
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            print(f"Successfully generated screenshot: {out_path}")
        else:
            print(f"Error rendering {filename}: {res.stderr}")

    httpd.shutdown()
    print("Test complete.")

if __name__ == "__main__":
    render_mobile_screenshots()
