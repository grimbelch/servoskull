"""Standalone Web Server entrypoint for Omega-7 (omega7-web.service).

Allows running and restarting the web remote server independently from the core
Servo Skull hardware process without triggering speech synthesis or hardware re-init.
"""

from __future__ import annotations
import sys
import time
from core import config, web


def main() -> None:
    port = getattr(config, "WEB_SERVER_PORT", 8080)
    print(f"[web-server] Starting standalone Omega-7 Web Remote Server on port {port}...")
    web._run_server(port)


if __name__ == "__main__":
    main()
