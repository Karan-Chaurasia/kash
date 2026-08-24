"""Serve the Kosh dashboard. The report is recomputed on every load."""
import http.server
import json
import os
import socketserver

import generate
from run import build

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8000


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] == "/report.json":
            body = json.dumps(build()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path in ("/", ""):
            self.path = "/dashboard.html"
        return super().do_GET()

    def log_message(self, *args):
        pass


def main():
    os.chdir(HERE)
    if not os.path.exists(os.path.join(HERE, "data", "orders.csv")):
        generate.main()
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Kosh dashboard: http://localhost:{PORT}/")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
