import pathlib
import sys
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ops"))
from router_worker import StatusWorker


class WorkerTests(unittest.TestCase):
    def test_slow_rpc_does_not_block_clock_or_launch_overlapping_queries(self):
        worker = StatusWorker([sys.executable, "-c", 'import time; time.sleep(.25); print(\'{"schema":"lnd-ops/router-status/v1","code":"syncing"}\')'], interval=10)
        self.addCleanup(worker.close)
        self.assertIsNone(worker.tick())
        pid = worker.process.pid
        ticks = 0
        deadline = time.monotonic() + 5
        result = None
        while time.monotonic() < deadline:
            before = time.monotonic()
            result = worker.tick()
            self.assertLess(time.monotonic() - before, .2)
            ticks += 1
            if result:
                break
            self.assertEqual(worker.process.pid, pid)
            time.sleep(.02)
        self.assertGreater(ticks, 2)
        self.assertEqual(result["code"], "syncing")
        self.assertIsNone(worker.tick())
        self.assertIsNone(worker.process)

    def test_timeout_stops_process_and_preserves_retry_cadence(self):
        worker = StatusWorker([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0)
        self.addCleanup(worker.close)
        worker.tick()
        process = worker.process
        result = worker.tick()
        self.assertEqual(result["code"], "query_error")
        self.assertIsNotNone(process.poll())
        self.assertIsNone(worker.process)
        self.assertIsNone(worker.tick())

    def test_malformed_output_is_error_not_completion(self):
        worker = StatusWorker([sys.executable, "-c", 'print("not json")'])
        self.addCleanup(worker.close)
        worker.tick()
        worker.process.wait(timeout=5)
        self.assertEqual(worker.tick()["code"], "query_error")

    def test_close_reaps_running_status_child(self):
        worker = StatusWorker([sys.executable, "-c", "import time; time.sleep(30)"])
        worker.tick()
        process = worker.process
        worker.close()
        self.assertIsNotNone(process.poll())
        self.assertIsNone(worker.output)


if __name__ == "__main__":
    unittest.main()
