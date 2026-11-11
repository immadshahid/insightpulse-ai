"""Start the InsightPulse server on this computer, without any developer tools.

Creates a private signing secret in the project's .env the first time it runs (the file is
gitignored), then serves on all network addresses so a phone on the same Wi-Fi can connect.
"""

from __future__ import annotations

import os
import secrets
import socket
from pathlib import Path

import uvicorn

BACKEND = Path(os.path.abspath(__file__)).parent  # keeps the short drive letter on Windows
ENV_FILE = BACKEND.parent / ".env"
PORT = 8000


def ensure_secret() -> None:
    """Add a random JWT_SECRET to .env unless one is already set."""
    text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    if any(line.strip().startswith("JWT_SECRET=") for line in text.splitlines()):
        return
    if text and not text.endswith("\n"):
        text += "\n"
    ENV_FILE.write_text(f"{text}JWT_SECRET={secrets.token_urlsafe(48)}\n", encoding="utf-8")


def lan_address() -> str | None:
    """This computer's address on the local network (no traffic is sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("10.255.255.255", 1))
            return str(probe.getsockname()[0])
        except OSError:
            return None


def main() -> None:
    """Prepare the environment and run the API until the window is closed."""
    os.chdir(BACKEND)
    ensure_secret()
    address = lan_address()
    print("\n  InsightPulse server is starting. Keep this window open while using the app.")
    print(f"  Android emulator:  http://10.0.2.2:{PORT}")
    if address:
        print(f"  Phone on Wi-Fi:    http://{address}:{PORT}")
    print()
    uvicorn.run("app.main:app", host="0.0.0.0", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
