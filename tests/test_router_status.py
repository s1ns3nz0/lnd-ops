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
    def test_prompt_stays_below_clock_and_refresh_does_not_erase_input(self):
        output = InteractiveOutput()
        prompt = start.ROUTER_INPUT_PROMPT
        with unittest.mock.patch.object(start.sys, 'stdout', output):
            start.render_router_lines(('status', 'clock 2', prompt), ('status', 'clock 1', prompt))
        update = output.getvalue()
        self.assertIn('\0337', update)
        self.assertIn('\033[1A\r\033[2Kclock 2\0338', update)
        self.assertNotIn(prompt, update)
        self.assertNotIn('\n', update)

    def test_dashboard_growth_moves_prompt_without_reprinting_it(self):
        output = InteractiveOutput()
        prompt = start.ROUTER_INPUT_PROMPT
        with unittest.mock.patch.object(start.sys, 'stdout', output):
            start.render_router_lines(('status', 'channels', 'clock', prompt), ('loading', 'clock', prompt))
        update = output.getvalue()
        self.assertIn('\033[1L', update)
        self.assertNotIn(prompt, update)
        self.assertNotIn('\033[J', update)

    def test_loading_has_a_dedicated_input_row_in_a_terminal(self):
        output = InteractiveOutput()
        with unittest.mock.patch.object(start.sys, 'stdout', output):
            rows = start.render_router_snapshot({'code': 'loading'}, None, None, 0, None)
        self.assertEqual(rows[-1], start.ROUTER_INPUT_PROMPT)
        self.assertTrue(output.getvalue().endswith('\n' + start.ROUTER_INPUT_PROMPT))

    def test_initial_loading_does_not_claim_unknown_resource_counts(self):
        with unittest.mock.patch.object(start, 'render_router_lines', side_effect=lambda rows, previous: rows):
            rows = start.render_router_snapshot({'code': 'loading'}, None, None, 0, None)
        self.assertEqual(len(rows), 2)
        self.assertIn('조회 중', rows[0])
        self.assertNotIn('?', '\n'.join(rows))

    def test_loading_to_dashboard_replaces_the_short_block(self):
        output = InteractiveOutput()
        with unittest.mock.patch.object(start.sys, 'stdout', output):
            start.render_router_lines(('state', 'channels', 'timer'), ('loading', 'timer'))
        self.assertIn('\033[1A\r\033[J', output.getvalue())
        self.assertIn('state\nchannels\ntimer', output.getvalue())

    def test_narrow_dashboard_wraps_guidance_without_losing_text(self):
        with unittest.mock.patch.object(start.shutil, 'get_terminal_size', return_value=os.terminal_size((40, 30))), \
                unittest.mock.patch.object(start, 'render_router_lines', side_effect=lambda rows, previous: rows), \
                unittest.mock.patch.object(start.time, 'time', return_value=100):
            rows = start.render_router_snapshot({'code': 'proof_required', 'ready': True}, None, 100, 0, None)
        self.assertTrue(all(start.display_width(row) <= 39 for row in rows))
        joined = ''.join(row.strip() for row in rows)
        self.assertIn('추가 입력 없이 실제 중계를 기다립니다.', joined)
        self.assertNotIn('만료 조건', joined)
        self.assertNotIn('접속 만료', joined)

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
            self.assertIn('새 조회 필요', '\n'.join(rows))
            self.assertIn('[미검증] 외부 접속', '\n'.join(rows))

    def test_external_expiry_is_reflected_between_status_polls(self):
        snapshot = {'code': 'complete', 'ready': True, 'external_reachability': 'operator_attested',
                    'external_expires_at': 110}
        with unittest.mock.patch.object(start.time, 'time', return_value=110), \
                unittest.mock.patch.object(start, 'render_router_lines', side_effect=lambda rows, previous: rows):
            rows = start.render_router_snapshot(snapshot, None, 100, 0, None)
        self.assertIn('준비 완료', '\n'.join(rows))
        self.assertIn('[미검증] 외부 접속', '\n'.join(rows))

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


class FundingDetailTests(unittest.TestCase):
    def test_funding_details_explain_accepted_request_and_remaining_block(self):
        snapshot = dict(code='funding_pending', funding=[dict(peer='03' + 'a' * 64,
            peer_connected=True, capacity_sat=23420, confirmations_until_active=1,
            point='b' * 64 + ':1')])
        with unittest.mock.patch.object(start, 'render_router_lines', side_effect=lambda rows, previous: rows), \
             unittest.mock.patch.object(start.time, 'time', return_value=100):
            rows = start.render_router_snapshot(snapshot, None, 100, 0, None)
        text = '\n'.join(rows)
        for expected in ['개설 접수됨', '연결됨', '23,420 sat', '블록 확인 1회 남음', '재개설 불필요', 'b' * 64]:
            self.assertIn(expected, text)
        snapshot['code'] = 'query_error'
        with unittest.mock.patch.object(start, 'render_router_lines', side_effect=lambda rows, previous: rows), \
             unittest.mock.patch.object(start.time, 'time', return_value=100):
            rows = start.render_router_snapshot(snapshot, None, 100, 0, None)
        text = '\n'.join(rows)
        self.assertIn('이전 조회', text)
        self.assertIn('현재 연결 미확인', text)
        self.assertNotIn('재개설 불필요', text)


