"""Scoped testnet RPC adapter; never invokes a shell or passes wallet passwords."""
import json
import os
import pathlib
import re
import subprocess


class RPCError(RuntimeError):
    pass


class WalletLocked(RPCError):
    pass


class GraphEdgeMissing(RPCError):
    """LND answered GetChanInfo, but does not have the requested graph edge."""


def environment():
    state = pathlib.Path(os.environ.get("XDG_STATE_HOME", pathlib.Path.home() / ".local/state"))
    return os.environ | {"KUBECONFIG": os.environ.get("KUBECONFIG", str(state / "lnd-ops/kubeconfig"))}


def call(*arguments, timeout=30):
    command = ["kubectl", "-n", "lnd-testnet", "exec", "lnd-0-0", "-c", "lnd", "--",
               "lncli", "--lnddir=/data/.lnd", "--network=testnet", *arguments]
    result = subprocess.run(command, env=environment(), capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        if any(text in detail.lower() for text in ("wallet locked", "wallet is locked", "unlock the wallet", "wallet not found")):
            raise WalletLocked("기존 testnet 지갑의 잠금을 해제해야 합니다")
        # Match the pinned LND NotFound response, not Kubernetes NotFound,
        # permission failures, or other errors containing similar words.
        if arguments and arguments[0] == 'getchaninfo' and re.search(
                r'^\[lncli\] rpc error: code = NotFound desc = edge not found$', detail, re.MULTILINE):
            raise GraphEdgeMissing("채널 그래프 정보를 아직 조회할 수 없습니다")
        raise RPCError(detail or "LND 조회 실패")
    return json.loads(result.stdout)


def require_testnet(info):
    if not info.get("testnet") or not info.get("identity_pubkey"):
        raise RPCError("testnet 지갑 identity를 확인할 수 없습니다")
    if not info.get("synced_to_chain"):
        raise RPCError("testnet 체인 동기화가 필요합니다")
