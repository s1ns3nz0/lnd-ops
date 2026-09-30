#!/usr/bin/env python3
"""Tiny stand-in for an OpenCTI L402 health endpoint in the rehearsal lab (not the real service).

Usage: dummy_http.py PORT PATH BODY [CERT KEY]   GET PATH -> 200 BODY (JSON), anything else 404. With CERT and KEY it serves HTTPS.
"""
import ssl
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make_handler(path, body):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != path:
                self.send_error(404)
                return
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass
    return Handler


def main(argv):
    port, path, body, *tls = argv
    server = ThreadingHTTPServer(("0.0.0.0", int(port)), make_handler(path, body))
    if tls:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(*tls)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main(sys.argv[1:])
