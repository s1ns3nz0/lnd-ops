#!/usr/bin/env python3
"""Synthetic Aperture L402 metrics for the local rehearsal lab (not real Aperture).

Exposes exactly the 17 aperture_l402_* series the funnel tool and alert rules read. Each counter grows
at a per-minute rate read from RATES_FILE on every scrape:
  {"mint": {"ok": 2}, "verify": {"missing_credentials": 2, "accepted": 1}}
Missing/invalid file or value means rate 0. Counters only ever increase, whatever the rates do.
"""

import json
import math
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MINT = ("ok", "challenge_failed", "identifier_failed", "secret_failed", "macaroon_failed", "caveat_failed")
VERIFY = ("accepted", "credential_verified", "missing_credentials", "malformed_credentials", "malformed_identifier",
          "payment_proof_mismatch", "unknown_credential", "secret_store_error", "invalid_signature",
          "restriction_failure", "invoice_state_mismatch")
FAMILIES = (("mint", "aperture_l402_mint_total", "result", MINT),
            ("verify", "aperture_l402_verify_total", "reason", VERIFY))


class Exporter:
    def __init__(self, rates_path, clock=time.monotonic):
        self.path, self.clock = rates_path, clock
        self.totals = {(f, v): 0.0 for f, _, _, values in FAMILIES for v in values}
        self.last = clock()
        self.lock = threading.Lock()

    def _rates(self):
        try:
            with open(self.path) as stream:
                data = json.load(stream)
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        out = {}
        for family, _, _, values in FAMILIES:
            group = data.get(family)
            group = group if isinstance(group, dict) else {}
            for value in values:
                rate = group.get(value)
                ok = isinstance(rate, (int, float)) and not isinstance(rate, bool) and math.isfinite(rate) and rate > 0
                out[(family, value)] = float(rate) if ok else 0.0
        return out

    def render(self):
        with self.lock:
            now = self.clock()
            elapsed, self.last = max(0.0, now - self.last), now
            for key, rate in self._rates().items():
                self.totals[key] += rate * elapsed / 60
            lines = []
            for family, metric, label, values in FAMILIES:
                lines += [f"# HELP {metric} Synthetic Aperture L402 counter (rehearsal lab).", f"# TYPE {metric} counter"]
                lines += [f'{metric}{{{label}="{v}"}} {int(self.totals[(family, v)])}' for v in values]
            return "\n".join(lines) + "\n"


def make_handler(exporter):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/metrics":
                self.send_error(404)
                return
            body = exporter.render().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    return Handler


def listen_tcp(port):
    """Accept-and-close TCP listener standing in for Aperture's proxy port so the blackbox tcp_connect probe can pass."""
    server = socket.create_server(("0.0.0.0", port))
    def loop():
        while True:
            server.accept()[0].close()
    threading.Thread(target=loop, daemon=True).start()
    return server.getsockname()[1]


def main():
    listen_tcp(int(os.environ.get("PROXY_PORT", "8081")))
    exporter = Exporter(os.environ.get("RATES_FILE", "/state/rates.json"))
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "9000"))), make_handler(exporter)).serve_forever()


if __name__ == "__main__":
    main()
