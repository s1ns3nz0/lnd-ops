"""Failure diagnosis must remain read-only and distinguish missing evidence."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ops'))
from loop_api import LoopError
from loop_ui import show_failed_out


class FailureDisplayTests(unittest.TestCase):
    def display(self, status='FAILED', reason='FAILURE_REASON_NO_ROUTE', minimum='250000', error=False):
        ops = Mock()
        ops.api.lnd.return_value = {'payments': [{'payment_hash': 'swap', 'status': status, 'failure_reason': reason}]}
        ops.api.loop.return_value = {'min_swap_amount': minimum, 'max_swap_amount': '120000000'}
        if error:
            ops.api.lnd.side_effect = LoopError('private transport details')
            ops.api.loop.side_effect = LoopError('private transport details')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            show_failed_out(ops, {'swap_id': 'swap', 'amount': 250000})
        ops.api.lnd.assert_called_once_with('listpayments', '--include_incomplete')
        ops.api.loop.assert_called_once_with('/v1/loop/out/terms')
        ops.submit.assert_not_called()
        return output.getvalue()

    def test_no_route_at_server_minimum_does_not_recommend_smaller_swap(self):
        text = self.display()
        self.assertIn('FAILURE_REASON_NO_ROUTE', text)
        self.assertIn('작은 금액으로 재시도할 수 없습니다', text)
        self.assertNotIn('더 작은 금액을 검토', text)

    def test_smaller_amount_is_conditional_and_requires_approval(self):
        text = self.display(minimum='10000')
        self.assertIn('더 작은 금액을 검토', text)
        self.assertIn('수동 승인', text)

    def test_pending_status_is_not_treated_as_final_failure(self):
        text = self.display(status='IN_FLIGHT', minimum='10000')
        self.assertIn('결제 종료 미확인', text)
        self.assertNotIn('더 작은 금액을 검토', text)
        self.assertIn('재시도를 검토하지 마세요', text)

    def test_timeout_is_distinct_from_no_route(self):
        text = self.display(reason='FAILURE_REASON_TIMEOUT')
        self.assertIn('결제 시도 시간이 만료', text)

    def test_diagnostic_failure_is_explicit_and_sanitized(self):
        text = self.display(error=True)
        self.assertIn('실패 상세 조회 실패', text)
        self.assertIn('가능 여부는 미확인', text)
        self.assertNotIn('private transport', text)


if __name__ == '__main__':
    unittest.main()
