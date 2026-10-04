"""Local UI QA fixture: demo tickets, enlarged text, optional cancellable delay.

Run: .venv/bin/python tests/ui_preview_server.py --port 8768 --text-scale 2 --delay 4
No real ticket sources or browser sessions are used by this fixture.
"""
from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from student_trip.query_control import check_cancelled
from student_trip.server import Handler, WEB_ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--text-scale", type=float, default=1)
    parser.add_argument("--delay", type=float, default=0)
    args = parser.parse_args()

    class PreviewHandler(Handler):
        def do_GET(self):
            if self.path in ("/", "/index.html"):
                page = (WEB_ROOT / "index.html").read_text()
                # Source-level fixture, not an injected browser automation mutation.
                page = page.replace("</head>", f"<style>:root {{ font-size: {args.text_scale * 100:g}%; }}</style></head>")
                body = page.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def _plan(self, data):
            until = time.monotonic() + min(max(args.delay, 0), 10)
            while time.monotonic() < until:
                check_cancelled()
                time.sleep(.05)
            super()._plan(data)

    print(f"UI QA (demo only): http://127.0.0.1:{args.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), PreviewHandler).serve_forever()


if __name__ == "__main__":
    main()
