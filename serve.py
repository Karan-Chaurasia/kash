"""Serve the Kash dashboard. The report is recomputed on every load."""
import http.server
import json
import os
import socketserver
from urllib.parse import parse_qs, urlparse

import generate
from ask import answer
from run import build

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8000


class Handler(http.server.SimpleHTTPRequestHandler):
    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/report.json":
            return self._json(build())
        if path == "/ask":
            q = parse_qs(urlparse(self.path).query).get("q", [""])[0]
            return self._json({"answer": answer(q, build())})
        if path in ("/", ""):
            self.path = "/dashboard.html"
        return super().do_GET()

    def log_message(self, *args):
        pass


def main():
    os.chdir(HERE)
    if not os.path.exists(os.path.join(HERE, "data", "orders.csv")):
        generate.main()
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Kash dashboard: http://localhost:{PORT}/")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
