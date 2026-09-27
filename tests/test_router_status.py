import contextlib
import importlib.machinery
import io
import os
import pathlib
import sys
import unittest
import unittest.mock


REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "ops"))
loader = importlib.machinery.SourceFileLoader("lndops_start", str(REPO / "ops/start"))
start = loader.load_module()
ROUTER = start.PHASES[2]
DETAIL = "ACTION: open and confirm a second active public channel with routing liquidity (currently 1)"


class InteractiveOutput(io.StringIO):
    def isatty(self):
        return True


class RouterStatusTests(unittest.TestCase):
    def test_funding_progress_rows_fit_a_narrow_terminal(self):
        snapshot = {'code': 'funding_pending', 'funding_progress': '1~3블록 남음 · 일부 미제공',
                    'funding_expiry': '100블록 남음 (최소)'}
        output = InteractiveOutput()
        with unittest.mock.patch.object(start.sys, 'stdout', output), \
                unittest.mock.patch.object(start.shutil, 'get_terminal_size', return_value=os.terminal_size((40, 24))), \
                unittest.mock.patch.object(start.time, 'time', return_value=100):
            rows = start.render_router_snapshot(snapshot, None, 100, 0, None)
        self.assertTrue(all(start.display_width(row) <= 39 for row in rows))
        self.assertTrue(any('채널 확인' in row for row in rows))
        self.assertTrue(any('만료 조건' in row for row in rows))
        self.assertTrue(any('100블록' in row for row in rows))

    def test_stale_snapshot_never_displays_current_router_readiness_or_reachability(self):
        snapshot = {'code': 'complete', 'ready': True, 'external_reachability': 'operator_attested',
                    'external_expires_at': 300}
        for now in (99, 131):
            with unittest.mock.patch.object(start.time, 'time', return_value=now), \
                    unittest.mock.patch.object(start, 'render_router_lines', side_effect=lambda rows, previous: rows):
                rows = start.render_router_snapshot(snapshot, None, 100, 0, None)
            self.assertIn('새 조회 필요', rows[3])
            self.assertIn('미검증', rows[5])

    def test_external_expiry_is_reflected_between_status_polls(self):
        snapshot = {'code': 'complete', 'ready': True, 'external_reachability': 'operator_attested',
                    'external_expires_at': 110}
        with unittest.mock.patch.object(start.time, 'time', return_value=110), \
                unittest.mock.patch.object(start, 'render_router_lines', side_effect=lambda rows, previous: rows):
            rows = start.render_router_snapshot(snapshot, None, 100, 0, None)
        self.assertIn('가능', rows[3])
        self.assertIn('미검증', rows[5])

    def test_expired_completion_does_not_advance_phase(self):
        worker = unittest.mock.Mock()
        worker.tick.side_effect = [
            {"code": "complete", "complete": True, "checked_at": 99, "external_expires_at": 100},
            {"code": "wrong_network", "complete": False, "checked_at": 100},
        ]
        with unittest.mock.patch.object(start, "StatusWorker", return_value=worker), \
                unittest.mock.patch.object(start.time, "time", return_value=100), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(start.guide_router(3, ROUTER), "failed")
        worker.request_now.assert_called_once()
        worker.close.assert_called_once()

    def test_narrow_terminal_rows_never_wrap(self):
        output = InteractiveOutput()
        with unittest.mock.patch.object(start.sys, "stdout", output), unittest.mock.patch.object(
            start.shutil, "get_terminal_size", return_value=os.terminal_size((24, 20))
        ), unittest.mock.patch.object(start.time, "monotonic", return_value=10):
            lines = start.render_router_wait(ROUTER, 1, DETAIL, None, 0)

        self.assertEqual(len(lines), 4)
        self.assertTrue(all(start.display_width(line) <= 23 for line in lines))
        self.assertEqual(output.getvalue().count("\n"), 3)

    def test_tty_refresh_writes_only_the_changed_row(self):
        output = InteractiveOutput()
        with unittest.mock.patch.object(start.sys, "stdout", output), unittest.mock.patch.object(
            start.shutil, "get_terminal_size", return_value=os.terminal_size((80, 20))
        ), unittest.mock.patch.object(start.time, "monotonic", return_value=10):
            previous = start.render_router_wait(ROUTER, 1, DETAIL, None, 0)
        output.seek(0)
        output.truncate(0)

        with unittest.mock.patch.object(start.sys, "stdout", output), unittest.mock.patch.object(
            start.shutil, "get_terminal_size", return_value=os.terminal_size((80, 20))
        ), unittest.mock.patch.object(start.time, "monotonic", return_value=20):
            start.render_router_wait(ROUTER, 1, DETAIL, None, 0, previous)

        refreshed = output.getvalue()
        self.assertIn("경과 시간", refreshed)
        self.assertNotIn("공개 채널", refreshed)
        self.assertNotIn("대기 조건", refreshed)

    def test_non_tty_does_not_log_timer_only_refreshes(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), unittest.mock.patch.object(
            start.shutil, "get_terminal_size", return_value=os.terminal_size((80, 20))
        ), unittest.mock.patch.object(start.time, "monotonic", return_value=10):
            previous = start.render_router_wait(ROUTER, 1, DETAIL, None, 0)
        output.seek(0)
        output.truncate(0)

        with contextlib.redirect_stdout(output), unittest.mock.patch.object(
            start.shutil, "get_terminal_size", return_value=os.terminal_size((80, 20))
        ), unittest.mock.patch.object(start.time, "monotonic", return_value=20):
            start.render_router_wait(ROUTER, 1, DETAIL, None, 0, previous)

        self.assertEqual(output.getvalue(), "")

    def test_non_tty_logs_only_changed_status_rows(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), unittest.mock.patch.object(
            start.shutil, "get_terminal_size", return_value=os.terminal_size((80, 20))
        ), unittest.mock.patch.object(start.time, "monotonic", return_value=10):
            previous = start.render_router_wait(ROUTER, 1, DETAIL, 100, 0)
        output.seek(0)
        output.truncate(0)

        with contextlib.redirect_stdout(output), unittest.mock.patch.object(
            start.shutil, "get_terminal_size", return_value=os.terminal_size((80, 20))
        ), unittest.mock.patch.object(start.time, "monotonic", return_value=20):
            start.render_router_wait(ROUTER, 2, DETAIL, 100, 0, previous)

        refreshed = output.getvalue()
        self.assertIn("공개 채널", refreshed)
        self.assertNotIn("대기 조건", refreshed)
        self.assertNotIn("최근 채널 동기화", refreshed)
        self.assertNotIn("경과 시간", refreshed)

    def test_closing_live_block_starts_the_next_log_on_a_new_line(self):
        output = InteractiveOutput()
        with unittest.mock.patch.object(start.sys, "stdout", output):
            start.close_router_wait(("one", "two", "three", "four"))
            print("next")
        self.assertEqual(output.getvalue(), "\nnext\n")

    def test_elapsed_clock_refreshes_each_second_between_live_checks(self):
        rendered = tuple(f"line-{index}" for index in range(4))
        with unittest.mock.patch.object(start.time, "sleep") as sleep, unittest.mock.patch.object(
            start, "render_router_wait", return_value=rendered
        ) as render:
            result = start.refresh_router_clock(ROUTER, 1, DETAIL, 100, 0, rendered)

        self.assertEqual(result, rendered)
        self.assertEqual(sleep.call_count, start.ROUTER_POLL_SECONDS)
        self.assertTrue(all(call.args == (1,) for call in sleep.call_args_list))
        self.assertEqual(render.call_count, start.ROUTER_POLL_SECONDS)


if __name__ == "__main__":
    unittest.main()
