import pathlib
import shlex
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ops"))
from router_proof import plan, validate, current_evidence
from router_proof_run import start, reconcile, Endpoint
from router_store import read, operation_lock

HASH = "a" * 64


def info(key):
    return {"identity_pubkey": key, "testnet": True, "synced_to_chain": True}


def fixture():
    channels = [{"chan_id": str(index), "channel_point": f"point-{index}", "active": True,
                 "private": False, "remote_pubkey": peer} for index, peer in ((1, "payer"), (2, "receiver"))]
    record = plan(info("router"), info("payer"), info("receiver"), channels, "1", "2", 10, 10)
    record.update(started_at=100, payment_hash=HASH, request_id="test", state="verifying")
    payment = {"payment_hash": HASH, "status": "SUCCEEDED", "value_msat": "10000", "fee_msat": "1000",
               "htlcs": [{"status": "SUCCEEDED", "attempt_time_ns": "101000000000", "resolve_time_ns": "102000000000",
                          "route": {"hops": [{"pub_key": "router", "chan_id": "1", "amt_to_forward_msat": "10000", "fee_msat": "1000"},
                                             {"pub_key": "receiver", "chan_id": "2", "amt_to_forward_msat": "10000", "fee_msat": "0"}]}}]}
    invoice = {"state": "SETTLED", "amt_paid_msat": "10000", "r_hash": HASH}
    events = [{"chan_id_in": "1", "chan_id_out": "2", "amt_in_msat": "11000", "amt_out_msat": "10000",
               "fee_msat": "1000", "timestamp_ns": "102000000000"}]
    return channels, record, payment, invoice, events


