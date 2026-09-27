"""Pure, shared testnet Router state and policy calculations.

Balances are conservative local estimates, not a guarantee of an external route.
No network calls, wallet changes or persistent state are performed here.
"""
import re

DEFAULT_POLICY = {"base_msat": 1000, "rate_ppm": 500, "min_htlc_msat": 1}


def channel_id(channel):
    # Current lncli listchannels uses scid for the numeric short ID and
    # chan_id for a 32-byte hex identifier. Older output used numeric chan_id.
    for key in ("scid", "channel_id", "chan_id"):
        value = str(channel.get(key, ""))
        if value.isdecimal() and 0 < int(value) <= 0xffffffffffffffff:
            return str(int(value))
    return ""


def policy_maximum(channel):
    """Stable ceiling bounded by capacity and constraints our outgoing updates obey."""
    capacity = max(0, int(channel.get("capacity", 0))) * 1000
    local = channel.get("local_constraints", {})
    limit = int(local.get("max_pending_amt_msat", capacity))
    return max(0, min(capacity, limit))


def policy_matches(policy, channel, target=None):
    target = DEFAULT_POLICY if target is None else target
    if not policy or policy.get("disabled", False):
        return False
    return (
        int(policy.get("fee_base_msat", -1)) == target["base_msat"]
        and int(policy.get("fee_rate_milli_msat", -1)) == target["rate_ppm"]
        and int(policy.get("min_htlc", policy.get("min_htlc_msat", -1))) == target["min_htlc_msat"]
        and int(policy.get("max_htlc_msat", 0)) == policy_maximum(channel)
    )


def directional_capacity(channel, incoming=False):
    """Bound estimated msat by balance, reserve, HTLC slots and in-flight limits.

    LND v0.21.3 validateCommitmentSanity validates local outgoing updates against
    LocalChanCfg, remote incoming updates against RemoteChanCfg. ListChannels
    commitment balances already exclude HTLC outputs; only the remaining
    in-flight allowance subtracts them. This is not LND's exact live bandwidth.
    """
    constraints = channel.get("remote_constraints" if incoming else "local_constraints", {})
    reserve_name = "remote_chan_reserve_sat" if incoming else "local_chan_reserve_sat"
    reserve = int(constraints.get("chan_reserve_sat", channel.get(reserve_name, 0)))
    balance = int(channel.get("remote_balance" if incoming else "local_balance", 0))
    pending = [htlc for htlc in channel.get("pending_htlcs", []) if bool(htlc.get("incoming")) == incoming]
    pending_msat = sum(int(htlc.get("amount", 0)) * 1000 for htlc in pending)
    if len(pending) >= int(constraints.get("max_accepted_htlcs", 483)):
        return 0
    # Keep an additional commitment-fee cushion for the funding side.
    fee_cushion = int(channel.get("commit_fee", 0)) if bool(channel.get("initiator")) != incoming else 0
    available = max(0, (balance - reserve - fee_cushion) * 1000)
    limit = int(constraints.get("max_pending_amt_msat", int(channel.get("capacity", 0)) * 1000))
    return max(0, min(available, limit - pending_msat))


def policy_allows(policy, amount_msat):
    return bool(policy) and not policy.get("disabled", False) and (
        int(policy.get("min_htlc", policy.get("min_htlc_msat", 0))) <= amount_msat
        <= int(policy.get("max_htlc_msat", 0))
    )


def funding_progress(pending):
    """Keep absent fields unknown; zero confirmations is not gossip proof."""
    def number(value, signed=False):
        if type(value) is int:
            parsed = value
        elif isinstance(value, str) and re.fullmatch(r'-?\d+', value):
            parsed = int(value)
        else:
            return None
        lower, upper = (-2**31, 2**31 - 1) if signed else (0, 2**32 - 1)
        return parsed if lower <= parsed <= upper else None

    rows = [{'point': item.get('channel', {}).get('channel_point'),
             'confirmations_until_active': number(item.get('confirmations_until_active')),
             'funding_expiry_blocks': number(item.get('funding_expiry_blocks'), signed=True)} for item in pending]
    known = [row['confirmations_until_active'] for row in rows if row['confirmations_until_active'] is not None]
    expiry = [row['funding_expiry_blocks'] for row in rows if row['funding_expiry_blocks'] is not None]
    activation = '대기 채널 없음' if not rows else '남은 블록 수 미제공'
    if known:
        low, high = min(known), max(known)
        activation = '0블록 · 활성 전환 확인' if high == 0 else f"{str(low) if low == high else str(low) + '~' + str(high)}블록 남음"
        if len(known) < len(rows):
            activation += ' · 일부 미제공'
    risk = bool(expiry and min(expiry) <= 0)
    expiry_message = '대기 채널 없음' if not rows else '만료 블록 수 미제공'
    if expiry:
        expiry_message = f"{min(expiry)}블록 · 상대 확인 필요" if risk else f"{min(expiry)}블록 남음 (최소)"
        if len(expiry) < len(rows):
            expiry_message += ' · 일부 미제공'
    return {'funding': rows, 'funding_progress': activation, 'funding_expiry': expiry_message,
            'funding_attention': risk}


