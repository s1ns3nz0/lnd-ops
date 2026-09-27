#!/usr/bin/env python3
"""Opt-in pinned-LND regtest funding integration; no host ports or real wallets.

Run: python3 tests/integration_router_funding.py
Creates a uniquely named internal Docker network and disposable containers,
then removes only those exact IDs. The RPC adapter asserts regtest and adapts
the testnet guard flag solely for this test. This is not testnet evidence.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import time
import uuid
from decimal import Decimal
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ops"))
from router_channels import preview, reconcile, submit
from router_model import funding_progress
from router_store import read
import router_rpc as rpc_adapter
from router_proof_run import preview as proof_preview, start as proof_start, reconcile as proof_reconcile

REPO = pathlib.Path(__file__).resolve().parents[1]
LOCK = json.loads((REPO / "ops/images.lock.json").read_text())
LND = "lightninglabs/lnd@" + LOCK["lnd"]["digest"]
BITCOIN = "bitcoin/bitcoin@" + LOCK["bitcoin-core"]["digest"]


def command(*args, timeout=60):
    result = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def wait_for(label, probe, timeout=120):
    deadline = time.monotonic() + timeout
    last_error = "not ready"
    while time.monotonic() < deadline:
        try:
            result = probe()
            if result:
                return result
        except (RuntimeError, KeyError, ValueError) as exc:
            last_error = str(exc)
        time.sleep(.5)
    raise RuntimeError(f"{label} timeout: {last_error}")


def sat(value):
    return int(Decimal(str(value)) * 100000000)


def main():
    network_name = "lndops-router-test-" + uuid.uuid4().hex[:12]
    network = command("docker", "network", "create", "--internal", "--label", "lndops.test=router-funding", network_name)
    containers = []

    def launch(alias, image, *args):
        container = command("docker", "run", "-d", "--network", network, "--network-alias", alias,
                            "--label", "lndops.test=router-funding", image, *args)
        containers.append(container)
        return container

    try:
        print("Starting isolated pinned Bitcoin/LND regtest", flush=True)
        bitcoin = launch("bitcoin", BITCOIN, "bitcoind", "-regtest", "-server", "-txindex=1",
                         "-rpcuser=router-test", "-rpcpassword=disposable-regtest-only", "-rpcbind=0.0.0.0",
                         "-rpcallowip=0.0.0.0/0", "-zmqpubrawblock=tcp://0.0.0.0:28332",
                         "-zmqpubrawtx=tcp://0.0.0.0:28333", "-fallbackfee=0.00001")

        def btc(*args):
            return json.loads(command("docker", "exec", bitcoin, "bitcoin-cli", "-regtest", "-rpcuser=router-test",
                                      "-rpcpassword=disposable-regtest-only", *args))

        wait_for("bitcoin", lambda: btc("getblockchaininfo"))
        btc("createwallet", "miner")
        # bitcoin-cli prints a raw address rather than a JSON string.
        mine_address = command("docker", "exec", bitcoin, "bitcoin-cli", "-regtest", "-rpcuser=router-test",
                               "-rpcpassword=disposable-regtest-only", "getnewaddress")
        btc("generatetoaddress", "101", mine_address)
        nodes = []
        for alias in ("alice", "bob", "carol"):
            nodes.append(launch(alias, LND, "--lnddir=/tmp/router-test", "--noseedbackup", "--bitcoin.regtest",
                                "--bitcoin.node=bitcoind", "--bitcoind.rpchost=bitcoin:18443",
                                "--bitcoind.rpcuser=router-test", "--bitcoind.rpcpass=disposable-regtest-only",
                                "--bitcoind.zmqpubrawblock=tcp://bitcoin:28332", "--bitcoind.zmqpubrawtx=tcp://bitcoin:28333",
                                "--listen=0.0.0.0:9735", "--rpclisten=127.0.0.1:10009", "--restlisten=127.0.0.1:8080"))

        def lnd(index, *args):
            return json.loads(command("docker", "exec", nodes[index], "lncli", "--lnddir=/tmp/router-test",
                                      "--network=regtest", *args))

        for index in range(3):
            wait_for(f"LND {index}", lambda index=index: lnd(index, "getinfo").get("synced_to_chain"))
        identity = lnd(0, "getinfo")["identity_pubkey"]
        peer = lnd(1, "getinfo")["identity_pubkey"]
        address = lnd(0, "newaddress", "p2wkh")["address"]
        command("docker", "exec", bitcoin, "bitcoin-cli", "-regtest", "-rpcuser=router-test",
                "-rpcpassword=disposable-regtest-only", "sendtoaddress", address, "0.005")
        btc("generatetoaddress", "6", mine_address)
        wait_for("funded wallet", lambda: int(lnd(0, "walletbalance")["confirmed_balance"]) >= 500000)
        lnd(0, "connect", peer + "@bob:9735")
        print("Opening channel with approved UTXOs; discarding RPC response deliberately", flush=True)
        submitted = []

        def rpc(*args):
            response = lnd(0, *args)
            if args[0] == "getinfo":
                assert response["chains"][0]["network"] == "regtest"
                response["testnet"] = True  # Test-only network guard adaptation.
            if args[0] == "openchannel":
                submitted.append(response)
                raise TimeoutError("test transport dropped the response")
            return response

        with tempfile.TemporaryDirectory(prefix="lndops-router-funding-") as directory:
            root = pathlib.Path(directory)
            plan = preview(peer, 100000, 1, 3000, 200000, rpc)
            try:
                submit(root, plan, rpc)
                raise AssertionError("expected dropped response")
            except TimeoutError:
                pass
            assert read(root, "open-request.json")["state"] == "uncertain"
            try:
                submit(root, plan, rpc)
                raise AssertionError("duplicate open was allowed")
            except ValueError:
                pass
            assert len(submitted) == 1
            txid = submitted[0]["funding_txid"]
            pending_recovered = reconcile(root, rpc)
            assert pending_recovered['state'] == 'broadcast'
            assert pending_recovered['channel_point'].startswith(txid + ':')
            assert len(submitted) == 1
            progress = funding_progress(rpc('pendingchannels')['pending_open_channels'])
            assert any(row['confirmations_until_active'] is not None and row['confirmations_until_active'] > 0
                       for row in progress['funding'])
            assert not progress['funding_attention']
            transaction = btc("getrawtransaction", txid, "true")
            inputs = [f"{item['txid']}:{item['vout']}" for item in transaction["vin"]]
            assert set(inputs) <= set(plan["utxos"])
            total_input = sum(sat(btc("getrawtransaction", item["txid"], "true")["vout"][item["vout"]]["value"])
                              for item in transaction["vin"])
            actual_fee = total_input - sum(sat(output["value"]) for output in transaction["vout"])
            assert 0 < actual_fee <= plan["fee_upper_bound_sat"] <= plan["fee_cap_sat"]
            btc("generatetoaddress", "6", mine_address)
            wait_for("active channel", lambda: any(c["active"] for c in lnd(0, "listchannels")["channels"]))
            missing_edge = subprocess.run(
                ['docker', 'exec', nodes[0], 'lncli', '--lnddir=/tmp/router-test',
                 '--network=regtest', 'getchaninfo', '--chan_id=1'],
                capture_output=True, text=True, timeout=30)
            assert missing_edge.returncode != 0
            with patch('router_rpc.subprocess.run', return_value=missing_edge):
                try:
                    rpc_adapter.call('getchaninfo', '--chan_id=1')
                    raise AssertionError('missing graph edge was accepted')
                except rpc_adapter.GraphEdgeMissing:
                    pass
            print('Pinned LND missing graph edge classified without hiding RPC failures', flush=True)
            recovered = reconcile(root, rpc)
            assert recovered["state"] == "active" and recovered["channel_point"].startswith(txid + ":")
            # A spent approved input must fail, never fall back to remaining change.
            try:
                lnd(0, "openchannel", "--node_key=" + peer, "--local_amt=100000", "--sat_per_vbyte=1", "--utxo=" + inputs[0])
                raise AssertionError("spent UTXO silently replaced")
            except RuntimeError as exc:
                assert "spent" in str(exc).lower() or "not found" in str(exc).lower() or "unspent" in str(exc).lower(), str(exc)
            print("Restarting test LND and checking journal/channel identity", flush=True)
            command("docker", "restart", nodes[0])
            wait_for("restart", lambda: lnd(0, "getinfo").get("synced_to_chain"))
            assert lnd(0, "getinfo")["identity_pubkey"] == identity
            assert any(c["channel_point"] == recovered["channel_point"] for c in lnd(0, "listchannels")["channels"])
            print("Preparing isolated payer -> Router -> receiver path", flush=True)
            receiver_key = lnd(2, "getinfo")["identity_pubkey"]
            lnd(0, "connect", receiver_key + "@carol:9735")
            lnd(0, "openchannel", "--node_key=" + receiver_key, "--local_amt=100000", "--sat_per_vbyte=1")
            btc("generatetoaddress", "6", mine_address)
            wait_for("two active channels", lambda: sum(c["active"] for c in lnd(0, "listchannels")["channels"]) == 2)
            wait_for("payer graph", lambda: len(lnd(1, "describegraph")["edges"]) >= 2)
            funding_invoice = lnd(1, "addinvoice", "--amt=20000")
            transfer = lnd(0, "payinvoice", "--force", "--json", "--fee_limit=10", funding_invoice["payment_request"])
            assert transfer["status"] == "SUCCEEDED", "regtest payer liquidity setup failed"
            submitted_payments = []

            def proof_rpc(index):
                def invoke(*args):
                    response = lnd(index, *args)
                    if args[0] == "getinfo":
                        assert response["chains"][0]["network"] == "regtest"
                        response["testnet"] = True
                    if index == 1 and args[0] == "payinvoice":
                        submitted_payments.append(response["payment_hash"])
                        raise TimeoutError("test dropped the successful forwarding response")
                    return response
                return invoke

            router_rpc, payer_rpc, receiver_rpc = (proof_rpc(index) for index in range(3))
            approved_proof = proof_preview(payer_rpc, receiver_rpc, 10, 10, router_rpc)
            try:
                proof_start(root, approved_proof, payer_rpc, receiver_rpc, router_rpc)
                raise AssertionError("expected dropped payment response")
            except TimeoutError:
                pass
            try:
                proof_start(root, approved_proof, payer_rpc, receiver_rpc, router_rpc)
                raise AssertionError("duplicate proof payment was allowed")
            except ValueError:
                pass
            def collect_proof():
                # wait_for retains the last validation error for diagnostics.
                return proof_reconcile(root, payer_rpc, receiver_rpc, router_rpc)
            evidence = wait_for("forwarding evidence", collect_proof)
            assert evidence["state"] == "complete" and len(submitted_payments) == 1
            assert evidence["payment_hash"] == submitted_payments[0]
            print(json.dumps({"network": "regtest", "lnd_image": LND, "bitcoin_image": BITCOIN,
                              "actual_fee_sat": actual_fee, "approved_fee_cap_sat": plan["fee_cap_sat"],
                              "exact_input_allowlist": True, "lost_response_recovered": True,
                              "spent_input_refused": True, "restart_identity_preserved": True,
                              "independent_payer_router_receiver": True, "forwarding_proof_reconciled": True}), flush=True)
    finally:
        for container in reversed(containers):
            subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=30)
        subprocess.run(["docker", "network", "rm", network], capture_output=True, timeout=30)


if __name__ == "__main__":
    main()
