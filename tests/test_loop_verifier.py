import contextlib
import io
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ops'))


class VerifierTests(unittest.TestCase):
    def verify(self, swaps, args=(), available=True):
        api = Mock()
        api.command.return_value = {'status': {'availableReplicas': 1}} if available else None
        api.loop.return_value = {'swaps': swaps}
        main = runpy.run_path(str(ROOT / 'ops/verify-loop'))['main']
        with patch.dict(main.__globals__, API=Mock(return_value=api)), patch.object(sys, 'argv', ['verify-loop', *args]), contextlib.redirect_stdout(io.StringIO()) as output:
            result = main()
        return result, output.getvalue(), api

    def test_ready_or_invoice_settled_is_not_phase_complete(self):
        for state in ('INITIATED', 'HTLC_PUBLISHED', 'INVOICE_SETTLED', 'FAILED'):
            result, _, _ = self.verify([{'state': state, 'amt': '10000', 'type': 'LOOP_OUT'}])
            self.assertEqual(result, 10)
        self.assertEqual(self.verify([])[0], 10)
        self.assertEqual(self.verify([], ['--ready'])[0], 0)

    def test_real_success_completes_phase_without_mutations(self):
        result, output, api = self.verify([{'state': 'SUCCESS', 'amt': '10000', 'type': 'LOOP_IN'}])
        self.assertEqual(result, 0)
        self.assertIn('실제 swap 성공', output)
        self.assertEqual(api.loop.call_args.args, ('/v1/loop/swaps',))
        api.save.assert_not_called()

    def test_missing_deployment_guides_credential_menu(self):
        result, output, _ = self.verify([], available=False)
        self.assertEqual(result, 10)
        self.assertIn('enable Loop', output)


if __name__ == '__main__': unittest.main()
