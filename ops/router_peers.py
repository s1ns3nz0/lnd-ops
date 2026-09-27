"""Operator-approved peer addresses and bounded reconnection."""
import ipaddress
import re
import subprocess
import time

from router_rpc import call, require_testnet
from router_store import operation_lock, read, write


def validate_peer(pubkey, address):
    if not re.fullmatch(r"0[23][0-9a-f]{64}", pubkey):
        raise ValueError("peer 공개키는 02 또는 03으로 시작하는 66자리 hex여야 합니다")
    if not isinstance(address, str) or any(c.isspace() for c in address):
        raise ValueError("peer 주소에는 공백을 넣을 수 없습니다")
    if address.startswith("["):
        match = re.fullmatch(r"\[([^\]]+)\]:(\d+)", address)
        if not match or ipaddress.ip_address(match[1]).version != 6:
            raise ValueError("IPv6 주소는 [주소]:포트 형식이어야 합니다")
        host, port = match[1], int(match[2])
    else:
        match = re.fullmatch(r"([a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?):(\d+)", address)
        if not match:
            raise ValueError("peer 주소는 DNS 또는 IP:포트 형식이어야 합니다")
        host, port = match[1], int(match[2])
    if not 1 <= port <= 65535 or len(host) > 253:
        raise ValueError("peer 주소 또는 포트가 잘못되었습니다")
    return pubkey, address


def config_for(root, info):
    require_testnet(info)
    config = read(root, "peers.json") or {"schema": "lnd-ops/router-peers/v1", "identity": info["identity_pubkey"], "peers": {}}
    if config.get("schema") != "lnd-ops/router-peers/v1" or config.get("identity") != info["identity_pubkey"]:
        raise ValueError("승인된 peer 목록이 현재 지갑 identity와 다릅니다")
    return config


def approve(root, pubkey, address, rpc=call):
    validate_peer(pubkey, address)
    with operation_lock(root):
        info = rpc("getinfo")
        config = config_for(root, info)
        if pubkey == info["identity_pubkey"]:
            raise ValueError("자기 노드는 peer로 등록할 수 없습니다")
        config["peers"][pubkey] = {"address": address, "approved_at": time.time(), "attempts": 0, "next_attempt_at": 0}
        write(root, "peers.json", config)


def reconnect(root, rpc=call, now=None):
    now = time.time() if now is None else now
    with operation_lock(root):
        info = rpc("getinfo")
        config = config_for(root, info)
        connected = {p["pub_key"] for p in rpc("listpeers").get("peers", [])}
        events = []
        for pubkey, entry in config["peers"].items():
            validate_peer(pubkey, entry["address"])
            if pubkey in connected:
                if entry["attempts"]:
                    events.append({"peer": pubkey, "state": "connected"})
                entry.update(attempts=0, next_attempt_at=0, state="connected", error=None)
                continue
            if entry["attempts"] >= 3:
                if entry.get("state") != "needs_review" and now >= entry["next_attempt_at"]:
                    entry.update(state="needs_review", error="세 번 연결을 요청했지만 연결 상태를 확인하지 못했습니다")
                    events.append({"peer": pubkey, "state": "needs_review"})
                continue
            if now < entry["next_attempt_at"]:
                continue
            # Persist the attempt before connecting so restart cannot reset limits.
            entry["attempts"] += 1
            entry["next_attempt_at"] = now + 10 * (2 ** (entry["attempts"] - 1))
            entry["state"] = "connecting"
            write(root, "peers.json", config)
            try:
                rpc("connect", f"{pubkey}@{entry['address']}")
                entry.update(state="requested", error=None)
            except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
                entry.update(state="needs_review" if entry["attempts"] >= 3 else "retry_wait", error=str(exc))
            events.append({"peer": pubkey, "state": entry["state"]})
            write(root, "peers.json", config)
        write(root, "peers.json", config)
        return events


def wizard(root, rpc=call):
    info = rpc("getinfo")
    require_testnet(info)
    print("  peer 운영자와 주소를 확인한 뒤 등록하세요. 승인한 주소만 자동 재연결합니다.")
    connected = rpc("listpeers").get("peers", [])
    for index, peer in enumerate(connected, 1):
        direction = "상대가 접속함; 표시 주소는 재연결 주소가 아닐 수 있음" if peer.get("inbound") else "현재 연결됨"
        print(f"  [{index}] {peer['pub_key']}\n      {peer.get('address', '?')} ({direction})")
    answer = input("  등록할 peer 번호 또는 공개키 [s=취소]: ").strip()
    if answer == "s":
        return False
    selected = connected[int(answer) - 1] if answer.isdigit() and 1 <= int(answer) <= len(connected) else None
    pubkey = selected["pub_key"] if selected else answer
    default = selected.get("address", "") if selected and not selected.get("inbound") else ""
    address = input(f"  공개 P2P 주소 [Enter={default}]: " if default else "  공개 P2P 주소 (DNS/IP:포트): ").strip() or default
    validate_peer(pubkey, address)
    print(f"  연결 및 향후 재연결 대상: {pubkey}@{address}")
    if input("  승인 [CONNECT 입력=등록·연결, 그 외=취소]: ").strip() != "CONNECT":
        return False
    approve(root, pubkey, address, rpc)
    for event in reconnect(root, rpc):
        print(f"  연결 상태: {event['state']}")
    return True
