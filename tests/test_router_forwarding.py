import pathlib
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'ops'))
from router_forwarding import observe


class ForwardingTests(unittest.TestCase):
    channels = [{'id': '1', 'peer': 'a'}, {'id': '2', 'peer': 'b'},
                {'id': '3', 'peer': 'c', 'private': True}]
    event = {'chan_id_in': '1', 'chan_id_out': '2', 'timestamp_ns': '99900000000000',
             'amt_in_msat': '1100', 'amt_out_msat': '1000', 'fee_msat': '100'}

    def test_reads_only_history_and_reports_real_forward(self):
        rpc = Mock(return_value={'forwarding_events': [self.event]})
        result = observe(rpc, self.channels, 100000)
        rpc.assert_called_once_with('fwdinghistory', '--start_time=13600',
                                    '--end_time=100000', '--max_events=50000')
        self.assertEqual(result['forwarding_observed_count'], 1)
        self.assertEqual(result['forwarding_observed_fee_msat'], 100)
        self.assertEqual(result['forwarding_observed_at'], 99900)

    def test_unrelated_private_stale_future_or_malformed_events_do_not_count(self):
        for change in ({'chan_id_in': '9'}, {'chan_id_in': '3'}, {'chan_id_out': '1'},
                       {'timestamp_ns': '1'}, {'timestamp_ns': '100001000000000'},
                       {'amt_in_msat': '999'}, {'fee_msat': '-1'},
                       {'amt_out_msat': 'bad'}, {'timestamp_ns': None}):
            with self.subTest(change=change):
                result = observe(Mock(return_value={'forwarding_events': [self.event | change]}), self.channels, 100000)
                self.assertEqual(result['forwarding_observed_count'], 0)

    def test_empty_history_and_same_peer_are_not_proof(self):
        for events, channels in (([], self.channels), ([self.event], [{'id': '1', 'peer': 'a'}, {'id': '2', 'peer': 'a'}])):
            self.assertEqual(observe(Mock(return_value={'forwarding_events': events}), channels, 100000)['forwarding_observed_count'], 0)


if __name__ == '__main__':
    unittest.main()
