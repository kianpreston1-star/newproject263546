#!/usr/bin/env python3
"""Tiny webhook receiver for testing clip/render callbacks locally.

Some clipping/render APIs can POST a "job done" callback instead of you polling.
During setup you can point them at this listener to see the exact payload, then
wire an n8n Webhook node to match.

Usage:
    python3 callback_listener.py [port]      # default 8099
    # then POST to http://<host>:<port>/callback

It prints every request and appends the JSON body to callbacks.log.
Not for production — it's a setup/debug aid only.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG = "callbacks.log"


class Handler(BaseHTTPRequestHandler):
    def _read(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(length) if length else b""

    def do_POST(self):
        raw = self._read()
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
            pretty = json.dumps(body, indent=2)
        except Exception:
            pretty = raw.decode("utf-8", "replace")
        print(f"\n--- POST {self.path} ---\n{pretty}\n")
        with open(LOG, "a") as f:
            f.write(pretty + "\n")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *a):  # quiet default logging
        pass


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    srv = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Listening on http://0.0.0.0:{port}/  (POST bodies logged to {LOG})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
