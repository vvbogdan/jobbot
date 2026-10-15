# -*- coding: utf-8 -*-
"""health — the minimal HTTP endpoint a Render Web Service (PORT) and UptimeRobot ping to confirm
the process is alive. No other module depends on this one."""
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from .logutil import log


def start_health_server():
    """Minimal HTTP endpoint for a Render Web Service (PORT) + UptimeRobot pings."""
    port = os.environ.get("PORT")
    if not port:
        return

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"jobbot ok")

        do_HEAD = do_GET  # noqa: N815

        def log_message(self, *a):
            pass

    srv = HTTPServer(("0.0.0.0", int(port)), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f"health server on port {port}")
