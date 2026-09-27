import copy
import importlib.util
import pathlib
import unittest


PATH = pathlib.Path(__file__).resolve().parents[1] / "ops/router_model.py"
spec = importlib.util.spec_from_file_location("router_model", PATH)
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


def channel(number, peer=None):
    return {"scid": str(number), "channel_point": f"tx{number}:0", "remote_pubkey": peer or f"peer{number}",
            "capacity": "100000", "active": True, "private": False,
            "local_balance": "70000", "remote_balance": "25000", "pending_htlcs": [],
            "local_constraints": {"chan_reserve_sat": "1000", "max_pending_amt_msat": "90000000", "max_accepted_htlcs": 10},
            "remote_constraints": {"chan_reserve_sat": "2000", "max_pending_amt_msat": "80000000", "max_accepted_htlcs": 5}}


class RouterModelTests(unittest.TestCase):
    def setUp(self):
        self.info = {"identity_pubkey": "self", "testnet": True, "synced_to_chain": True,
                     "synced_to_graph": True, "uris": ["self@host:9735"]}
        self.channels = [channel(1), channel(2)]
        self.peers = [{"pub_key": "peer1"}, {"pub_key": "peer2"}]
        self.policies = {}
        for c in self.channels:
            policy = {"fee_base_msat": "1000", "fee_rate_milli_msat": "500", "min_htlc": "1",
                      "max_htlc_msat": "90000000", "disabled": False}
            self.policies[c["scid"]] = {"own": policy, "remote": copy.deepcopy(policy)}

    def assess(self, pending=None, **kwargs):
        return model.assess(self.info, self.channels, pending or {}, self.peers, self.policies, **kwargs)

    def test_distinct_peers_with_directional_capacity_are_ready_without_payments(self):
        result = self.assess()
        self.assertTrue(result["ready"])
        self.assertEqual(len(result["routes"]), 2)

    def test_funding_identifies_peer_capacity_and_connection(self):
        result = self.assess({'pending_open_channels': [{'channel': {
            'private': False, 'remote_node_pub': 'peer1', 'capacity': '23420',
            'channel_point': 'funding:1'}, 'confirmations_until_active': 1}]})
        item = result['funding'][0]
        self.assertEqual(item['peer'], 'peer1')
        self.assertEqual(item['capacity_sat'], 23420)
        self.assertTrue(item['peer_connected'])
        self.peers = []
        result = self.assess({'pending_open_channels': [{'channel': {
            'private': False, 'remote_node_pub': 'peer1'}}]})
        self.assertFalse(result['funding'][0]['peer_connected'])

    def test_disconnected_active_flag_cannot_claim_ready(self):
        self.peers.pop()
        result = self.assess()
        self.assertFalse(result['ready'])
        self.assertEqual(result['code'], 'peer_disconnected')
        self.assertEqual(result['active_public'], 1)

    def test_connection_is_independent_of_channel_activation(self):
        self.channels[0]['active'] = False
        result = self.assess()
        self.assertTrue(result['channels'][0]['peer_connected'])
        self.assertFalse(result['channels'][0]['active'])
        self.peers = []
        result = self.assess()
        self.assertFalse(result['channels'][1]['peer_connected'])
        self.assertTrue(result['channels'][1]['active'])

    def test_one_channel_requires_action_not_indefinite_wait(self):
        self.channels.pop()
        self.assertEqual(self.assess()["code"], "channel_required")
        result = self.assess({"pending_open_channels": [{"channel": {"private": False}}]})
        self.assertEqual(result["code"], "funding_pending")

    def test_pending_progress_does_not_invent_zero_for_missing_fields(self):
        self.channels.pop()
        result = self.assess({'pending_open_channels': [{'channel': {'private': False}}]})
        self.assertIsNone(result['funding'][0]['confirmations_until_active'])
        self.assertIn('미제공', result['funding_progress'])
        self.assertFalse(result['funding_attention'])

    def test_pending_blocks_decrease_but_zero_does_not_prove_router_ready(self):
        self.channels.pop()
        for remaining in (3, 2, 0):
            result = self.assess({'pending_open_channels': [{'channel': {'private': False},
                                  'confirmations_until_active': remaining, 'funding_expiry_blocks': 200}]})
            self.assertFalse(result['ready'])
            self.assertEqual(result['code'], 'funding_pending')
            self.assertEqual(result['funding'][0]['confirmations_until_active'], remaining)
        self.assertIn('활성 전환 확인', result['funding_progress'])

    def test_expiry_boundary_requires_review_without_claiming_channel_failed(self):
        self.channels.pop()
        for expiry in (0, -1):
            result = self.assess({'pending_open_channels': [{'channel': {'private': False},
                                  'confirmations_until_active': 3, 'funding_expiry_blocks': expiry}]})
            self.assertEqual(result['code'], 'funding_review')
            self.assertTrue(result['funding_attention'])
            self.assertFalse(result['ready'])

    def test_multiple_pending_progress_keeps_unknown_and_private_separate(self):
        self.channels.pop()
        result = self.assess({'pending_open_channels': [
            {'channel': {'private': False}, 'confirmations_until_active': '3', 'funding_expiry_blocks': '200'},
            {'channel': {'private': False}, 'confirmations_until_active': 1, 'funding_expiry_blocks': 100},
            {'channel': {'private': False}, 'confirmations_until_active': True, 'funding_expiry_blocks': 'bad'},
            {'channel': {'private': True}, 'confirmations_until_active': 99, 'funding_expiry_blocks': -99},
        ]})
        self.assertEqual(result['pending_public'], 3)
        self.assertIn('1~3블록', result['funding_progress'])
        self.assertIn('일부 미제공', result['funding_progress'])
        self.assertFalse(result['funding_attention'])

    def test_two_channels_to_same_peer_do_not_satisfy_two_peers(self):
        self.channels[1]["remote_pubkey"] = "peer1"
        self.assertEqual(self.assess()["code"], "channel_required")

    def test_missing_peer_reconnects_instead_of_opening_another_channel(self):
        self.channels[1]["active"] = False
        self.peers.pop()
        self.assertEqual(self.assess()["code"], "peer_disconnected")

    def test_private_pending_does_not_hide_need_for_public_channel(self):
        self.channels.pop()
        self.assertEqual(self.assess({"pending_open_channels": [{"channel": {"private": True}}]})["code"], "channel_required")

    def test_normal_balance_shift_does_not_invalidate_fee_policy(self):
        c = self.channels[0]
        before = model.policy_maximum(c)
        c["local_balance"] = "55000"
        c["remote_balance"] = "40000"
        self.assertEqual(model.policy_maximum(c), before)
        self.assertTrue(model.policy_matches(self.policies["1"]["own"], c))
        self.assertTrue(self.assess()["ready"])

    def test_outbound_only_channels_are_not_routing_ready(self):
        for c in self.channels:
            c["remote_balance"] = "2000"
        self.assertEqual(self.assess()["code"], "liquidity_required")
        self.assertEqual(self.assess()['route_blockers'], ['inbound_liquidity'])

    def test_missing_own_graph_policy_waits_instead_of_prompting_mutation(self):
        self.policies['1']['own'] = None
        self.assertEqual(self.assess()['code'], 'graph_pending')

    def test_missing_remote_graph_policy_is_not_called_insufficient_funds(self):
        for pair in self.policies.values():
            pair['remote'] = None
        result = self.assess()
        self.assertEqual(result['code'], 'graph_pending')
        self.assertEqual(result['route_blockers'], ['remote_policy_unknown'])

    def test_one_verified_direction_is_enough_when_other_remote_policy_is_missing(self):
        self.policies['1']['remote'] = None
        result = self.assess()
        self.assertTrue(result['ready'])
        self.assertEqual(len(result['routes']), 1)

    def test_fee_budget_and_peer_policy_are_distinct_from_liquidity(self):
        result = self.assess(fee_limit_sat=0)
        self.assertEqual(result['route_blockers'], ['fee_limit'])
        for pair in self.policies.values():
            pair['remote']['disabled'] = True
        self.assertEqual(self.assess()['route_blockers'], ['inbound_policy'])

    def test_reserves_and_remaining_inflight_limits_without_double_subtraction(self):
        c = self.channels[0]
        c["local_balance"] = "1100"
        c["pending_htlcs"] = [{"incoming": False, "amount": "60"}]
        self.assertEqual(model.directional_capacity(c), 100000)
        c["local_constraints"]["max_pending_amt_msat"] = 90000
        self.assertEqual(model.directional_capacity(c), 30000)
        c["local_constraints"]["max_accepted_htlcs"] = 1
        self.assertEqual(model.directional_capacity(c), 0)
        # Outgoing slots do not suppress the incoming direction.
        self.assertEqual(model.directional_capacity(c, True), 23000000)

    def test_remote_disabled_policy_blocks_inbound_route(self):
        for pair in self.policies.values():
            pair["remote"]["disabled"] = True
        self.assertEqual(self.assess()["code"], "liquidity_required")

    def test_amount_and_fee_budget_are_enforced(self):
        self.assertEqual(self.assess(test_sat=90000)["code"], "liquidity_required")
        self.assertEqual(self.assess(fee_limit_sat=0)["code"], "liquidity_required")
        with self.assertRaises(ValueError):
            self.assess(test_sat=0)

    def test_mainnet_is_refused(self):
        self.info["testnet"] = False
        self.assertEqual(self.assess()["code"], "wrong_network")


if __name__ == "__main__":
    unittest.main()
