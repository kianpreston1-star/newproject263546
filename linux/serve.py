#!/usr/bin/env python3
"""Tiny local web server for Cloud AI.

Puter.js only works when the page is served by a web server, not opened as a file, so the
launcher runs this to serve the app at http://127.0.0.1:<port>/. It only hands out the app's
static files (the AI itself runs in Puter's cloud), uses a few MB of RAM and no CPU while idle,
and only listens on this computer.
"""
import functools
import http.server
import mimetypes
import sys
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8723
APP_DIR = Path(__file__).resolve().parent / "app"

mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # nothing reads the log

    def end_headers(self):
        # Revalidate on each load so re-running the installer updates the app straight away.
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def main():
    handler = functools.partial(Handler, directory=str(APP_DIR))
    with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    main()
