"""Export secret-free Loop daemon health and swap counts for Prometheus."""
import json
import os
import ssl
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import Request, urlopen

LOOP_URL = "https://127.0.0.1:8081"
LOOP_DIR = os.environ.get("LOOP_DIR", "/loop")
NETWORK = os.environ.get("LOOP_NETWORK", "testnet")


def loop_request(path):
    macaroon_path = f"{LOOP_DIR}/{NETWORK}/loop.macaroon"
    context = ssl.create_default_context(cafile=f"{LOOP_DIR}/tls.cert")
    with open(macaroon_path, "rb") as source:
        macaroon = source.read().hex()
    request = Request(f"{LOOP_URL}{path}", headers={"Grpc-Metadata-macaroon": macaroon})
    with urlopen(request, context=context, timeout=5) as response:
        return json.load(response)


def metrics():
    try:
        info = loop_request("/v1/loop/info")
        swaps = loop_request("/v1/loop/swaps").get("swaps", [])
        state_counts = {}
        for swap in swaps:
            state = str(swap.get("state", "UNKNOWN")).lower()
            state_counts[state] = state_counts.get(state, 0) + 1
        lines = [
            "# HELP lnd_ops_loop_healthy Loop daemon API health.",
            "# TYPE lnd_ops_loop_healthy gauge",
            "lnd_ops_loop_healthy 1",
            "# HELP lnd_ops_loop_swaps_total Loop swaps grouped by current state.",
            "# TYPE lnd_ops_loop_swaps_total gauge",
        ]
        for state, count in sorted(state_counts.items()):
            lines.append(f'lnd_ops_loop_swaps_total{{state="{state}"}} {count}')
        if not info:
            raise ValueError("Loop info response was empty")
        return "\n".join(lines) + "\n"
    except Exception:
        return "# HELP lnd_ops_loop_healthy Loop daemon API health.\n# TYPE lnd_ops_loop_healthy gauge\nlnd_ops_loop_healthy 0\n"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/metrics":
            self.send_error(404)
            return
        body = metrics().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 9094), Handler).serve_forever()
