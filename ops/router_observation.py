"""Issue and import operator-controlled, unsigned external P2P observations."""
import ipaddress
import re
import secrets
import time

from router_rpc import require_testnet
from router_store import operation_lock, read, write

REQUEST = "lnd-ops/router-p2p-request/v1"
OBSERVATION = "lnd-ops/router-p2p-observation/v1"
CONFIRM = "IMPORT EXTERNAL ROUTER OBSERVATION"
MAX_AGE = 600


def public_endpoint(endpoint):
    if not isinstance(endpoint, str):
        raise ValueError("공개 IP:9735 형식이 필요합니다")
    match = re.fullmatch(r"(?:\[([^\]]+)\]|([^:]+)):9735", endpoint)
    if not match:
        raise ValueError("공개 IP:9735 형식이 필요합니다")
    address = ipaddress.ip_address(match[1] or match[2])
    address = getattr(address, "ipv4_mapped", None) or address
    if not address.is_global or address.is_multicast or address.is_reserved or "%" in str(address):
        raise ValueError("외부 검사에는 숫자로 된 공개 IP가 필요합니다")
    if address.version == 4 and address in ipaddress.ip_network("192.0.0.0/24"):
        raise ValueError("검사기가 허용하지 않는 특수 목적 IP입니다")
    return endpoint


def binding(info, endpoint):
    require_testnet(info)
    identity = info["identity_pubkey"]
    if not isinstance(identity, str) or not re.fullmatch(r"0[23][0-9a-f]{64}", identity):
        raise ValueError("노드 공개키 형식이 잘못되었습니다")
    public_endpoint(endpoint)
    if f"{identity}@{endpoint}" not in info.get("uris", []):
        raise ValueError("현재 LND가 공개한 주소와 검사 주소가 다릅니다")
    return identity


def issue(root, info, endpoint, now=None):
    now = int(time.time()) if now is None else now
    identity = binding(info, endpoint)
    with operation_lock(root):
        previous = read(root, "p2p-request.json")
        if previous and previous["expires_at"] > now:
            if previous["identity"] == identity and previous["endpoint"] == endpoint:
                return previous
            raise ValueError("기존 외부 검사 요청이 만료된 뒤 새 주소로 발급하세요")
        request = {"schema": REQUEST, "nonce": secrets.token_hex(32), "identity": identity,
                   "endpoint": endpoint, "issued_at": now, "expires_at": now + MAX_AGE}
        write(root, "p2p-request.json", request)
        return request


def validate(observation, request, info, now):
    if not isinstance(observation, dict) or observation.get("schema") != OBSERVATION:
        raise ValueError("외부 검사 결과 형식이 잘못되었습니다")
    if not isinstance(request, dict) or observation.get("request") != request:
        raise ValueError("현재 발급한 요청과 결과가 다릅니다")
    identity = binding(info, request["endpoint"])
    if request.get("schema") != REQUEST or request.get("identity") != identity:
        raise ValueError("검사 요청의 지갑이 현재 지갑과 다릅니다")
    issued, expiry = request.get("issued_at"), request.get("expires_at")
    started, verified = observation.get("started_at"), observation.get("verified_at")
    if any(type(value) is not int for value in (issued, expiry, started, verified)):
        raise ValueError("검사 시각 형식이 잘못되었습니다")
    if not (0 < issued <= started <= verified <= now < expiry and expiry - issued <= MAX_AGE
            and verified - started <= 15):
        raise ValueError("검사 요청이 만료되었거나 검사 시각이 일치하지 않습니다")
    if observation.get("remote_key") != identity:
        raise ValueError("응답 노드의 공개키가 현재 지갑과 다릅니다")
    if observation.get("authenticated_handshake") is not True or observation.get("lightning_init_received") is not True:
        raise ValueError("인증된 Lightning 접속 결과가 필요합니다")
    if observation.get("network_origin") != "operator-attested-external":
        raise ValueError("별도 외부 네트워크에서 실행했다는 운영자 확인이 필요합니다")
    key = observation.get("observer_key")
    if not isinstance(key, str) or not re.fullmatch(r"0[23][0-9a-f]{64}", key) or key == identity:
        raise ValueError("검사기 임시 공개키가 잘못되었습니다")
    # A private socket address is valid behind the observer's own NAT. It
    # cannot prove physical network origin, which remains operator-attested.
    local = observation.get("local_address")
    if not isinstance(local, str) or not local or len(local) > 256 or any(ord(c) < 32 for c in local):
        raise ValueError("검사기 소켓 주소가 잘못되었습니다")
    return observation


def import_result(root, observation, info, confirmation, now=None):
    if confirmation != CONFIRM:
        raise ValueError("본인이 별도 네트워크에서 실행한 결과임을 명시적으로 확인하세요")
    now = int(time.time()) if now is None else now
    with operation_lock(root):
        request = read(root, "p2p-request.json")
        validate(observation, request, info, now)
        record = {"schema": "lnd-ops/router-p2p-receipt/v1", "observation": observation,
                  "imported_at": now, "provenance": "operator-controlled-unsigned"}
        write(root, "p2p-observation.json", record)
        # Keep the request until expiry for idempotent imports after a lost
        # response. Issuing again during this period returns the same nonce.
        return record


def current(record, info, now=None):
    """Return recent operator-attested evidence, never independent attestation."""
    now = int(time.time()) if now is None else now
    try:
        if not isinstance(record, dict) or record.get("schema") != "lnd-ops/router-p2p-receipt/v1" or record.get("provenance") != "operator-controlled-unsigned":
            return False
        observation = record["observation"]
        if not isinstance(observation, dict):
            return False
        validate(observation, observation["request"], info, now)
        return type(record["imported_at"]) is int and observation["verified_at"] <= record["imported_at"] <= now
    except (ValueError, KeyError, TypeError, RuntimeError):
        return False
