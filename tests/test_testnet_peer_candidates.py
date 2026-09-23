import importlib.machinery
import importlib.util
import json
import pathlib
import subprocess
import unittest
import unittest.mock


REPO = pathlib.Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("testnet_peer_candidates", str(REPO / "ops/testnet-peer-candidates"))
spec = importlib.util.spec_from_loader(loader.name, loader)
candidates = importlib.util.module_from_spec(spec)
loader.exec_module(candidates)


class TestnetPeerCandidateTests(unittest.TestCase):
    def test_lists_only_announced_clearnet_candidates_by_degree(self):
        key_a, key_b = "02" + "a" * 64, "03" + "b" * 64
        graph = {
            "nodes": [
                {"pub_key": key_a, "alias": "A", "addresses": [{"addr": "198.51.100.1:9735"}]},
                {"pub_key": key_b, "alias": "B", "addresses": [{"addr": "hidden.onion:9735"}]},
            ],
            "edges": [{"node1_pub": key_a, "node2_pub": key_b}],
        }
        completed = subprocess.CompletedProcess([], 0, stdout=json.dumps(graph), stderr="")
        with unittest.mock.patch.object(candidates.subprocess, "run", return_value=completed), unittest.mock.patch("builtins.print") as output:
            self.assertEqual(candidates.main([]), 0)
        rendered = "\n".join(" ".join(map(str, call.args)) for call in output.call_args_list)
        self.assertIn(f"{key_a}@198.51.100.1:9735", rendered)
        self.assertNotIn(key_b + "@", rendered)

    def test_empty_graph_is_manual_gate(self):
        completed = subprocess.CompletedProcess([], 0, stdout='{"nodes": [], "edges": []}', stderr="")
        with unittest.mock.patch.object(candidates.subprocess, "run", return_value=completed):
            self.assertEqual(candidates.main([]), 10)


if __name__ == "__main__":
    unittest.main()
