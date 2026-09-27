"""Wallet-bound target forwarding policy, independent of live channel balances."""
from router_model import DEFAULT_POLICY
from router_store import read


def validate(policy):
    limits = {"base_msat": (0, 1000000), "rate_ppm": (0, 1000000), "min_htlc_msat": (1, 100000000)}
    if set(policy) != set(limits):
        raise ValueError("routing 정책 필드가 잘못되었습니다")
    for key, (minimum, maximum) in limits.items():
        value = policy[key]
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"routing 정책 {key} 값이 허용 범위를 벗어났습니다")
    return policy


def target(root, identity):
    record = read(root, "policy.json")
    if not record:
        return DEFAULT_POLICY.copy()
    if record.get("schema") != "lnd-ops/router-policy/v1" or record.get("identity") != identity:
        raise ValueError("저장된 routing 정책의 지갑 identity가 다릅니다. 현재 지갑 정책을 다시 승인하세요")
    return validate(record["target"])
