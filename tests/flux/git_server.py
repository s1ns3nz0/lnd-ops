"""Credential-free, read-only smart Git HTTP fixture; isolated test network only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import subprocess
from urllib.parse import urlsplit


class Git(BaseHTTPRequestHandler):
    def handle_git(self):
        url = urlsplit(self.path)
        if 'git-receive-pack' in url.query or url.path.endswith('git-receive-pack'):
            self.send_error(403)
            return
        env = os.environ | {'GIT_PROJECT_ROOT': '/srv', 'GIT_HTTP_EXPORT_ALL': '1',
                            'REQUEST_METHOD': self.command, 'PATH_INFO': url.path,
                            'QUERY_STRING': url.query, 'CONTENT_TYPE': self.headers.get('Content-Type', ''),
                            'REMOTE_ADDR': self.client_address[0]}
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        p = subprocess.run(['git', 'http-backend'], input=body, capture_output=True, env=env)
        headers, _, data = p.stdout.partition(b'\r\n\r\n')
        parsed = [h.decode().split(':', 1) for h in headers.split(b'\r\n') if b':' in h]
        code = next((int(v.strip().split()[0]) for k, v in parsed if k.lower() == 'status'), 200)
        self.send_response(code)
        for key, value in parsed:
            if key.lower() != 'status':
                self.send_header(key, value.strip())
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = handle_git
    do_POST = handle_git


ThreadingHTTPServer(('0.0.0.0', 8000), Git).serve_forever()
