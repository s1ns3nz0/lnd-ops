import importlib.machinery
import importlib.util
import pathlib
import unittest
import unittest.mock


REPO = pathlib.Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("exercise_regtest", str(REPO / "ops/exercise-regtest"))
spec = importlib.util.spec_from_loader(loader.name, loader)
exercise = importlib.util.module_from_spec(spec)
loader.exec_module(exercise)


class RegtestPaymentTests(unittest.TestCase):
    def test_payment_requires_matching_success_and_settled_records(self):
        responses = [
            {"payment_request": "invoice", "r_hash": "hash"},
            {"payments": [{"payment_hash": "HASH", "status": "SUCCEEDED", "fee_sat": "2"}]},
            {"invoices": [{"r_hash": "hash", "state": "SETTLED"}]},
        ]
        with unittest.mock.patch.object(exercise, "lnd_json", side_effect=responses) as lnd_json, \
             unittest.mock.patch.object(exercise, "lnd") as lnd:
            result = exercise.pay_and_verify("lnd-1", "lnd-0", 5000)

        self.assertEqual(result, "hash")
        lnd.assert_called_once_with(
            "lnd-1", "pay 5000 sat regtest invoice", "payinvoice",
            "--pay_req", "invoice", "--fee_limit", "10", "--force",
        )
        self.assertEqual(lnd_json.call_args_list[0].args, (
            "lnd-0", "create 5000 sat regtest invoice", "addinvoice", "--amt", "5000",
        ))

    def test_payment_rejects_missing_outgoing_success(self):
        responses = [
            {"payment_request": "invoice", "r_hash": "hash"},
            {"payments": [{"payment_hash": "hash", "status": "FAILED"}]},
            {"invoices": [{"r_hash": "hash", "state": "SETTLED"}]},
        ]
        with unittest.mock.patch.object(exercise, "lnd_json", side_effect=responses), \
             unittest.mock.patch.object(exercise, "lnd"), \
             self.assertRaisesRegex(exercise.StepError, "outgoing payment"):
            exercise.pay_and_verify("lnd-0", "lnd-1", 10000)

    def test_payment_rejects_missing_settled_invoice(self):
        responses = [
            {"payment_request": "invoice", "r_hash": "hash"},
            {"payments": [{"payment_hash": "hash", "status": "SUCCEEDED"}]},
            {"invoices": [{"r_hash": "hash", "state": "OPEN"}]},
        ]
        with unittest.mock.patch.object(exercise, "lnd_json", side_effect=responses), \
             unittest.mock.patch.object(exercise, "lnd"), \
             self.assertRaisesRegex(exercise.StepError, "incoming invoice"):
            exercise.pay_and_verify("lnd-0", "lnd-1", 10000)

    def test_payment_rejects_fee_above_limit(self):
        responses = [
            {"payment_request": "invoice", "r_hash": "hash"},
            {"payments": [{"payment_hash": "hash", "status": "SUCCEEDED", "fee_sat": "11"}]},
            {"invoices": [{"r_hash": "hash", "state": "SETTLED"}]},
        ]
        with unittest.mock.patch.object(exercise, "lnd_json", side_effect=responses), \
             unittest.mock.patch.object(exercise, "lnd"), \
             self.assertRaisesRegex(exercise.StepError, "fee exceeded"):
            exercise.pay_and_verify("lnd-0", "lnd-1", 10000)

    def test_payment_retries_a_transient_initial_failure(self):
        responses = [
            {"payment_request": "invoice", "r_hash": "hash"},
            {"payments": [{"payment_hash": "hash", "status": "SUCCEEDED", "fee_sat": "0"}]},
            {"invoices": [{"r_hash": "hash", "state": "SETTLED"}]},
        ]
        with unittest.mock.patch.object(exercise, "lnd_json", side_effect=responses), \
             unittest.mock.patch.object(exercise, "lnd", side_effect=[exercise.StepError("transient"), "ok"]) as lnd, \
             unittest.mock.patch.object(exercise.time, "sleep") as sleep:
            exercise.pay_and_verify("lnd-0", "lnd-1", 10000)

        self.assertEqual(lnd.call_count, 2)
        sleep.assert_called_once_with(2)


if __name__ == "__main__":
    unittest.main()
