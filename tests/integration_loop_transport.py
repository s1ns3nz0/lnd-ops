"""Isolated TLS/authentication test for the in-Pod REST bridge, not a live swap.

Run in the repository's pinned Linux Python image. The server is a local fixture.
"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ops'))
from loop_api import POD_REQUEST


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                        '-subj', '/CN=localhost', '-addext', 'subjectAltName=IP:127.0.0.1',
                        '-keyout', str(root / 'key'), '-out', str(root / 'tls.cert')],
                       check=True, capture_output=True)
        secret = b'fixture-only-not-an-lnd-credential'
        (root / 'loop.macaroon').write_bytes(secret)
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                assert self.headers['Grpc-Metadata-macaroon'] == secret.hex()
                if self.path == '/unauthorized':
                    self.send_response(401); self.end_headers(); self.wfile.write(secret); return
                self.send_response(200); self.end_headers()
                self.wfile.write(b'{"network":"testnet"}')

            def do_POST(self):
                assert self.headers['Grpc-Metadata-macaroon'] == secret.hex()
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append((self.path, body))
                self.send_response(200); self.end_headers()
                self.wfile.write(b'{"id":"fixture-swap"}')

            def log_message(self, *_args): pass

        server = HTTPServer(('127.0.0.1', 0), Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(root / 'tls.cert'), str(root / 'key'))
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        script = POD_REQUEST.replace('/loop/testnet', str(root)).replace('127.0.0.1:8081', f'127.0.0.1:{server.server_port}')
        try:
            for spec in ({'path': '/v1/loop/info', 'method': 'GET'},
                         {'path': '/v1/loop/out', 'method': 'POST', 'body': {'amt': '1000', 'label': 'fixture'}},
                         {'path': '/unauthorized', 'method': 'GET'}):
                result = subprocess.run([sys.executable, '-c', script, json.dumps(spec)], check=True, capture_output=True, text=True)
                assert secret.hex() not in result.stdout + result.stderr
                assert secret.decode() not in result.stdout + result.stderr
                parsed = json.loads(result.stdout)
                if spec['path'] == '/unauthorized': assert parsed == {'transport_error': 'Loop API HTTP 401'}
                else: assert 'transport_error' not in parsed
            assert requests == [('/v1/loop/out', {'amt': '1000', 'label': 'fixture'})]
        finally:
            server.shutdown(); server.server_close(); thread.join()
    print('PASS Linux Loop REST bridge: verified TLS, auth, single POST, sanitized failures (fixture server)')


if __name__ == '__main__': main()