def assess(info, channels, pending, peers, policies, *, test_sat=10, fee_limit_sat=10, target_policy=None):
    if test_sat <= 0 or fee_limit_sat < 0:
        raise ValueError("시험 금액은 양수, 수수료 상한은 0 이상이어야 합니다")
    public = [channel for channel in channels if not channel.get("private")]
    active = [channel for channel in public if channel.get("active")]
    pending_public = [item for item in pending.get("pending_open_channels", [])
                      if not item.get("channel", {}).get("private", False)]
    rows = [{"id": channel_id(channel), "point": channel.get("channel_point"),
             "peer": channel.get("remote_pubkey"), "active": bool(channel.get("active")),
             "private": bool(channel.get("private")),
             "outbound_msat": directional_capacity(channel),
             "inbound_msat": directional_capacity(channel, True)} for channel in channels]
    result = {"schema": "lnd-ops/router-status/v1", "identity": info.get("identity_pubkey"),
              "code": "ready", "message": "라우팅 준비 완료 / 실경유 미검증", "ready": False,
              "synced_to_chain": bool(info.get("synced_to_chain")),
              "synced_to_graph": bool(info.get("synced_to_graph")),
              "active_public": len(active), "public_peers": len({c.get('remote_pubkey') for c in active}),
              "inactive_public": len(public) - len(active), "private": len(channels) - len(public),
              "pending_public": len(pending_public), "pending": pending_public,
              "channels": rows, "peers": len(peers), "test_sat": test_sat, "fee_limit_sat": fee_limit_sat}
    result.update(funding_progress(pending_public))

    def waiting(code, message):
        return result | {"code": code, "message": message}

    if not info.get("testnet"):
        return waiting("wrong_network", "testnet 노드만 지원합니다")
    if not info.get("synced_to_chain") or not info.get("synced_to_graph"):
        return waiting("syncing", "testnet 체인·그래프 동기화 중")
    if not peers:
        return waiting("peer_disconnected", "승인된 peer 재연결이 필요합니다")
    if not info.get("uris"):
        return waiting("exposure_required", "공개 P2P 주소를 설정해야 합니다")
    if result["public_peers"] < 2:
        if pending_public:
            if result['funding_attention']:
                return waiting('funding_review', 'funding 만료 조건 확인 필요 · 상대 노드와 상태 확인')
            return waiting("funding_pending", "공개 채널 funding 확인 대기 중")
        connected = {p.get("pub_key") for p in peers}
        if any(not c.get("active") and c.get("remote_pubkey") not in connected for c in public):
            return waiting("peer_disconnected", "기존 공개 채널의 peer 재연결이 필요합니다")
        if len({c.get("remote_pubkey") for c in public}) >= 2:
            return waiting("channel_inactive", "기존 공개 채널의 활성화를 확인 중입니다")
        return waiting("channel_required", "다른 peer에 공개 채널을 개설해야 합니다")
    own_policies = {key: pair.get("own") for key, pair in policies.items()}
    if any(not own_policies.get(channel_id(c)) for c in active):
        return waiting('graph_pending', '새 공개 채널의 정책 정보를 기다립니다')
    if any(not policy_matches(own_policies.get(channel_id(c)), c, target_policy) for c in active):
        return waiting("policy_required", "공개 채널 routing 정책 적용이 필요합니다")
    outgoing_msat = test_sat * 1000
    routes = []
    blockers = set()
    for outgoing in active:
        own = own_policies[channel_id(outgoing)]
        fee_msat = int(own["fee_base_msat"]) + (outgoing_msat * int(own["fee_rate_milli_msat"]) + 999999) // 1000000
        incoming_msat = outgoing_msat + fee_msat
        if fee_msat > fee_limit_sat * 1000:
            blockers.add('fee_limit')
            continue
        if directional_capacity(outgoing) < outgoing_msat:
            blockers.add('outbound_liquidity')
            continue
        if not policy_allows(own, outgoing_msat):
            blockers.add('outbound_policy')
            continue
        for incoming in active:
            if incoming.get("remote_pubkey") == outgoing.get("remote_pubkey"):
                continue
            remote = policies.get(channel_id(incoming), {}).get("remote")
            if not remote:
                blockers.add('remote_policy_unknown')
                continue
            if directional_capacity(incoming, True) < incoming_msat:
                blockers.add('inbound_liquidity')
                continue
            if not policy_allows(remote, incoming_msat):
                blockers.add('inbound_policy')
                continue
            routes.append({"incoming": channel_id(incoming), "outgoing": channel_id(outgoing), "fee_msat": fee_msat})
    if not routes:
        result['route_blockers'] = sorted(blockers)
        if 'remote_policy_unknown' in blockers:
            return waiting('graph_pending', '상대 채널 정책 정보가 없어 경로를 아직 확인할 수 없습니다')
        return waiting("liquidity_required", "시험 금액을 전달할 inbound/outbound 또는 peer 정책 조건이 부족합니다")
    return result | {"ready": True, "routes": routes}