class ProofTests(unittest.TestCase):
    def setUp(self):
        self.channels, self.record, self.payment, self.invoice, self.events = fixture()

    def validate(self):
        return validate(self.record, self.payment, self.invoice, self.events, now=105)

    def test_exact_route_and_forwarding_evidence_match_without_secrets(self):
        self.payment["payment_preimage"] = "secret"
        result = self.validate()
        self.assertEqual(result["state"], "complete")
        self.assertNotIn("secret", str(result))

    def test_old_or_ambiguous_local_events_do_not_prove_payment(self):
        self.events[0]["timestamp_ns"] = "99000000000"
        with self.assertRaises(ValueError):
            self.validate()
        self.events[0]["timestamp_ns"] = "102000000000"
        self.events *= 2
        with self.assertRaises(ValueError):
            self.validate()

    def test_direct_payment_to_router_or_wrong_channel_does_not_count(self):
        self.payment["htlcs"][0]["route"]["hops"].pop()
        with self.assertRaises(ValueError):
            self.validate()
        self.payment = fixture()[2]
        self.payment["htlcs"][0]["route"]["hops"][0]["chan_id"] = "9"
        with self.assertRaises(ValueError):
            self.validate()

    def test_wrong_amount_hash_fee_and_unsettled_receiver_fail(self):
        for key, value in (("value_msat", "9999"), ("payment_hash", "b" * 64), ("fee_msat", "10001")):
            original = self.payment[key]
            self.payment[key] = value
            with self.assertRaises(ValueError):
                self.validate()
            self.payment[key] = original
        self.invoice["state"] = "OPEN"
        with self.assertRaises(ValueError):
            self.validate()

    def test_replaced_channel_or_wallet_invalidates_current_evidence(self):
        evidence = self.validate()
        rows = [{"id": c["chan_id"], "point": c["channel_point"], "peer": c["remote_pubkey"], "private": False} for c in self.channels]
        self.assertTrue(current_evidence(evidence, "router", rows))
        self.assertFalse(current_evidence(evidence, "new-router", rows))
        rows[0]["point"] = "replacement"
        self.assertFalse(current_evidence(evidence, "router", rows))

    def test_endpoint_identity_and_public_channel_requirements(self):
        with self.assertRaises(ValueError):
            plan(info("router"), info("router"), info("receiver"), self.channels, "1", "2", 10, 10)
        self.channels[0]["private"] = True
        with self.assertRaises(ValueError):
            plan(info("router"), info("payer"), info("receiver"), self.channels, "1", "2", 10, 10)

    def test_numeric_scid_wins_over_new_lncli_hex_chan_id(self):
        self.channels[0].update(scid="1", chan_id="f" * 64, scid_str="0x0x1")
        result = plan(info("router"), info("payer"), info("receiver"), self.channels, "1", "2", 10, 10)
        self.assertEqual(result["incoming"]["id"], "1")


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = pathlib.Path(self.directory.name)
        self.channels, self.record, self.payment, self.invoice, self.events = fixture()
        self.sent = 0
        self.drop = False

    def router(self, command, *args):
        if command == "getinfo": return info("router")
        if command == "listchannels": return {"channels": self.channels}
        if command == "fwdinghistory": return {"forwarding_events": self.events}
        self.fail(command)

    def payer(self, command, *args):
        if command == "getinfo": return info("payer")
        if command == "decodepayreq": return {"destination": "receiver", "num_msat": "10000", "payment_hash": HASH}
        if command == "payinvoice":
            self.assertEqual(read(self.root, "proof-request.json")["state"], "paying")
            self.assertIn("--fee_limit=10", args)
            self.assertIn("--outgoing_chan_id=1", args)
            self.assertIn("--last_hop=router", args)
            self.sent += 1
            if self.drop: raise TimeoutError("response lost")
            return self.payment
        if command == "trackpayment": return self.payment
        self.fail(command)

    def receiver(self, command, *args):
        if command == "getinfo": return info("receiver")
        if command == "addinvoice": return {"payment_request": "private-invoice", "r_hash": HASH}
        if command == "lookupinvoice": return self.invoice
        self.fail(command)

    def approved(self):
        return plan(info("router"), info("payer"), info("receiver"), self.channels, "1", "2", 10, 10)

    def test_lost_response_reconciles_without_second_payment(self):
        self.drop = True
        with patch("router_proof_run.time.time", return_value=100):
            with self.assertRaises(TimeoutError):
                start(self.root, self.approved(), self.payer, self.receiver, self.router)
        with self.assertRaises(ValueError):
            start(self.root, self.approved(), self.payer, self.receiver, self.router)
        result = reconcile(self.root, self.payer, self.receiver, self.router)
        self.assertEqual(result["state"], "complete")
        self.assertEqual(self.sent, 1)
        self.assertNotIn("private-invoice", str(read(self.root, "forwarding-proof.json")))

    def test_external_invoice_hash_mismatch_blocks_proof(self):
        self.drop = True
        with patch("router_proof_run.time.time", return_value=100), self.assertRaises(TimeoutError):
            start(self.root, self.approved(), self.payer, self.receiver, self.router)
        self.invoice["r_hash"] = "b" * 64
        with self.assertRaises(ValueError):
            reconcile(self.root, self.payer, self.receiver, self.router)
        self.assertIsNone(read(self.root, "forwarding-proof.json"))

    def test_endpoint_rejects_ssh_option_injection(self):
        for alias in ("-oProxyCommand=bad", "host;bad", "host x", "user@host"):
            with self.assertRaises(ValueError):
                Endpoint(alias, "/home/user/.lnd")

    def test_remote_arguments_stay_literal_and_stream_uses_terminal_status(self):
        endpoint = Endpoint("payer-lab", "/home/user/lnd;$(touch bad)")
        response = Mock(returncode=0, stdout='{"status":"IN_FLIGHT"}\n{"status":"SUCCEEDED"}')
        with patch("router_proof_run.subprocess.run", return_value=response) as run:
            self.assertEqual(endpoint("trackpayment", "--json", HASH)["status"], "SUCCEEDED")
        argv = run.call_args.args[0]
        self.assertIn("StrictHostKeyChecking=yes", argv)
        self.assertEqual(shlex.split(argv[-1])[2], "--lnddir=/home/user/lnd;$(touch bad)")

    def test_concurrent_start_is_blocked_before_any_remote_rpc(self):
        external = Mock(side_effect=AssertionError("unexpected remote RPC"))
        with operation_lock(self.root), self.assertRaises(BlockingIOError):
            start(self.root, self.approved(), external, external, self.router)
        external.assert_not_called()

    def test_different_created_invoice_hash_prevents_payment(self):
        def mismatched_receiver(command, *args):
            if command == "addinvoice":
                return {"payment_request": "private-invoice", "r_hash": "b" * 64}
            return self.receiver(command, *args)
        with self.assertRaisesRegex(ValueError, "hash"):
            start(self.root, self.approved(), self.payer, mismatched_receiver, self.router)
        self.assertEqual(self.sent, 0)


if __name__ == "__main__":
    unittest.main()
