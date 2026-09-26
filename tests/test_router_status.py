import contextlib
import importlib.machinery
import io
import os
import pathlib
import unittest
import unittest.mock


REPO = pathlib.Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("lndops_start", str(REPO / "ops/start"))
start = loader.load_module()
ROUTER = start.PHASES[2]
DETAIL = "ACTION: open and confirm a second active public channel with routing liquidity (currently 1)"


class InteractiveOutput(io.StringIO):
    def isatty(self):
        return True


class RouterStatusTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
