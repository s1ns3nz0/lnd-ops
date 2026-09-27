import pathlib
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'ops'))
from router_rpc import call, GraphEdgeMissing, RPCError, WalletLocked


class RouterRPCErrorTests(unittest.TestCase):
    def rpc_failure(self, message, command='getchaninfo'):
        result = subprocess.CompletedProcess([], 1, '', message)
        with patch('router_rpc.subprocess.run', return_value=result):
            return call(command, '--chan_id=123')

    def test_pinned_missing_edge_with_kubectl_exit_trailer(self):
        with self.assertRaises(GraphEdgeMissing):
            self.rpc_failure('[lncli] rpc error: code = NotFound desc = edge not found\n'
                      'command terminated with exit code 1\n')

    def test_unrelated_errors_are_not_graph_waits(self):
        for message in (
            'Error from server (NotFound): pods "lnd-0-0" not found',
            '[lncli] rpc error: code = PermissionDenied desc = edge not found',
            '[lncli] rpc error: code = Unavailable desc = connection refused',
            '[lncli] rpc error: code = NotFound desc = edge not found in zombie index',
            '[lncli] rpc error: code = Unknown desc = graph bucket not initialized',
        ):
            with self.subTest(message=message), self.assertRaises(RPCError) as caught:
                self.rpc_failure(message)
            self.assertIs(type(caught.exception), RPCError)

    def test_classification_is_scoped_to_getchaninfo(self):
        with self.assertRaises(RPCError) as caught:
            self.rpc_failure('[lncli] rpc error: code = NotFound desc = edge not found', 'listchannels')
        self.assertIs(type(caught.exception), RPCError)

    def test_locked_wallet_retains_unlock_action(self):
        with self.assertRaises(WalletLocked):
            self.rpc_failure('[lncli] wallet is locked')


if __name__ == '__main__':
    unittest.main()
