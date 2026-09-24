import unittest
import io
import hashlib
import json
import pathlib
import tempfile
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from collector.payment_metrics import PAGE_SIZE, aggregate, backup_metrics, certificate_metrics, read_pages, read_wallet_state, wallet_state_metrics


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

    def test_backup_metrics_compare_record_without_exporting_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / "channel.backup"
            status = pathlib.Path(directory) / "lnd-0.status"
            source.write_bytes(b"static-channel-backup")
            plain_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            cipher_hash = "b" * 64
            status.write_text(f"9000 {plain_hash} {cipher_hash} gpg-symmetric-v1\n")
            output = backup_metrics(source, status, 10000)
        self.assertIn("lnd_ops_scb_source_present 1", output)
        self.assertIn("lnd_ops_scb_backup_recorded 1", output)
        self.assertIn("lnd_ops_scb_backup_current 1", output)
        self.assertIn("lnd_ops_scb_backup_age_seconds 1000", output)
        self.assertNotIn(plain_hash, output)
        self.assertNotIn(cipher_hash, output)

    def test_backup_metrics_fail_closed_for_stale_or_missing_record(self):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / "channel.backup"
            status = pathlib.Path(directory) / "lnd-0.status"
            source.write_bytes(b"changed")
            status.write_text(f"9000 {'a' * 64} {'b' * 64} gpg-symmetric-v1\n")
            stale = backup_metrics(source, status, 10000)
            missing = backup_metrics(source, pathlib.Path(directory) / "missing", 10000)
        self.assertIn("lnd_ops_scb_backup_current 0", stale)
        self.assertIn("lnd_ops_scb_backup_recorded 0", missing)

    def test_certificate_metrics_export_only_expiry(self):
        decoded = {"notAfter": "Sep 24 06:48:34 2027 GMT", "subject": ((('commonName', 'private-node'),),)}
        with patch("collector.payment_metrics.ssl._ssl._test_decode_cert", return_value=decoded):
            output = certificate_metrics("/private/tls.cert")
        self.assertIn("lnd_ops_tls_certificate_expiry_timestamp_seconds 1821768514", output)
        self.assertNotIn("private-node", output)


if __name__ == "__main__":
    unittest.main()
