import unittest
import io
import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from collector.payment_metrics import PAGE_SIZE, aggregate, read_pages, read_wallet_state, wallet_state_metrics


class PaymentMetricsTest(unittest.TestCase):
    def test_wallet_state_uses_no_macaroon_and_emits_one_active_state(self):
        def fake_urlopen(request, **_kwargs):
            self.assertEqual(request, "https://127.0.0.1:8080/v1/state")
            return io.BytesIO(b'{"state":"LOCKED"}')

        with patch("collector.payment_metrics.urlopen", side_effect=fake_urlopen):
            state = read_wallet_state("https://127.0.0.1:8080", None)
        output = wallet_state_metrics(state)
        self.assertIn('lnd_ops_wallet_state{state="LOCKED"} 1', output)
        self.assertIn('lnd_ops_wallet_state{state="SERVER_ACTIVE"} 0', output)
        self.assertEqual(output.count('} 1\n'), 1)

    def test_wallet_state_rejects_unknown_value(self):
        with patch("collector.payment_metrics.urlopen", return_value=io.BytesIO(b'{"state":"PRIVATE"}')):
            with self.assertRaisesRegex(ValueError, "unrecognized LND wallet state"):
                read_wallet_state("https://127.0.0.1:8080", None)

    def test_payment_pagination_reads_all_pages_with_readonly_macaroon(self):
        offsets = []

        def fake_urlopen(request, **_kwargs):
            query = parse_qs(urlparse(request.full_url).query)
            offsets.append(query["index_offset"][0])
            self.assertEqual(query["include_incomplete"], ["true"])
            self.assertEqual(query["paginate_forwards"], ["true"])
            self.assertEqual(request.get_header("Grpc-metadata-macaroon"), "aabb")
            if len(offsets) == 1:
                payload = {"payments": [{"payment_index": str(i)} for i in range(PAGE_SIZE)], "last_index_offset": str(PAGE_SIZE)}
            else:
                payload = {"payments": [{"payment_index": str(PAGE_SIZE + 1)}], "last_index_offset": str(PAGE_SIZE + 1)}
            return io.BytesIO(json.dumps(payload).encode())

        with patch("collector.payment_metrics.urlopen", side_effect=fake_urlopen):
            items = list(read_pages("https://127.0.0.1:8080", "/v1/payments", "payments", "last_index_offset", "aabb", None))
        self.assertEqual(offsets, ["0", str(PAGE_SIZE)])
        self.assertEqual(len(items), PAGE_SIZE + 1)

    def test_invoice_pagination_rejects_nonadvancing_offset(self):
        payload = {"invoices": [{} for _ in range(PAGE_SIZE)], "last_index_offset": "0"}
        with patch("collector.payment_metrics.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
            with self.assertRaisesRegex(ValueError, "non-advancing invoices pagination offset"):
                list(read_pages("https://127.0.0.1:8080", "/v1/invoices", "invoices", "last_index_offset", "aabb", None))

    def test_aggregate_emits_only_status_and_totals(self):
        now = 10_000
        payments = [
            {
                "payment_hash": "private-hash",
                "payment_request": "private-invoice",
                "status": "SUCCEEDED",
                "creation_time_ns": str((now - 10) * 1_000_000_000),
                "fee_sat": "2",
                "htlcs": [{"resolve_time_ns": str((now - 7) * 1_000_000_000)}],
            },
            {"status": "FAILED", "creation_time_ns": str((now - 20) * 1_000_000_000)},
            {"status": "SUCCEEDED", "creation_time_ns": str((now - 7200) * 1_000_000_000)},
        ]
        invoices = [
            {"state": "SETTLED", "settle_date": str(now - 5), "r_hash": "private-receive-hash"},
            {"state": "CANCELED", "creation_date": str(now - 5)},
        ]
        output = aggregate(payments, invoices, now)
        self.assertIn('lnd_ops_outgoing_payments_1h{status="SUCCEEDED"} 1', output)
        self.assertIn('lnd_ops_outgoing_payments_1h{status="FAILED"} 1', output)
        self.assertIn("lnd_ops_outgoing_fee_sat_1h 2", output)
        self.assertIn("lnd_ops_outgoing_latency_seconds_sum_1h 3.000000", output)
        self.assertIn('lnd_ops_received_invoices_1h{state="SETTLED"} 1', output)
        self.assertNotIn("private-", output)
        self.assertNotIn("CANCELED", output)


if __name__ == "__main__":
    unittest.main()
