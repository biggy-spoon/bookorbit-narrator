"""A tiny, dependency-free HTTP listener for the GPU host itself.

Lets the sidecar ask this machine to power off once it's done narrating and has
nothing else queued, so it doesn't sit awake idle burning power until the next
book shows up - it's woken again via Wake-on-LAN next time, same as always.

Deliberately minimal: one route, one token check, stdlib only. Run as root (via
the included systemd unit) since it needs to call `systemctl poweroff`.
"""

import hmac
import os
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = os.environ.get("SHUTDOWN_TOKEN", "")
PORT = int(os.environ.get("PORT", "8899"))


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/shutdown":
            self.send_response(404)
            self.end_headers()
            return

        presented = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if not TOKEN or not hmac.compare_digest(presented, TOKEN):
            self.send_response(401)
            self.end_headers()
            return

        self.send_response(202)
        self.end_headers()
        subprocess.run(["systemctl", "poweroff"], check=False)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - matches base signature
        pass  # systemd journal already captures stdout/stderr; no need to double-log per request


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("SHUTDOWN_TOKEN must be set")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
