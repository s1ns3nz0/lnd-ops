"""One bounded status subprocess; callers remain free to paint and accept input."""
import json
import os
import signal
import subprocess
import tempfile
import time


class StatusWorker:
    def __init__(self, command, env=None, interval=10, timeout=180):
        self.command, self.env = command, env
        self.interval, self.timeout = interval, timeout
        self.process = self.output = None
        self.due = 0
        self.started = 0

    def tick(self):
        now = time.monotonic()
        if self.process is None:
            if now < self.due:
                return None
            self.output = tempfile.TemporaryFile(mode="w+t")
            try:
                self.process = subprocess.Popen(self.command, env=self.env, stdin=subprocess.DEVNULL,
                                                stdout=self.output, stderr=subprocess.STDOUT, text=True,
                                                start_new_session=True)
            except BaseException:
                self.output.close()
                self.output = None
                raise
            self.started = now
            return None
        if self.process.poll() is None:
            if now - self.started < self.timeout:
                return None
            self.close()
            self.due = now + self.interval
            return {"code": "query_error", "message": "상태 조회 시간 초과; 다시 확인합니다", "attempted_at": time.time()}
        self.output.seek(0)
        text = self.output.read(1024 * 1024)
        try:
            result = json.loads(text)
            if not isinstance(result, dict) or result.get("schema") != "lnd-ops/router-status/v1" or not isinstance(result.get("code"), str):
                raise ValueError("invalid status schema")
            return result
        except ValueError:
            return {"code": "query_error", "message": "상태 응답을 읽을 수 없습니다", "attempted_at": time.time()}
        finally:
            self.output.close()
            self.process = self.output = None
            self.due = now + self.interval

    def close(self):
        if self.process is not None:
            # Kill the process group, including any kubectl/lncli descendants.
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.process.wait(timeout=1)
            self.process = None
        if self.output is not None:
            self.output.close()
            self.output = None

    def request_now(self):
        self.due = 0