class ProgressSummaryTests(unittest.TestCase):
    def test_pending_is_not_failed_connection_or_router_ready(self):
        text = '\n'.join(start.router_progress_summary(dict(code='funding_pending',
            identity='mac-node', synced_to_chain=True, synced_to_graph=True,
            public_peers=1, pending_public=1), True, False))
        for part in ['mac-node', '동기화 [완료]', '개설 확인 대기', '실제 결제 중계 이력 [미검증]',
                     '같은 채널을 다시 개설할 필요 없습니다']:
            self.assertIn(part, text)
        self.assertNotIn('라우팅 준비 완료', text)

    def test_ready_does_not_mean_forwarded_or_external_verified(self):
        text = '\n'.join(start.router_progress_summary(dict(code='proof_required', ready=True,
            public_peers=2, synced_to_chain=True, synced_to_graph=True), True, False))
        self.assertIn('실제 결제 중계 이력 [트래픽 대기]', text)
        self.assertIn('외부망에서 P2P 접속 확인 [미검증]', text)
        self.assertIn('자동 발생 시점은 알 수 없습니다', text)

    def test_stale_complete_cannot_claim_current_completion(self):
        text = '\n'.join(start.router_progress_summary(dict(code='complete', ready=True,
            public_peers=2, forwarding_proof='verified'), False, False))
        self.assertNotIn('[완료]', text)
        self.assertIn('최신 상태를 확인하지 못했습니다', text)

    def test_observation_mode_never_automatically_opens_channel(self):
        worker = unittest.mock.Mock()
        worker.tick.side_effect = [dict(code='channel_required', message='need channel', checked_at=100),
                                   dict(code='wrong_network')]
        with unittest.mock.patch.object(start, 'StatusWorker', return_value=worker), \
             unittest.mock.patch.object(start.subprocess, 'run') as run, \
             unittest.mock.patch.object(start, 'render_router_snapshot'), \
             unittest.mock.patch.object(start.sys.stdin, 'isatty', return_value=False), \
             unittest.mock.patch.object(start.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(start.guide_router(3, ROUTER, actions_enabled=False), 'failed')
        run.assert_not_called()

    def test_compact_pending_view_fits_standard_terminal(self):
        snapshot = dict(code='funding_pending', identity='03' + 'a' * 64,
            synced_to_chain=True, synced_to_graph=True, active_public=1,
            public_peers=1, pending_public=1, inactive_public=0,
            funding=[dict(peer='03' + 'b' * 64, capacity_sat=23420,
                          peer_connected=True, confirmations_until_active=1)])
        with unittest.mock.patch.object(start, 'render_router_lines', side_effect=lambda rows, previous: rows), \
             unittest.mock.patch.object(start.sys.stdout, 'isatty', return_value=True), \
             unittest.mock.patch.object(start.shutil, 'get_terminal_size', return_value=os.terminal_size((80, 24))), \
             unittest.mock.patch.object(start.time, 'time', return_value=100):
            rows = start.render_router_snapshot(snapshot, None, 100, 0, None, compact=True)
        self.assertLessEqual(len(rows), 24)
        self.assertEqual(rows[-1], start.ROUTER_INPUT_PROMPT)
        self.assertIn('연결됨', '\n'.join(rows))
        self.assertIn('1회 남음', '\n'.join(rows))

    def test_small_window_never_cursor_updates_scrolled_rows(self):
        output = InteractiveOutput()
        rows = ['status'] * 8 + ['경과 시간 1', start.ROUTER_INPUT_PROMPT]
        with unittest.mock.patch.object(start.sys, 'stdout', output), \
             unittest.mock.patch.object(start.shutil, 'get_terminal_size', return_value=os.terminal_size((80, 5))):
            previous = start.render_router_lines(rows)
            output.seek(0)
            output.truncate(0)
            rows[-2] = '경과 시간 2'
            start.render_router_lines(rows, previous)
        self.assertEqual(output.getvalue(), '')


class LiveForwardingRowsTests(unittest.TestCase):
    def test_exact_millisat_fee_and_direction_are_visible(self):
        snapshot = dict(forwarding_history_count=1, forwarding_history_fee_msat=1005,
                        forwarding_recent=[dict(timestamp=1790489966, amount_msat=11000, fee_msat=1005,
                                                incoming_peer='Mac', outgoing_peer='External')])
        text = '\n'.join(start.router_forwarding_rows(snapshot, True))
        self.assertIn('1건', text)
        self.assertIn('1.005 sat', text)
        self.assertIn('출금 11.000 sat', text)
        self.assertIn('Mac… → 이 노드 → External…', text)
        self.assertIn('10초마다 조회', text)
        self.assertIn('이전 조회', '\n'.join(start.router_forwarding_rows(snapshot, False)))

    def test_unknown_history_is_not_zero_and_capped_is_explicit(self):
        self.assertIn('아직 조회하지 못했습니다', '\n'.join(start.router_forwarding_rows({}, True)))
        self.assertIn('일부 기록', '\n'.join(start.router_forwarding_rows(
            dict(forwarding_history_count=50000, forwarding_window_capped=True), True)))
